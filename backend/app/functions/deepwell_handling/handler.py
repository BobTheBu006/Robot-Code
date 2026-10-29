"""Move a deepwell lid or plate between its well and a target, with the gripper.

The block is a sequence of the machine's existing blocks - Move XY, Move Z,
Gripper, Pick Up Toolhead - each run through the same path the editor uses,
so pins, ports and safety checks are resolved exactly as for a single block.
The wells sit on the right Z platform; the target is on the left one.
"""

import json
from pathlib import Path
from threading import Event, Lock

from app.core.safety import safety_controller
from app.services.deepwell_positions import deepwell_position_store
from app.services.function_discovery import function_discovery_service
from app.services.toolhead import toolhead_state_store

_DEFAULTS = {
    item["key"]: item.get("default")
    for manifest in [json.loads((Path(__file__).parent / "manifest.json").read_text())]
    for item in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]
}

# action -> (object, direction)
ACTIONS = {
    "take_lid": ("lid", "take"),
    "put_lid": ("lid", "put"),
    "take_plate": ("plate", "take"),
    "return_plate": ("plate", "put"),
}
OBJECT_NAMES = {"lid": "lid", "plate": "deepwell"}

# Motion steps can be cancelled through their own block's cancel. Gripper
# steps are never: cutting the servo pulses would drop what the claws hold.
_cancelled = Event()
_current_lock = Lock()
_current_step: tuple[str, dict] | None = None


class DeepwellHandlingError(RuntimeError):
    pass


def _setting(inputs: dict, key: str) -> float:
    value = inputs.get(key)
    if value is None or value == "":
        value = _DEFAULTS[key]
    return float(value)


def _defaults_of(function_id: str) -> dict:
    """What a freshly placed block would send: its manifest defaults."""
    manifest = function_discovery_service.get_function(function_id).manifest
    return {item.key: item.default for item in [*manifest.inputs, *manifest.advanced_inputs]}


def _run(function_id: str, overrides: dict) -> dict:
    global _current_step
    if _cancelled.is_set():
        raise DeepwellHandlingError("Cancelled.")
    safety_controller.raise_if_blocked("Deepwell handling")
    inputs = {**_defaults_of(function_id), **overrides}
    with _current_lock:
        _current_step = (function_id, inputs)
    try:
        response = function_discovery_service.test_function(function_id, inputs)
    finally:
        with _current_lock:
            _current_step = None
    if not response.ok:
        raise DeepwellHandlingError(response.error or f"{function_id} failed.")
    return response.result


