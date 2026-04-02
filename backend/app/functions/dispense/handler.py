from app.models.syringe import SyringeDispenseRequest
from app.services.syringe_controller import syringe_controller_service


def execute(context: dict, inputs: dict) -> dict:
    request = SyringeDispenseRequest.model_validate(
        {
            "port": inputs.get("tool_port"),
            "calibration_file": inputs.get("calibration_file"),
            "speed": inputs.get("speed") or None,
            "baud_rate": inputs.get("baud_rate"),
            "A": inputs.get("A", 0),
            "B": inputs.get("B", 0),
            "C": inputs.get("C", 0),
            "D": inputs.get("D", 0),
            "E": inputs.get("E", 0),
            "F": inputs.get("F", 0),
            "G": inputs.get("G", 0),
        }
    )

    response = syringe_controller_service.dispense(request)

    return {
        "status": "completed",
        "reply": response.reply,
        "port": response.port,
        "baud_rate": response.baud_rate,
        "calibration_file": response.calibration_file,
        "command_format": response.command_format,
        "speed": response.speed,
        "speed_command_sent": response.speed_command_sent,
        "speed_reply": response.speed_reply,
        "speed_applied": response.speed_applied,
        "command_sent": response.command_sent,
        "requested_amounts": response.requested_amounts,
        "calculated_steps": response.calculated_steps,
        "mode": context.get("mode"),
    }
