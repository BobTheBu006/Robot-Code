from app.models.gantry import GantryZCalibrationRequest
from app.services.hybrid_z_axis import hybrid_z_axis_service


def execute(context: dict, inputs: dict) -> dict:
    request = GantryZCalibrationRequest.model_validate(inputs)
    result = hybrid_z_axis_service.calibrate_z(context, request)
    result["status"] = "completed"
    result["message"] = "Z axis calibration completed."
    return result


def cancel(context: dict, inputs: dict) -> dict:
    hybrid_z_axis_service.emergency_stop()
    return {
        "ok": True,
        "message": "STOP sent to the Z axis ESP32.",
        "tool_port": inputs.get("tool_port"),
        "mode": context.get("mode"),
    }
