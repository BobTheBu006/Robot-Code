from app.models.gantry import GantryXYCalibrationRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.raspberry_gantry import planned_calibrate_xy_result, xy_hardware_is_on_raspberry_pi
from app.services.workspace_defaults import workspace_defaults_service


def execute(context: dict, inputs: dict) -> dict:
    request = GantryXYCalibrationRequest.model_validate(inputs)
    if xy_hardware_is_on_raspberry_pi(context):
        result = planned_calibrate_xy_result(context, request)
        # The write-back below must run on this path too: the Pi-driven machine
        # is the one actually calibrating, so its track lengths and buffer are
        # the ones the block defaults and move ranges should follow.
        result["workspace_defaults"] = workspace_defaults_service.apply_track_lengths(
            request.x_track_length_cm, request.y_track_length_cm, request.limit_buffer_cm
        )
        return result

    response = gantry_controller_service.calibrate_xy(request)

    # The track lengths just calibrated against become the new defaults, and the
    # usable ranges on the move blocks are re-derived from them, so the whole app
    # follows the machine as measured instead of the values authored by hand.
    workspace = workspace_defaults_service.apply_track_lengths(
        request.x_track_length_cm, request.y_track_length_cm, request.limit_buffer_cm
    )

    return {
        "workspace_defaults": workspace,
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
