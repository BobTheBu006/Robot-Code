"""Dispense a volume from each syringe head.

The generated stub this replaces reported "not implemented yet", so the block
looked broken in the UI while the identical preset block worked. Both now share
one input mapping and one result shape.
"""

from app.models.syringe import SyringeDispenseRequest
from app.services.syringe_controller import syringe_controller_service, dispense_result_payload


def execute(context: dict, inputs: dict) -> dict:
    request = SyringeDispenseRequest.from_block_inputs(inputs)
    response = syringe_controller_service.dispense(request)
    return dispense_result_payload(response, context)
