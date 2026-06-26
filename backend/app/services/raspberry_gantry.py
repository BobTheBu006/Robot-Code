from app.models.gantry import GantryXYCalibrationRequest, GantryXYMoveRequest

RASPBERRY_BOARD_ID = "raspberry-pi"
XY_DEVICE_IDS = {
    "x-axis-motor",
    "y-axis-motor",
    "x-min-limit-switch",
    "x-max-limit-switch",
    "y-min-limit-switch",
    "y-max-limit-switch",
}


def _hardware_map_devices(context: dict) -> list[dict]:
    hardware_map = context.get("hardware_map")
    if not isinstance(hardware_map, dict):
        return []

    devices = hardware_map.get("devices")
    return devices if isinstance(devices, list) else []


def xy_hardware_is_on_raspberry_pi(context: dict) -> bool:
    devices_by_id = {
        device.get("id"): device
        for device in _hardware_map_devices(context)
        if isinstance(device, dict)
    }

    for device_id in XY_DEVICE_IDS:
        device = devices_by_id.get(device_id)
        if not device or device.get("board_id") != RASPBERRY_BOARD_ID or device.get("enabled") is False:
            return False

    return True


def planned_calibrate_xy_result(context: dict, request: GantryXYCalibrationRequest) -> dict:
    return {
        "calibrated": False,
        "status": "gpio_direct_execution_pending",
        "message": (
            "XY gantry hardware is mapped to Raspberry Pi GPIO, so ESP32 serial/flashing was skipped. "
            "Direct Raspberry Pi GPIO motion execution still needs a dedicated stepper driver before this block can move hardware."
        ),
        "tool_port": None,
        "workspace": {
            "x_track_length_cm": request.x_track_length_cm,
            "y_track_length_cm": request.y_track_length_cm,
        },
        "calibration_speed_profile": request.calibration_speed_profile,
        "speed_rpm": request.speed_rpm,
        "trapezoidal_speed": request.trapezoidal_speed,
        "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
        "pin_command_sent": None,
        "pin_reply": None,
        "pins_applied": True,
        "limit_command_sent": None,
        "limit_reply": None,
        "limits_applied": True,
        "calibration_command_sent": None,
        "calibration_reply": None,
        "configured_pins": {
            "x_step_pin": request.x_step_pin,
            "x_dir_pin": request.x_dir_pin,
            "y_step_pin": request.y_step_pin,
            "y_dir_pin": request.y_dir_pin,
        },
        "configured_limits": {
            "limit_switch_mode": request.limit_switch_mode,
            "x_min_limit_pin": request.x_min_limit_pin,
            "x_max_limit_pin": request.x_max_limit_pin,
            "y_min_limit_pin": request.y_min_limit_pin,
            "y_max_limit_pin": request.y_max_limit_pin,
            "speed_rpm": request.speed_rpm,
            "trapezoidal_speed": request.trapezoidal_speed,
            "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
        },
        "mode": context.get("mode"),
        "controller": RASPBERRY_BOARD_ID,
    }


def planned_move_xy_result(context: dict, request: GantryXYMoveRequest) -> dict:
    return {
        "accepted": False,
        "status": "gpio_direct_execution_pending",
        "message": (
            "XY gantry hardware is mapped to Raspberry Pi GPIO, so ESP32 serial/flashing was skipped. "
            "Direct Raspberry Pi GPIO motion execution still needs a dedicated stepper driver before this block can move hardware."
        ),
        "tool_port": None,
        "target": {"x_cm": request.x_cm, "y_cm": request.y_cm, "z_cm": request.z_cm},
        "speed_profile": request.speed_profile,
        "speed_rpm": request.speed_rpm,
        "trapezoidal_speed": request.trapezoidal_speed,
        "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
        "on_the_fly_calibration": request.on_the_fly_calibration,
        "calibration_max_diff_steps": request.calibration_max_diff_steps,
        "pin_command_sent": None,
        "pin_reply": None,
        "pins_applied": True,
        "limit_command_sent": None,
        "limit_reply": None,
        "limits_applied": True,
        "move_command_sent": None,
        "move_reply": None,
        "move_applied": False,
        "configured_pins": {
            "x_step_pin": request.x_step_pin,
            "x_dir_pin": request.x_dir_pin,
            "y_step_pin": request.y_step_pin,
            "y_dir_pin": request.y_dir_pin,
        },
        "configured_limits": {
            "limit_switch_mode": request.limit_switch_mode,
            "x_min_limit_pin": request.x_min_limit_pin,
            "x_max_limit_pin": request.x_max_limit_pin,
            "y_min_limit_pin": request.y_min_limit_pin,
            "y_max_limit_pin": request.y_max_limit_pin,
            "speed_rpm": request.speed_rpm,
            "trapezoidal_speed": request.trapezoidal_speed,
            "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
            "on_the_fly_calibration": request.on_the_fly_calibration,
            "calibration_max_diff_steps": request.calibration_max_diff_steps,
        },
        "mode": context.get("mode"),
        "controller": RASPBERRY_BOARD_ID,
    }
