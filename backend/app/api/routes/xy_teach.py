"""Hand-teach endpoints for the Teach Tool Positions dialog.

The dialog posts the block's own inputs; they are resolved against the
Hardware Map exactly like a block run, so the pins and the XY board's port
(found by USB serial) are the real ones, not the browser's copy.
"""

from fastapi import APIRouter, HTTPException

from app.models.gantry import GantryGotoXYRequest
from app.services.function_discovery import function_discovery_service
from app.services.gantry_controller import GantryControllerError, gantry_controller_service
from app.services.hardware_map import HardwareMapError, hardware_map_service

router = APIRouter(prefix="/api/robot/xy-teach", tags=["xy-teach"])


@router.post("/{action}")
def xy_teach(action: str, inputs: dict) -> dict:
    if action not in {"start", "position", "end"}:
        raise HTTPException(status_code=404, detail=f"Unknown teach action '{action}'.")
    try:
        manifest = function_discovery_service.get_function("teach_tool_positions").manifest
        resolved = hardware_map_service.apply_function_defaults(manifest, inputs)
        request = GantryGotoXYRequest.model_validate(resolved)
        return gantry_controller_service.teach(request, action)
    except (HardwareMapError, GantryControllerError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
