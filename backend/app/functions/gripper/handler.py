from app.services.gripper import ServoSettings, gripper_service


def _servo(inputs: dict, side: str) -> ServoSettings:
    return ServoSettings(
        gpio=int(float(inputs[f"{side}_servo_pin"])),
        open_deg=float(inputs.get(f"{side}_open_deg", 0.0)),
        closed_deg=float(inputs.get(f"{side}_closed_deg", 0.0)),
        pulse_min_us=float(inputs.get(f"{side}_pulse_min_us", 500.0)),
        pulse_max_us=float(inputs.get(f"{side}_pulse_max_us", 2500.0)),
    )


def execute(context: dict, inputs: dict) -> dict:
    action = str(inputs.get("action") or "close").strip().lower()
    servos = [_servo(inputs, "left"), _servo(inputs, "right")]
    if servos[0].gpio == servos[1].gpio:
        raise ValueError("The left and right gripper servos are on the same GPIO.")

    angles = gripper_service.move(servos, action, float(inputs.get("ramp_deg_per_s", 180.0)))
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
