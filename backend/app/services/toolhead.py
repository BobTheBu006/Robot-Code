"""Tool changer: rack geometry, held-tool tracking and the pick/drop motion.

The held tool is physical state: a tool stays on the gantry across a backend
restart, so the index is persisted to disk rather than kept in memory. If it
were only in memory, a restart while holding a tool would make the next pick-up
skip its automatic drop and drive a held tool into the rack.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from app.models.gantry import GantryGotoXYRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.workspace_defaults import workspace_defaults_service

# Speed used for every step after the initial approach. The approach speed is
# user-editable; engagement is deliberately slow and fixed.
ENGAGE_RPM = 50

TOOLHEAD_COUNT = 6

# Rack as measured. These seed the block defaults; the exact position of each
# slot is editable per toolhead and an edit is written back as the new default.
DEFAULT_TOOLHEAD_POSITIONS: dict[int, tuple[float, float]] = {
    1: (0.0, 3.2),
    2: (0.0, 13.2),
    3: (0.0, 23.2),
    4: (0.0, 33.2),
    5: (0.0, 43.2),
    6: (0.0, 53.2),
}

_STATE_PATH = Path(__file__).resolve().parents[3] / "toolhead-state.json"


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
        if x_cm < 0.0:
            problems.append(f"({x_cm:g}, {y_cm:g}) is below X = 0")
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
    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._lock = Lock()

    def _read(self) -> dict:
        if not self._state_path.exists():
            return {}
        try:
            with self._state_path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, payload: dict) -> None:
        temp_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        temp_path.replace(self._state_path)

    def held_index(self) -> int | None:
        with self._lock:
            value = self._read().get("held_index")
            return value if isinstance(value, int) else None

    def set_held_index(self, index: int | None) -> None:
        with self._lock:
            payload = self._read()
            payload["held_index"] = index
            self._write(payload)


toolhead_state_store = ToolheadStateStore(_STATE_PATH)


class ToolheadService:
    def _goto(self, base_inputs: dict, x_cm: float, y_cm: float, speed_rpm: int) -> dict:
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
        x, y = position.x_cm, position.y_cm
        engaged_y = round(y - dip_depth_cm + lift_cm, 3)
        released_y = round(y - release_cm, 3)
        return [
            (round(x + clearance_cm, 3), engaged_y),
            (x, engaged_y),
            (x, y),
            (x, released_y),
            (round(x + clearance_cm, 3), released_y),
        ]

    def run_sequence(
        self,
        base_inputs: dict,
        waypoints: list[tuple[float, float]],
        approach_speed_rpm: int,
    ) -> list[dict]:
        """Run a tool-change sequence: first waypoint at the approach speed,
        every subsequent waypoint at the fixed engage speed."""
        moves: list[dict] = []
        for step, (x_cm, y_cm) in enumerate(waypoints):
            speed_rpm = approach_speed_rpm if step == 0 else ENGAGE_RPM
            moves.append(self._goto(base_inputs, x_cm, y_cm, speed_rpm))
        return moves

    def drop(
        self,
        base_inputs: dict,
        position: ToolheadPosition,
        approach_speed_rpm: int,
        dip_depth_cm: float,
        lift_cm: float,
        release_cm: float,
        clearance_cm: float,
    ) -> list[dict]:
        waypoints = self.drop_waypoints(position, dip_depth_cm, lift_cm, release_cm, clearance_cm)
        _assert_waypoints_reachable("be dropped", position, waypoints)
        moves = self.run_sequence(base_inputs, waypoints, approach_speed_rpm)
        toolhead_state_store.set_held_index(None)
        return moves

    def pickup(
        self,
        base_inputs: dict,
        position: ToolheadPosition,
        approach_speed_rpm: int,
        dip_depth_cm: float,
        lift_cm: float,
        clearance_cm: float,
    ) -> list[dict]:
        waypoints = self.pickup_waypoints(position, dip_depth_cm, lift_cm, clearance_cm)
        _assert_waypoints_reachable("be picked up", position, waypoints)
        moves = self.run_sequence(base_inputs, waypoints, approach_speed_rpm)
        toolhead_state_store.set_held_index(position.index)
        return moves


toolhead_service = ToolheadService()
