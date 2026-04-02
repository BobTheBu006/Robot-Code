def execute(context: dict, inputs: dict) -> dict:
    return {
        "calibrated": False,
        "status": "not_implemented",
        "message": "XY calibration is not implemented yet. This block currently defines the calibration contract.",
        "tool_port": inputs.get("tool_port"),
        "workspace": {
            "x_track_length_cm": inputs.get("x_track_length_cm"),
            "y_track_length_cm": inputs.get("y_track_length_cm"),
        },
        "advanced": {
            "x_step_pin": inputs.get("x_step_pin"),
            "x_dir_pin": inputs.get("x_dir_pin"),
            "y_step_pin": inputs.get("y_step_pin"),
            "y_dir_pin": inputs.get("y_dir_pin"),
            "limit_switch_mode": inputs.get("limit_switch_mode"),
            "x_min_limit_pin": inputs.get("x_min_limit_pin"),
            "x_max_limit_pin": inputs.get("x_max_limit_pin"),
            "y_min_limit_pin": inputs.get("y_min_limit_pin"),
            "y_max_limit_pin": inputs.get("y_max_limit_pin"),
        },
        "mode": context.get("mode"),
    }
