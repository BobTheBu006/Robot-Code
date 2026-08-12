"""Dispense through the peristaltic pumps.

Volumes are per pump and run concurrently: pumps with a non-zero volume all
start together, each at its own speed. Zero leaves a pump alone, so a workflow
that only wants pump 3 sets one field and ignores the rest.
"""

from app.services.peristaltic_pumps import (
    PUMP_COUNT,
    PeristalticPumpError,
    PumpCommand,
    peristaltic_pump_service,
    steps_for_volume,
)

DEFAULT_SPEED_RPM = 60


def _number(inputs: dict, key: str, default: float) -> float:
    value = inputs.get(key)
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _calibration_for(context: dict, index: int) -> float:
    """mL per 200 steps for one pump, straight from the Hardware Map.

    Read per run rather than baked into the block, so recalibrating a pump takes
    effect everywhere without editing workflows.
    """
    hardware_map = context.get("hardware_map")
    devices = hardware_map.get("devices") if isinstance(hardware_map, dict) else None
    for device in devices or []:
        if isinstance(device, dict) and device.get("id") == f"peristaltic-pump-{index}":
            return float(device.get("calibration_ml_per_200_steps") or 0.0)
    return 0.0


def execute(context: dict, inputs: dict) -> dict:
    commands: list[PumpCommand] = []
    planned: list[dict] = []

    for index in range(1, PUMP_COUNT + 1):
        volume_ml = _number(inputs, f"pump_{index}_ml", 0.0)
        if volume_ml == 0:
            continue

        calibration = _calibration_for(context, index)
        try:
            steps = steps_for_volume(volume_ml, calibration)
        except PeristalticPumpError as exc:
            return {
                "ok": False,
                "status": "error",
                "error": f"Pump {index}: {exc}",
                "message": f"Pump {index} is not calibrated.",
            }

        speed = int(_number(inputs, f"pump_{index}_speed_rpm", DEFAULT_SPEED_RPM))
        commands.append(PumpCommand(index=index - 1, steps=steps, speed_rpm=speed))
        planned.append({
            "pump": index, "volume_ml": volume_ml, "steps": steps,
            "speed_rpm": speed, "ml_per_200_steps": calibration,
        })

    if not commands:
        return {
            "ok": True,
            "status": "completed",
            "message": "No pump had a volume set, so nothing ran.",
            "pumps": [],
        }

    dir_pins = [int(_number(inputs, f"pump_{i}_dir_pin", -1)) for i in range(1, PUMP_COUNT + 1)]
    step_pins = [int(_number(inputs, f"pump_{i}_step_pin", -1)) for i in range(1, PUMP_COUNT + 1)]
    enable_pin = int(_number(inputs, "motor_enable_pin", -1))

    try:
        result = peristaltic_pump_service.run(
            context,
            commands,
            dir_pins=dir_pins,
            step_pins=step_pins,
            enable_pin=enable_pin,
            tool_port=inputs.get("tool_port"),
        )
    except PeristalticPumpError as exc:
        return {"ok": False, "status": "error", "error": str(exc), "pumps": planned}

    result["pumps"] = planned
    result["tool_port"] = inputs.get("tool_port")
    if result.get("status") == "completed":
        described = ", ".join(f"pump {p['pump']} {p['volume_ml']:g} mL" for p in planned)
        result["message"] = f"Dispensed {described}."
    return result


def cancel(context: dict, inputs: dict) -> dict:
    """Stop mid-dispense. The firmware checks for STOP between steps."""
    from app.services.hybrid_z_axis import hybrid_z_axis_service

    hybrid_z_axis_service.emergency_stop()
    return {"ok": True, "message": "STOP sent to the pump controller."}
