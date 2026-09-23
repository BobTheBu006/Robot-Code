from app.services.pogo_connector import pogo_connector_service


def execute(context: dict, inputs: dict) -> dict:
    group_id = str(inputs.get("connector_group_id") or "").strip()
    if not group_id:
        raise ValueError("Select which tool to connect.")

    # Raises when verification fails; the connector is then left empty.
    result = pogo_connector_service.activate(group_id)
    return {
        "status": "connected",
        **result.as_dict(),
        "mode": context.get("mode"),
    }
