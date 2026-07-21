from app.models.gantry import GantryCircleXYRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.raspberry_gantry import planned_circle_xy_result, xy_hardware_is_on_raspberry_pi


def execute(context: dict, inputs: dict) -> dict:
    request = GantryCircleXYRequest.model_validate(inputs)

    if xy_hardware_is_on_raspberry_pi(context):
        result = planned_circle_xy_result(context, request)
        return {
            "status": "completed",
            "message": (
                f"Gantry traced {request.repeat_count} circle"
                f"{'' if request.repeat_count == 1 else 's'} around X = {request.center_x_cm:.3f} cm, "
                f"Y = {request.center_y_cm:.3f} cm with radius {request.radius_cm:.3f} cm."
            ),
            "tool_port": result["port"],
            "center": result["center"],
            "radius_cm": result["radius_cm"],
            "repeat_count": result["repeat_count"],
            "speed_profile": result["speed_profile"],
            "speed_rpm": result["speed_rpm"],
            "trapezoidal_speed": result["trapezoidal_speed"],
            "acceleration_rpm_per_s": result["acceleration_rpm_per_s"],
            "pin_command_sent": result["pin_command_sent"],
            "pin_reply": result["pin_reply"],
            "pins_applied": result["pins_applied"],
            "limit_command_sent": result["limit_command_sent"],
            "limit_reply": result["limit_reply"],
            "limits_applied": result["limits_applied"],
            "move_command_sent": result["move_command_sent"],
            "move_reply": result["move_reply"],
            "move_applied": result["move_applied"],
            "configured_pins": result["configured_pins"],
            "configured_limits": result["configured_limits"],
            "mode": context.get("mode"),
        }

    response = gantry_controller_service.circle_xy(request)

    return {
        "status": "completed",
        "message": (
            f"Gantry traced {request.repeat_count} circle"
            f"{'' if request.repeat_count == 1 else 's'} around X = {request.center_x_cm:.3f} cm, "
            f"Y = {request.center_y_cm:.3f} cm with radius {request.radius_cm:.3f} cm."
        ),
        "tool_port": response.port,
        "center": response.center,
        "radius_cm": response.radius_cm,
        "repeat_count": response.repeat_count,
        "speed_profile": response.speed_profile,
        "speed_rpm": response.speed_rpm,
        "trapezoidal_speed": response.trapezoidal_speed,
        "acceleration_rpm_per_s": response.acceleration_rpm_per_s,
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
