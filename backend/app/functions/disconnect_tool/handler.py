from app.services.pogo_connector import pogo_connector_service


def execute(context: dict, inputs: dict) -> dict:
    results = pogo_connector_service.deactivate()
    return {
        "status": "disconnected",
        "connectors": [result.as_dict() for result in results],
        "message": " ".join(result.message for result in results) or "No connectors are defined.",
        "mode": context.get("mode"),
    }
