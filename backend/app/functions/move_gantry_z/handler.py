def execute(context: dict, inputs: dict) -> dict:
    return {
        "accepted": False,
        "status": "not_implemented",
        "message": "Dual-Z execution is not implemented yet. This block currently defines the contract and configuration shape.",
        "tool_port": inputs.get("tool_port"),
        "target": {
            "z_left_cm": inputs.get("z_left_cm"),
            "z_right_cm": inputs.get("z_right_cm"),
        },
        "speed_profile": inputs.get("speed_profile"),
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
