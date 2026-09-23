from app.models.gantry import GantryGotoXYRequest
from app.models.toolhead import ToolheadPickupRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.pogo_connector import ConnectorError, pogo_connector_service
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




def _connect_tool(toolhead_index: int, *, reverify: bool):
    """Hand the pogo connector to the tool now on the head, or leave it empty
    when that tool has no electrical connection."""
    try:
        return pogo_connector_service.connect_for_toolhead(toolhead_index, reverify=reverify)
    except ConnectorError as exc:
        # The tool is physically on the head either way; only its connection
        # is in doubt, so say exactly that rather than failing as a pick-up.
        raise RuntimeError(f"Toolhead {toolhead_index} is on the head, but its connector check failed: {exc}") from exc


def _gantry_base_inputs(inputs: dict) -> dict:
    return {key: value for key, value in inputs.items() if key in _GANTRY_KEYS}


def execute(context: dict, inputs: dict) -> dict:
    request = ToolheadPickupRequest.model_validate(inputs)
    base_inputs = _gantry_base_inputs(inputs)
    positions = request.positions()
    target = position_for_index(request.toolhead_index, positions)

    held_index = toolhead_state_store.held_index()
    if held_index == request.toolhead_index:
        # Nothing moves, but the connector must still describe this tool - a
        # manual Disconnect Tool may have emptied it since the pick-up.
        connector_results = _connect_tool(request.toolhead_index, reverify=False)
        return {
            "status": "completed",
            "message": f"Toolhead {request.toolhead_index} is already held; no move was made.",
            "toolhead_index": request.toolhead_index,
            "held_index": held_index,
            "already_held": True,
            "connector": [result.as_dict() for result in connector_results],
            "auto_dropped_index": None,
            "drop_moves": [],
            "pickup_moves": [],
            "engage_speed_rpm": ENGAGE_RPM,
            "mode": context.get("mode"),
        }

    # A tool already on the gantry must go back to its own slot before a new one
    # can be collected, otherwise the pick-up drives a loaded head into the rack.
    drop_moves: list[dict] = []
    auto_dropped_index = None
    if held_index is not None:
        # Release the connector before its contacts separate.
        pogo_connector_service.deactivate()
        held_position = position_for_index(held_index, positions)
        drop_moves = toolhead_service.drop(
            base_inputs=base_inputs,
            position=held_position,
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
        auto_dropped_index = held_index

    pickup_moves = toolhead_service.pickup(
        base_inputs=base_inputs,
        position=target,
        approach_speed_rpm=request.approach_speed_rpm,
        dip_depth_cm=request.dip_depth_cm,
        lift_cm=request.lift_cm,
        clearance_cm=request.pickup_clearance_cm,
        context=context,
        verify_x_home=request.verify_x_home,
        rack_approach_speed_rpm=request.rack_approach_speed_rpm,
        home_speed_rpm=request.home_speed_rpm,
    )

    connector_results = _connect_tool(target.index, reverify=True)

    # Persist only after the sequence succeeds, so a position that the guard
    # rejected is never adopted as the new default.
    position_changes = workspace_defaults_service.apply_toolhead_defaults(
        _supplied_toolhead_defaults(inputs)
    )

    if auto_dropped_index is None:
        message = f"Picked up toolhead {target.index} at X {target.x_cm:g}, Y {target.y_cm:g}."
    else:
        message = (
            f"Dropped toolhead {auto_dropped_index} first, then picked up toolhead {target.index} "
            f"at X {target.x_cm:g}, Y {target.y_cm:g}."
        )

    return {
        "status": "completed",
        "message": message,
        "toolhead_index": target.index,
        "held_index": toolhead_state_store.held_index(),
        "already_held": False,
        "connector": [result.as_dict() for result in connector_results],
        "auto_dropped_index": auto_dropped_index,
        "target_x_cm": target.x_cm,
        "target_y_cm": target.y_cm,
        "approach_speed_rpm": request.approach_speed_rpm,
        "engage_speed_rpm": ENGAGE_RPM,
        "drop_moves": drop_moves,
        "pickup_moves": pickup_moves,
        "toolhead_position_defaults_updated": position_changes,
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
