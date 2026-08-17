"""Tool changer: rack geometry, held-tool tracking and the pick/drop motion.

The held tool is physical state: a tool stays on the gantry across a backend
restart, so it is persisted to disk rather than kept in memory. It is tracked
through `physical_state_store` so that "I do not know what is on the head" is
representable - see that module for why guessing is what broke this before.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.models.gantry import GantryGotoXYRequest, GantryXYMoveRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.physical_state import PhysicalStateError, physical_state_store
from app.services.raspberry_gantry import (
    planned_move_xy_result,
    raspberry_gantry_gpio_service,
    xy_hardware_is_on_raspberry_pi,
)
from app.services.workspace_defaults import workspace_defaults_service

TOOLHEAD_FACT_ID = "toolhead.held"

# Speed used for every step after the initial approach. The approach speed is
# user-editable; engagement is deliberately slow and fixed.
ENGAGE_RPM = 50

TOOLHEAD_COUNT = 6

# Rack as measured. These seed the block defaults; the exact position of each
# slot is editable per toolhead and an edit is written back as the new default.
DEFAULT_TOOLHEAD_POSITIONS: dict[int, tuple[float, float]] = {
    1: (0.0, 2.7),
    2: (0.0, 12.7),
    3: (0.0, 22.7),
    4: (0.0, 32.7),
    5: (0.0, 42.7),
    6: (0.0, 52.7),
}


class ToolheadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolheadPosition:
    index: int
    x_cm: float
    y_cm: float


def position_for_index(index: int, positions: dict[int, tuple[float, float]]) -> ToolheadPosition:
    if not 1 <= index <= TOOLHEAD_COUNT:
        raise ToolheadError(f"Toolhead index must be between 1 and {TOOLHEAD_COUNT}; got {index}.")
    if index not in positions:
        raise ToolheadError(f"No position is configured for toolhead {index}.")
    x_cm, y_cm = positions[index]
    return ToolheadPosition(index=index, x_cm=round(x_cm, 3), y_cm=round(y_cm, 3))


def _usable_maxima() -> tuple[float | None, float | None]:
    tracks = workspace_defaults_service.current_track_lengths()
    x_track = tracks.get("x_track_length_cm")
    y_track = tracks.get("y_track_length_cm")
    # The buffer is calibrated, not fixed, so read whatever the machine last used.
    buffer_cm = workspace_defaults_service.current_buffer_cm()
    return (
        None if x_track is None else round(x_track - 2.0 * buffer_cm, 3),
        None if y_track is None else round(y_track - 2.0 * buffer_cm, 3),
    )


def _assert_waypoints_reachable(action: str, position: ToolheadPosition, waypoints: list[tuple[float, float]]) -> None:
    """Reject a sequence before it moves, naming the offending waypoint.

    A dip below Y = 0 drives the carriage into the Y-min switch, so this is
    checked against the usable workspace rather than left to the firmware.
    """
    usable_x_max, usable_y_max = _usable_maxima()
    problems: list[str] = []
    for x_cm, y_cm in waypoints:
        if y_cm < 0.0:
            problems.append(
                f"({x_cm:g}, {y_cm:g}) is below Y = 0 by {abs(y_cm):g} cm"
            )
        elif usable_y_max is not None and y_cm > usable_y_max:
            problems.append(f"({x_cm:g}, {y_cm:g}) is above the usable Y max of {usable_y_max:g} cm")
        if x_cm < TOOLHEAD_MIN_X_CM:
            problems.append(
                f"({x_cm:g}, {y_cm:g}) is below the minimum X of {TOOLHEAD_MIN_X_CM:g} cm"
            )
        elif usable_x_max is not None and x_cm > usable_x_max:
            problems.append(f"({x_cm:g}, {y_cm:g}) is above the usable X max of {usable_x_max:g} cm")

    if problems:
        raise ToolheadError(
            f"Toolhead {position.index} cannot {action}: its position "
            f"(X {position.x_cm:g}, Y {position.y_cm:g}) leaves too little room. "
            + "; ".join(problems)
            + ". Move the tool further from the limit, reduce the dip depth, or re-space the rack."
        )


class ToolheadStateStore:
    """Held-tool tracking on top of the certainty-aware physical state store.

    Every read goes through `require_known`, so a tool change that was
    interrupted refuses to guess instead of reporting an empty head.
    """

    def held_index(self) -> int | None:
        """The tool on the gantry, or None. Raises if that is not knowable."""
        fact = physical_state_store.require_known(TOOLHEAD_FACT_ID)
        return fact.value if isinstance(fact.value, int) else None

    def held_index_or_uncertain(self) -> tuple[int | None, bool]:
        """Read without raising, for callers that only want to report state."""
        fact = physical_state_store.get(TOOLHEAD_FACT_ID)
        if fact is None:
            return None, True
        value = fact.value if isinstance(fact.value, int) else None
        return value, not fact.is_known

    def set_held_index(self, index: int | None) -> None:
        physical_state_store.set_known(TOOLHEAD_FACT_ID, index)

    def begin_change(self, provisional_index: int | None, phase: str) -> None:
        """Record the intent before the gantry moves."""
        physical_state_store.begin_transition(
            TOOLHEAD_FACT_ID, provisional_value=provisional_index, phase=phase
        )

    def commit_change(self, index: int | None) -> None:
        physical_state_store.commit_transition(TOOLHEAD_FACT_ID, index)

    def mark_uncertain(self, reason: str) -> None:
        physical_state_store.mark_uncertain(TOOLHEAD_FACT_ID, reason=reason)


toolhead_state_store = ToolheadStateStore()


class ToolheadService:
    def _goto(self, base_inputs: dict, x_cm: float, y_cm: float, speed_rpm: int, context: dict | None = None) -> dict:
        # Route through the same board decision as the move blocks: when the XY
        # gantry lives on Raspberry Pi GPIO, tool changes must not fall back to
        # the ESP32 serial path (there may be no /dev/ttyUSB0 at all, or worse,
        # another board answering on it).
        if context is not None and xy_hardware_is_on_raspberry_pi(context):
            move_request = GantryXYMoveRequest.model_validate(
                {**base_inputs, "x_cm": x_cm, "y_cm": y_cm, "speed_rpm": speed_rpm}
            )
            result = planned_move_xy_result(context, move_request)
            return {
                "x_cm": x_cm,
                "y_cm": y_cm,
                "speed_rpm": speed_rpm,
                "move_reply": result.get("move_reply") or result.get("message"),
            }

        request = GantryGotoXYRequest.model_validate(
            {**base_inputs, "x_cm": x_cm, "y_cm": y_cm, "speed_rpm": speed_rpm}
        )
        response = gantry_controller_service.goto_xy(request)
        return {
            "x_cm": x_cm,
            "y_cm": y_cm,
            "speed_rpm": speed_rpm,
            "move_reply": response.move_reply,
        }

    def pickup_waypoints(
        self, position: ToolheadPosition, dip_depth_cm: float, lift_cm: float, clearance_cm: float
    ) -> list[tuple[float, float]]:
        x, y = position.x_cm, position.y_cm
        engaged_y = round(y - dip_depth_cm + lift_cm, 3)
        return [
            (round(x + clearance_cm, 3), y),
            (x, y),
            (x, round(y - dip_depth_cm, 3)),
            (x, engaged_y),
            (round(x + clearance_cm, 3), engaged_y),
        ]

    def drop_waypoints(
        self, position: ToolheadPosition, dip_depth_cm: float, lift_cm: float, release_cm: float, clearance_cm: float
    ) -> list[tuple[float, float]]:
        """Exact mirror of the pickup exit: approach at the engaged height the
        tool was carried at, slide into the slot, rise past the slot Y by the
        release offset so the holder takes the tool off the hooks, settle onto
        the slot Y, and leave at slot height."""
        x, y = position.x_cm, position.y_cm
        engaged_y = round(y - dip_depth_cm + lift_cm, 3)
        unhook_y = round(y + release_cm, 3)
        return [
            (round(x + clearance_cm, 3), engaged_y),
            (x, engaged_y),
            (x, unhook_y),
            (x, y),
            (round(x + clearance_cm, 3), y),
        ]

    def run_sequence(
        self,
        base_inputs: dict,
        waypoints: list[tuple[float, float]],
        approach_speed_rpm: int,
        context: dict | None = None,
        verify_x_home: bool = False,
    ) -> list[dict]:
        """Run a tool-change sequence: first waypoint at the approach speed,
        every subsequent waypoint at the fixed engage speed.

        With `verify_x_home`, the X min switch is re-touched once the carriage
        is sitting at the clearance offset and before it engages the tool. The
        sequence is already about to drive X to the rack, so the re-home costs
        one short probe and buys back every step X has lost since the last
        home - which is what makes a tool change miss its hooks. Y is left
        alone: it is not the axis being corrected, and re-homing it would drag
        a mounted tool through the rack.
        """
        moves: list[dict] = []
        for step, (x_cm, y_cm) in enumerate(waypoints):
            speed_rpm = approach_speed_rpm if step == 0 else ENGAGE_RPM
            moves.append(self._goto(base_inputs, x_cm, y_cm, speed_rpm, context=context))

            # After the clearance approach, with the tool not yet engaged, is
            # the only point in the sequence where an X probe is safe: the
            # carriage is clear of the hooks and nothing is being carried into
            # them.
            if verify_x_home and step == 0:
                rehome = self._rehome_x(base_inputs, context)
                if rehome is not None:
                    moves.append(rehome)

        return moves

    def _rehome_x(self, base_inputs: dict, context: dict | None) -> dict | None:
        """Re-touch X min mid-sequence. Only on the Pi-driven gantry.

        The ESP32 gantry path has no equivalent single-axis probe, so this is
        skipped there rather than faked - a tool change that silently did not
        verify would be worse than one that never claimed to.
        """
        if context is None or not xy_hardware_is_on_raspberry_pi(context):
            return None

        request = GantryXYMoveRequest.model_validate(
            {**base_inputs, "x_cm": 0.0, "y_cm": 0.0, "speed_rpm": ENGAGE_RPM}
        )
        result = raspberry_gantry_gpio_service.rehome_x(context, request)
        return {
            "action": "verify_x_home",
            "drift_steps": result.get("drift_steps"),
            "drift_cm": result.get("drift_cm"),
            "move_reply": result.get("message"),
        }

    def drop(
        self,
        base_inputs: dict,
        position: ToolheadPosition,
        approach_speed_rpm: int,
        dip_depth_cm: float,
        lift_cm: float,
        release_cm: float,
        clearance_cm: float,
        context: dict | None = None,
        verify_x_home: bool = False,
    ) -> list[dict]:
        waypoints = self.drop_waypoints(position, dip_depth_cm, lift_cm, release_cm, clearance_cm)
        _assert_waypoints_reachable("be dropped", position, waypoints)

        # Declare the intent before moving, keeping the tool index as the
        # provisional value. If the sequence is interrupted, "might still be
        # holding it" is the safe belief - assuming the head came back empty is
        # what let the next pick-up drive a loaded head into the rack.
        toolhead_state_store.begin_change(position.index, f"dropping toolhead {position.index}")
        moves = self.run_sequence(
            base_inputs, waypoints, approach_speed_rpm, context=context, verify_x_home=verify_x_home
        )
        toolhead_state_store.commit_change(None)
        return moves

    def pickup(
        self,
        base_inputs: dict,
        position: ToolheadPosition,
        approach_speed_rpm: int,
        dip_depth_cm: float,
        lift_cm: float,
        clearance_cm: float,
        context: dict | None = None,
        verify_x_home: bool = False,
    ) -> list[dict]:
        waypoints = self.pickup_waypoints(position, dip_depth_cm, lift_cm, clearance_cm)
        _assert_waypoints_reachable("be picked up", position, waypoints)

        # Same conservative rule as drop(): from the first move onwards the
        # head may already be carrying this tool, so that is the provisional
        # value an interrupted sequence leaves behind.
        toolhead_state_store.begin_change(position.index, f"picking up toolhead {position.index}")
        moves = self.run_sequence(
            base_inputs, waypoints, approach_speed_rpm, context=context, verify_x_home=verify_x_home
        )
        toolhead_state_store.commit_change(position.index)
        return moves


toolhead_service = ToolheadService()
