def execute(context: dict, inputs: dict) -> dict:
    """Placeholder execution contract for the future workflow runner."""

    return {
        "accepted": False,
        "message": "Gantry execution is intentionally deferred in this step.",
        "inputs": inputs,
    }
