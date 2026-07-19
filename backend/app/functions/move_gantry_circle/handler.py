from app.models.gantry import GantryCircleXYRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.raspberry_gantry import xy_hardware_is_on_raspberry_pi


def execute(context: dict, inputs: dict) -> dict:
    # There is no Raspberry Pi GPIO implementation of the circle move yet, and
    # the ESP32 fallback would drive whatever else is wired to that board, so
    # refuse rather than move the wrong motors.
    if xy_hardware_is_on_raspberry_pi(context):
        raise RuntimeError(
            "Move Gantry Circle is only implemented for an ESP32-driven gantry, but the XY hardware "
            "is mapped to the Raspberry Pi in the Hardware Map. Use Move Gantry XY instead."
        )

    request = GantryCircleXYRequest.model_validate(inputs)
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
