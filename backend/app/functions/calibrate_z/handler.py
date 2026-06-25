from app.models.gantry import GantryZCalibrationRequest
from app.services.gantry_controller import gantry_controller_service


def execute(context: dict, inputs: dict) -> dict:
    request = GantryZCalibrationRequest.model_validate(inputs)
    response = gantry_controller_service.calibrate_z(request)

    return {
        "calibrated": response.calibrated,
        "status": "completed",
        "message": "Z gantry calibration completed.",
        "tool_port": response.port,
        "workspace": response.workspace,
        "calibration_speed_profile": response.calibration_speed_profile,
        "speed_rpm": response.speed_rpm,
        "trapezoidal_speed": response.trapezoidal_speed,
        "acceleration_rpm_per_s": response.acceleration_rpm_per_s,
        "pin_command_sent": response.pin_command_sent,
        "pin_reply": response.pin_reply,
        "pins_applied": response.pins_applied,
        "limit_command_sent": response.limit_command_sent,
        "limit_reply": response.limit_reply,
        "limits_applied": response.limits_applied,
        "calibration_command_sent": response.calibration_command_sent,
        "calibration_reply": response.calibration_reply,
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