def _plan(inputs: dict) -> list[tuple[str, str, dict]]:
    """The steps as (description, function id, inputs)."""
    action = str(inputs.get("action") or _DEFAULTS["action"]).strip().lower()
    if action not in ACTIONS:
        raise DeepwellHandlingError(f"Unknown action '{action}'.")
    obj, direction = ACTIONS[action]
    name = OBJECT_NAMES[obj]

    well = str(inputs.get("well") or _DEFAULTS["well"]).strip().upper()
    well_x, well_y = deepwell_position_store.position(well)
    target_x, target_y = _setting(inputs, "target_x_cm"), _setting(inputs, "target_y_cm")
    target_z = _setting(inputs, "target_z_cm")
    grab_z = _setting(inputs, f"{obj}_grab_z_cm")
    open_deg, grip_deg = _setting(inputs, f"{obj}_open_deg"), _setting(inputs, f"{obj}_grip_deg")
    travel_left, travel_right = _setting(inputs, "travel_z_left_cm"), _setting(inputs, "travel_z_right_cm")
    xy_speed, z_speed = _setting(inputs, "xy_speed_rpm"), _setting(inputs, "z_speed_rpm")

    # A grab height at or below travel would close the claws on air - the
    # unset defaults look exactly like that, so refuse instead of running.
    if grab_z <= travel_right:
        raise DeepwellHandlingError(
            f"The {name} grab height ({grab_z:g} cm) must be above the right Z travel height "
            f"({travel_right:g} cm). Set it in the block's advanced settings."
        )
    if target_z <= travel_left:
        raise DeepwellHandlingError(
            f"Target Z ({target_z:g} cm) must be above the left Z travel height ({travel_left:g} cm)."
        )
    if open_deg <= grip_deg:
        raise DeepwellHandlingError(
            f"The {name} claw open angle ({open_deg:g}) must be wider than the grip angle ({grip_deg:g}); + opens."
        )

    def xy(x: float, y: float) -> dict:
        return {"x_cm": x, "y_cm": y, "speed_rpm": xy_speed}

    def z(left: float, right: float) -> dict:
        return {"z_left_cm": left, "z_right_cm": right, "speed_rpm": z_speed}

    # Left servo takes +angle, right -angle: the Gripper block's own
    # convention (open +30/-30, closed -90/+90).
    claws_open = {"action": "open", "left_open_deg": open_deg, "right_open_deg": -open_deg}
    claws_grip = {"action": "close", "left_closed_deg": grip_deg, "right_closed_deg": -grip_deg}

    source = (f"well {well}", (well_x, well_y), lambda up: z(travel_left, up), grab_z)
    target = ("the target", (target_x, target_y), lambda up: z(up, travel_right), target_z)
    start, end = (source, target) if direction == "take" else (target, source)

    def lift(place, up: bool) -> tuple[str, str, dict]:
        label, _, heights, height = place
        side = "right" if place is source else "left"
        if up:
            return (f"Raise the {side} Z to {height:g} cm at {label}", "move_z", heights(height))
        return (f"Lower the {side} Z to travel height", "move_z", z(travel_left, travel_right))

    return [
        ("Both Z platforms to travel height", "move_z", z(travel_left, travel_right)),
        (f"Open the claws to {open_deg:g} deg", "gripper", claws_open),
        (f"Move over {start[0]}", "move_gantry_xy", xy(*start[1])),
        lift(start, True),
        (f"Grip the {name} at {grip_deg:g} deg", "gripper", claws_grip),
        lift(start, False),
        (f"Carry the {name} to {end[0]}", "move_gantry_xy", xy(*end[1])),
        lift(end, True),
        (f"Release the {name}", "gripper", claws_open),
        lift(end, False),
    ]


def _ensure_gripper(inputs: dict, log: list[dict]) -> None:
    slot = int(_setting(inputs, "gripper_slot"))
    held = toolhead_state_store.held_index()
    if held == slot:
        return
    if held is not None:
        raise DeepwellHandlingError(
            f"Tool {held} is on the head, not the gripper (slot {slot}). Drop it first."
        )
    _run("pickup_toolhead", {"toolhead_index": slot})
    log.append({"step": f"Pick up the gripper from slot {slot}", "function_id": "pickup_toolhead"})


def execute(context: dict, inputs: dict) -> dict:
    _cancelled.clear()
    action = str(inputs.get("action") or _DEFAULTS["action"]).strip().lower()
    steps = _plan(inputs)  # validate everything before anything moves
    obj = OBJECT_NAMES[ACTIONS[action][0]]
    log: list[dict] = []

    _ensure_gripper(inputs, log)
    for index, (description, function_id, step_inputs) in enumerate(steps, start=1):
        try:
            _run(function_id, step_inputs)
        except Exception as exc:
            in_claws = 5 <= index <= 9  # between grip and release
            raise DeepwellHandlingError(
                f"Stopped at step {index}/{len(steps)} ({description}): {exc}"
                + (f" The {obj} may still be in the claws." if in_claws else "")
            ) from exc
        log.append({"step": description, "function_id": function_id})

    return {
        "status": "completed",
        "message": f"Done: {action.replace('_', ' ')} for well "
                   f"{str(inputs.get('well') or _DEFAULTS['well']).upper()}.",
        "steps": log,
        "mode": context.get("mode"),
    }


def cancel(context: dict, inputs: dict) -> dict:
    _cancelled.set()
    with _current_lock:
        current = _current_step
    if current is None or current[0] == "gripper":
        return {"ok": True, "message": "Deepwell handling will stop after the current step.", "mode": context.get("mode")}
    response = function_discovery_service.cancel_function(*current)
    return {"ok": True, "message": f"Cancelled {current[0]}.", "detail": response.model_dump(), "mode": context.get("mode")}
