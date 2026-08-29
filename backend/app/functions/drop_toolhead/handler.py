from app.models.gantry import GantryGotoXYRequest
from app.models.toolhead import ToolheadDropRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.toolhead import (
    ENGAGE_RPM,
    position_for_index,
    toolhead_service,
    toolhead_state_store,
)
from app.services.workspace_defaults import TOOLHEAD_DEFAULT_KEYS, workspace_defaults_service

_GANTRY_KEYS = set(GantryGotoXYRequest.model_fields) - {"x_cm", "y_cm", "speed_rpm"}

# Advanced settings that describe the rack and the tool-change motion. Hardware
# pins are excluded: the Hardware Map owns those.
_TOOLHEAD_DEFAULT_KEYS = TOOLHEAD_DEFAULT_KEYS


def _supplied_toolhead_defaults(inputs: dict) -> dict:
    """Only the settings actually passed in, so an omitted field never resets a
    measurement tuned on the machine."""
    return {
        key: float(value)
        for key, value in inputs.items()
        if key in _TOOLHEAD_DEFAULT_KEYS and value is not None
    }




def _gantry_base_inputs(inputs: dict) -> dict:
    return {key: value for key, value in inputs.items() if key in _GANTRY_KEYS}


def execute(context: dict, inputs: dict) -> dict:
    # A drop must return the tool along the same geometry it was picked up
    # with, so the rack measurements always come from the latest shared
    # defaults rather than whatever this block carried when it was placed -
    # a stale drop block must not aim at an outdated slot position.
    inputs = {**inputs, **workspace_defaults_service.current_toolhead_defaults()}
    request = ToolheadDropRequest.model_validate(inputs)
    base_inputs = _gantry_base_inputs(inputs)

    # The slot to return to is whichever tool is currently held, so the block
    # needs no index of its own.
    held_index = toolhead_state_store.held_index()
    if held_index is None:
        return {
            "status": "completed",
            "message": "No toolhead is currently held; nothing to drop.",
            "toolhead_index": None,
            "held_index": None,
            "dropped": False,
            "drop_moves": [],
            "engage_speed_rpm": ENGAGE_RPM,
            "mode": context.get("mode"),
        }

    position = position_for_index(held_index, request.positions())
    drop_moves = toolhead_service.drop(
        base_inputs=base_inputs,
        position=position,
        approach_speed_rpm=request.approach_speed_rpm,
        dip_depth_cm=request.dip_depth_cm,
        lift_cm=request.lift_cm,
        release_cm=request.release_cm,
        clearance_cm=request.drop_clearance_cm,
        context=context,
        verify_x_home=request.verify_x_home,
        rack_approach_speed_rpm=request.rack_approach_speed_rpm,
        home_speed_rpm=request.home_speed_rpm,
    )

    # Persist only after the sequence succeeds, so a position that the guard
    # rejected is never adopted as the new default.
    position_changes = workspace_defaults_service.apply_toolhead_defaults(
        _supplied_toolhead_defaults(inputs)
    )

    return {
        "status": "completed",
        "message": f"Dropped toolhead {position.index} at X {position.x_cm:g}, Y {position.y_cm:g}.",
        "toolhead_position_defaults_updated": position_changes,
        "toolhead_index": position.index,
        "held_index": toolhead_state_store.held_index(),
        "dropped": True,
        "target_x_cm": position.x_cm,
        "target_y_cm": position.y_cm,
        "approach_speed_rpm": request.approach_speed_rpm,
        "engage_speed_rpm": ENGAGE_RPM,
        "drop_moves": drop_moves,
        "mode": context.get("mode"),
    }


def cancel(context: dict, inputs: dict) -> dict:
    response = gantry_controller_service.cancel_operation(inputs.get("tool_port"))
    return {
        "ok": response["ok"],
        "message": response["message"],
        "tool_port": response.get("tool_port"),
        "mode": context.get("mode"),
    }
