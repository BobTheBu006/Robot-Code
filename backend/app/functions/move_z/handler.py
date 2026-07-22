from app.models.gantry import GantryZMoveRequest
from app.services.hybrid_z_axis import hybrid_z_axis_service


def execute(context: dict, inputs: dict) -> dict:
    request = GantryZMoveRequest.model_validate(inputs)
    result = hybrid_z_axis_service.move_z(context, request)
    result["status"] = "completed"
    result["message"] = f"Moved Z to left {request.z_left_cm:g} cm, right {request.z_right_cm:g} cm."
    return result


def cancel(context: dict, inputs: dict) -> dict:
    hybrid_z_axis_service.emergency_stop()
    return {
        "ok": True,
        "message": "STOP sent to the Z axis ESP32.",
        "tool_port": inputs.get("tool_port"),
        "mode": context.get("mode"),
    }
