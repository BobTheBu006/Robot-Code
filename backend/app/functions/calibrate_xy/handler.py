from app.models.gantry import GantryXYCalibrationRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.raspberry_gantry import planned_calibrate_xy_result, xy_hardware_is_on_raspberry_pi


def execute(context: dict, inputs: dict) -> dict:
    request = GantryXYCalibrationRequest.model_validate(inputs)
    if xy_hardware_is_on_raspberry_pi(context):
        return planned_calibrate_xy_result(context, request)

    response = gantry_controller_service.calibrate_xy(request)

    return {
        "calibrated": response.calibrated,
        "status": "completed",
        "message": "X gantry calibration completed.",
        "tool_port": response.port,
        "workspace": response.workspace,
        "calibration_speed_profile": response.calibration_speed_profile,
        "speed_rpm": response.speed_rpm,
        "trapezoidal_speed": response.trapezoidal_speed,
        "acceleration_rpm_per_s": response.acceleration_rpm_per_s,
        "steps_per_rotation": response.steps_per_rotation,
        "max_probe_rotations": response.max_probe_rotations,
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
