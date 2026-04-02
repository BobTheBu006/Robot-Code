from app.models.syringe import SyringeDispenseRequest
from app.services.syringe_controller import syringe_controller_service


def execute(context: dict, inputs: dict) -> dict:
    request = SyringeDispenseRequest.model_validate(
        {
            "port": inputs.get("tool_port"),
            "calibration_file": inputs.get("calibration_file"),
            "speed": inputs.get("speed") or None,
            "intake_speed": inputs.get("intake_speed") or None,
            "outtake_speed": inputs.get("outtake_speed") or None,
            "head_a_step_pin": inputs.get("head_a_step_pin"),
            "head_a_dir_pin": inputs.get("head_a_dir_pin"),
            "head_b_step_pin": inputs.get("head_b_step_pin"),
            "head_b_dir_pin": inputs.get("head_b_dir_pin"),
            "head_c_step_pin": inputs.get("head_c_step_pin"),
            "head_c_dir_pin": inputs.get("head_c_dir_pin"),
            "head_d_step_pin": inputs.get("head_d_step_pin"),
            "head_d_dir_pin": inputs.get("head_d_dir_pin"),
            "head_e_step_pin": inputs.get("head_e_step_pin"),
            "head_e_dir_pin": inputs.get("head_e_dir_pin"),
            "head_f_step_pin": inputs.get("head_f_step_pin"),
            "head_f_dir_pin": inputs.get("head_f_dir_pin"),
            "head_g_step_pin": inputs.get("head_g_step_pin"),
            "head_g_dir_pin": inputs.get("head_g_dir_pin"),
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
        "intake_speed": response.intake_speed,
        "outtake_speed": response.outtake_speed,
        "speed_command_sent": response.speed_command_sent,
        "speed_reply": response.speed_reply,
        "speed_applied": response.speed_applied,
        "intake_speed_command_sent": response.intake_speed_command_sent,
        "intake_speed_reply": response.intake_speed_reply,
        "intake_speed_applied": response.intake_speed_applied,
        "outtake_speed_command_sent": response.outtake_speed_command_sent,
        "outtake_speed_reply": response.outtake_speed_reply,
        "outtake_speed_applied": response.outtake_speed_applied,
        "pin_config_commands_sent": response.pin_config_commands_sent,
        "pin_config_replies": response.pin_config_replies,
        "pin_config_applied": response.pin_config_applied,
        "configured_pins": response.configured_pins,
        "command_sent": response.command_sent,
        "requested_amounts": response.requested_amounts,
        "calculated_steps": response.calculated_steps,
        "mode": context.get("mode"),
    }
