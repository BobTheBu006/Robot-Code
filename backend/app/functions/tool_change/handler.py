from app.models.gantry import GantryXYMoveRequest, GantryZMoveRequest, ToolChangeRequest
from app.services.gantry_controller import gantry_controller_service


def _xy_request(request: ToolChangeRequest, x_cm: float, y_cm: float) -> GantryXYMoveRequest:
    return GantryXYMoveRequest(
        tool_port=request.tool_port,
        x_cm=x_cm,
        y_cm=y_cm,
        speed_profile=request.speed_profile,
        x_step_pin=request.x_step_pin,
        x_dir_pin=request.x_dir_pin,
        y_step_pin=request.y_step_pin,
        y_dir_pin=request.y_dir_pin,
        limit_switch_mode=request.limit_switch_mode,
        x_min_limit_pin=request.x_min_limit_pin,
        x_max_limit_pin=request.x_max_limit_pin,
        y_min_limit_pin=request.y_min_limit_pin,
        y_max_limit_pin=request.y_max_limit_pin,
        baud_rate=request.baud_rate,
    )


def _z_request(request: ToolChangeRequest, z_cm: float) -> GantryZMoveRequest:
    return GantryZMoveRequest(
        tool_port=request.tool_port,
        z_left_cm=z_cm,
        z_right_cm=z_cm,
        speed_profile=request.speed_profile,
        z_left_step_pin=request.z_left_step_pin,
        z_left_dir_pin=request.z_left_dir_pin,
        z_right_step_pin=request.z_right_step_pin,
        z_right_dir_pin=request.z_right_dir_pin,
        limit_switch_mode=request.limit_switch_mode,
        z_left_min_limit_pin=request.z_left_min_limit_pin,
        z_left_max_limit_pin=request.z_left_max_limit_pin,
        z_right_min_limit_pin=request.z_right_min_limit_pin,
        z_right_max_limit_pin=request.z_right_max_limit_pin,
        baud_rate=request.baud_rate,
    )


def _sequence_for_request(request: ToolChangeRequest) -> list[dict[str, float | str]]:
    slot_position = request.slot_position()
    slot_x = slot_position["x_cm"]
    slot_y = slot_position["y_cm"]
    slot_z = slot_position["z_cm"]
    left_x = slot_x - request.lateral_offset_cm
    back_y = slot_y - request.backoff_y_cm

    get_sequence: list[dict[str, float | str]] = [
        {"label": "approach_slot", "x_cm": slot_x, "y_cm": slot_y, "z_cm": slot_z},
        {"label": "move_left_into_tool", "x_cm": left_x, "y_cm": slot_y, "z_cm": slot_z},
        {"label": "move_back_lock_tool", "x_cm": left_x, "y_cm": back_y, "z_cm": slot_z},
        {"label": "move_right_clear_rack", "x_cm": slot_x, "y_cm": back_y, "z_cm": slot_z},
    ]

    if request.action == "get_tool":
        return get_sequence

    return [
        {"label": "approach_loaded_tool", "x_cm": slot_x, "y_cm": back_y, "z_cm": slot_z},
        {"label": "move_left_to_drop_lane", "x_cm": left_x, "y_cm": back_y, "z_cm": slot_z},
        {"label": "move_forward_release_tool", "x_cm": left_x, "y_cm": slot_y, "z_cm": slot_z},
        {"label": "move_right_clear_empty_tool", "x_cm": slot_x, "y_cm": slot_y, "z_cm": slot_z},
    ]


def execute(context: dict, inputs: dict) -> dict:
    request = ToolChangeRequest.model_validate(inputs)
    sequence = _sequence_for_request(request)
    results: list[dict[str, object]] = []

    for step in sequence:
        label = str(step["label"])
        x_cm = float(step["x_cm"])
        y_cm = float(step["y_cm"])
        z_cm = float(step["z_cm"])
        z_response = gantry_controller_service.move_z(_z_request(request, z_cm))
        xy_response = gantry_controller_service.move_xy(_xy_request(request, x_cm, y_cm))
        results.append({
            "label": label,
            "target": {
                "x_cm": x_cm,
                "y_cm": y_cm,
                "z_cm": z_cm,
            },
            "z_move_applied": z_response.move_applied,
            "xy_move_applied": xy_response.move_applied,
            "z_move_command_sent": z_response.move_command_sent,
            "xy_move_command_sent": xy_response.move_command_sent,
            "z_move_reply": z_response.move_reply,
            "xy_move_reply": xy_response.move_reply,
        })

    return {
        "accepted": all(
            bool(result["z_move_applied"]) and bool(result["xy_move_applied"])
            for result in results
        ),
        "status": "completed",
        "message": f"Tool change {request.action.replace('_', ' ')} sequence completed.",
        "action": request.action,
        "slot": request.slot,
        "slot_position": request.slot_position(),
        "sequence": sequence,
        "steps": results,
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
