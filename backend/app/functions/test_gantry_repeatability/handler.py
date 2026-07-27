from app.models.gantry import GantryRepeatabilityTestRequest
from app.services.raspberry_gantry import planned_test_repeatability_result, xy_hardware_is_on_raspberry_pi


def execute(context: dict, inputs: dict) -> dict:
    request = GantryRepeatabilityTestRequest.model_validate(inputs)
    if not xy_hardware_is_on_raspberry_pi(context):
        raise RuntimeError(
            "Test Gantry Repeatability only supports the Raspberry Pi GPIO gantry. "
            "Map the XY motors and limit switches to the Raspberry Pi in the Hardware Map first."
        )

    result = planned_test_repeatability_result(context, request)

    overall_max = result.get("max_abs_deviation_steps", 0)
    result["message"] = (
        f"Repeatability test completed: worst deviation across all limits and speeds was "
        f"{overall_max} steps ({overall_max / result['steps_per_cm']:.3f} cm)."
    )
    return result


def cancel(context: dict, inputs: dict) -> dict:
    from app.services.raspberry_gantry import emergency_stop_raspberry_gantry

    response = emergency_stop_raspberry_gantry()
    return {
        "ok": response["ok"],
        "message": response["message"],
        "tool_port": inputs.get("tool_port"),
        "mode": context.get("mode"),
    }
