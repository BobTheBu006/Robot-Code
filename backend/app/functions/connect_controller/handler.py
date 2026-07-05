from app.services.hardware_map import hardware_map_service


def execute(context: dict, inputs: dict) -> dict:
    controller_id = str(inputs.get("controller_id") or "").strip()
    if not controller_id:
        raise ValueError("Select which controller to connect to.")

    status = hardware_map_service.verify_board_connection(controller_id)
    if not status.matched:
        raise RuntimeError(status.message)

    return {
        "status": "connected",
        "controller_id": status.board_id,
        "label": status.label,
        "usb_port": status.usb_port,
        "message": status.message,
        "mode": context.get("mode"),
    }
