from app.models.gantry import GantryXMoveRequest
from app.services.gantry_controller import gantry_controller_service


def execute(context: dict, inputs: dict) -> dict:
    request = GantryXMoveRequest.model_validate(inputs)
    response = gantry_controller_service.move_x(request)

    return {
        "status": "completed",
        "message": f"Gantry moved to X = {request.x_cm:.3f} cm.",
        "tool_port": response.port,
        "target": response.target,
        "speed_profile": response.speed_profile,
        "speed_rpm": response.speed_rpm,
        "pin_command_sent": response.pin_command_sent,
        "pin_reply": response.pin_reply,
        "pins_applied": response.pins_applied,
        "limit_command_sent": response.limit_command_sent,
        "limit_reply": response.limit_reply,
        "limits_applied": response.limits_applied,
        "move_command_sent": response.move_command_sent,
        "move_reply": response.move_reply,
        "move_applied": response.move_applied,
        "configured_pins": response.configured_pins,
        "configured_limits": response.configured_limits,
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
