"""7-syringe dispense preset.

Thin wrapper over the same service the plain `dispense` block uses; the input
mapping and result shape are shared so the two cannot drift apart.
"""

from app.models.syringe import SyringeDispenseRequest
from app.services.syringe_controller import syringe_controller_service, dispense_result_payload


def execute(context: dict, inputs: dict) -> dict:
    request = SyringeDispenseRequest.from_block_inputs(inputs)
    response = syringe_controller_service.dispense(request)
    return dispense_result_payload(response, context)
