import json
from pathlib import Path

from app.services.gripper import ServoSettings, gripper_service

# A setting the caller left out takes the block's own default. Falling back
# to 0 instead once sent both servos to centre - a jump from the closed rack
# position, and open == close for every command after it.
_DEFAULTS = {
    item["key"]: item.get("default")
    for manifest in [json.loads((Path(__file__).parent / "manifest.json").read_text())]
    for item in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]
}


def _setting(inputs: dict, key: str) -> float:
    value = inputs.get(key)
    if value is None or value == "":
        value = _DEFAULTS[key]
    return float(value)


def _servo(inputs: dict, side: str) -> ServoSettings:
    return ServoSettings(
        gpio=int(_setting(inputs, f"{side}_servo_pin")),
        open_deg=_setting(inputs, f"{side}_open_deg"),
        closed_deg=_setting(inputs, f"{side}_closed_deg"),
        pulse_min_us=_setting(inputs, f"{side}_pulse_min_us"),
        pulse_max_us=_setting(inputs, f"{side}_pulse_max_us"),
    )


def execute(context: dict, inputs: dict) -> dict:
    action = str(inputs.get("action") or "close").strip().lower()
    servos = [_servo(inputs, "left"), _servo(inputs, "right")]
    if servos[0].gpio == servos[1].gpio:
        raise ValueError("The left and right gripper servos are on the same GPIO.")

    angles = gripper_service.move(servos, action, _setting(inputs, "ramp_deg_per_s"))
    return {
        "status": "completed",
        "action": action,
        "message": f"Gripper {'opened' if action == 'open' else 'closed'}; servos holding.",
        "left_deg": angles[servos[0].gpio],
        "right_deg": angles[servos[1].gpio],
        "mode": context.get("mode"),
    }


def cancel(context: dict, inputs: dict) -> dict:
    gripper_service.release()
    return {"ok": True, "message": "Gripper pulses stopped.", "mode": context.get("mode")}
