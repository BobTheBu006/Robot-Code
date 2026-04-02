def execute(context: dict, inputs: dict) -> dict:
    return {
        "calibrated": False,
        "status": "not_implemented",
        "message": "Z calibration is not implemented yet. This block currently defines the calibration contract.",
        "tool_port": inputs.get("tool_port"),
        "workspace": {
            "z_left_track_length_cm": inputs.get("z_left_track_length_cm"),
            "z_right_track_length_cm": inputs.get("z_right_track_length_cm"),
        },
        "advanced": {
            "z_left_step_pin": inputs.get("z_left_step_pin"),
            "z_left_dir_pin": inputs.get("z_left_dir_pin"),
            "z_right_step_pin": inputs.get("z_right_step_pin"),
            "z_right_dir_pin": inputs.get("z_right_dir_pin"),
            "limit_switch_mode": inputs.get("limit_switch_mode"),
            "z_left_min_limit_pin": inputs.get("z_left_min_limit_pin"),
            "z_left_max_limit_pin": inputs.get("z_left_max_limit_pin"),
            "z_right_min_limit_pin": inputs.get("z_right_min_limit_pin"),
            "z_right_max_limit_pin": inputs.get("z_right_max_limit_pin"),
        },
        "mode": context.get("mode"),
    }
