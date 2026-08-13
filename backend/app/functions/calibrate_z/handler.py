from app.models.gantry import GantryZCalibrationRequest
from app.services.hybrid_z_axis import hybrid_z_axis_service
from app.services.workspace_defaults import workspace_defaults_service


def execute(context: dict, inputs: dict) -> dict:
    request = GantryZCalibrationRequest.model_validate(inputs)
    result = hybrid_z_axis_service.calibrate_z(context, request)

    # What was just measured becomes what the app offers next: these track
    # lengths are the new defaults on this block, and the usable travel derived
    # from them becomes the allowed range on Move Z. Same write-back the XY
    # calibration does, so the app follows the machine as measured rather than
    # numbers typed in once and never revisited.
    #
    # Only when a side actually calibrated - a run that skipped an axis, or
    # stopped part way, has not measured anything worth adopting.
    if result.get("calibrated") or result.get("left_calibrated") or result.get("right_calibrated"):
        result["workspace_defaults"] = workspace_defaults_service.apply_z_track_lengths(
            request.z_left_track_length_cm,
            request.z_right_track_length_cm,
            request.limit_buffer_cm,
        )

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
