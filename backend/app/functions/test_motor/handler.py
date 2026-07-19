from app.models.gantry import GantryTestMotorRequest
from app.services.gantry_controller import gantry_controller_service
from app.services.raspberry_gantry import planned_test_motor_result, xy_hardware_is_on_raspberry_pi


def execute(context: dict, inputs: dict) -> dict:
    request = GantryTestMotorRequest.model_validate(inputs)
    # The motors may be driven straight from Pi GPIO rather than over serial; the
    # ESP32 path would otherwise send motor commands to whatever else is on that
    # port.
    if xy_hardware_is_on_raspberry_pi(context):
        return planned_test_motor_result(context, request)

    response = gantry_controller_service.test_motor(request)

    return {
        "status": "completed",
        "message": (
            f"Pulsed CoreXY motor {response.motor} {response.steps} steps "
            f"{'forward' if response.forward else 'backward'} at {response.speed_rpm} RPM. "
            "On a CoreXY the carriage moves diagonally when only one motor turns. "
            "The gantry calibration was dropped because this move is not position-tracked."
        ),
        "tool_port": response.port,
        "motor": response.motor,
        "steps": response.steps,
        "forward": response.forward,
        "speed_rpm": response.speed_rpm,
        "pin_command_sent": response.pin_command_sent,
        "pin_reply": response.pin_reply,
        "limit_command_sent": response.limit_command_sent,
        "limit_reply": response.limit_reply,
        "test_command_sent": response.test_command_sent,
        "test_reply": response.test_reply,
        "configured_pins": response.configured_pins,
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
