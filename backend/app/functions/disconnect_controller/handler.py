from app.services.hardware_map import hardware_map_service


def execute(context: dict, inputs: dict) -> dict:
    controller_id = str(inputs.get("controller_id") or "").strip()
    if not controller_id:
        raise ValueError("Select which controller to disconnect.")

    status = hardware_map_service.verify_board_connection(controller_id)
    if status.matched:
        raise RuntimeError(
            f"{status.label} is still detected on {status.usb_port}. "
            "Physically disconnect it before continuing."
        )

    return {
        "status": "disconnected",
        "controller_id": status.board_id,
        "label": status.label,
        "usb_port": status.usb_port,
        "message": f"{status.label} is no longer detected on {status.usb_port}.",
        "mode": context.get("mode"),
    }
