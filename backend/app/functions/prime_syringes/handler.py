from app.models.syringe import SyringePrimeRequest
from app.services.syringe_controller import syringe_controller_service


def execute(context: dict, inputs: dict) -> dict:
    request = SyringePrimeRequest.model_validate(
        {
            "port": inputs.get("tool_port"),
            "calibration_file": inputs.get("calibration_file"),
            "home_overtravel_ul": inputs.get("home_overtravel_ul", 1000),
            "prime_volume_ul": inputs.get("prime_volume_ul", 1000),
            "prime_cycles": int(inputs.get("prime_cycles") or 3),
            "final_draw_ul": inputs.get("final_draw_ul", 1000),
            "speed": int(inputs.get("speed") or 60),
            "baud_rate": inputs.get("baud_rate"),
            # Per-head step/dir pins resolved from the Hardware Map; without
            # them the firmware falls back to its compiled-in pinout, which no
            # longer matches the wiring.
            **{
                f"head_{head}_{signal}_pin": inputs.get(f"head_{head}_{signal}_pin")
                for head in "abcdefg"
                for signal in ("step", "dir")
            },
        }
    )

    response = syringe_controller_service.prime(request)

    return {
        "status": "completed",
        "message": (
            f"Homed all plungers against the hard stop, then primed with "
            f"{response.prime_cycles} draw/push cycles of {response.prime_volume_ul:g} µl "
            f"at {response.speed} RPM."
        ),
        "port": response.port,
        "baud_rate": response.baud_rate,
        "calibration_file": response.calibration_file,
        "speed": response.speed,
        "prime_volume_ul": response.prime_volume_ul,
        "prime_cycles": response.prime_cycles,
        "home_overtravel_ul": response.home_overtravel_ul,
        "final_draw_ul": response.final_draw_ul,
        "final_draw_steps": response.final_draw_steps,
        "home_steps": response.home_steps,
        "prime_steps": response.prime_steps,
        "pin_config_applied": response.pin_config_applied,
        "configured_pins": response.configured_pins,
        "commands_sent": response.commands_sent,
        "replies": response.replies,
        "mode": context.get("mode"),
    }
