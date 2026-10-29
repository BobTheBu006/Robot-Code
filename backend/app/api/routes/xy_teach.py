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


# Typing a position into the dialog drives there gently: this is positioning
# by eye next to a person, not a production move.
TEACH_GOTO_RPM = 200


@router.post("/{action}")
def xy_teach(action: str, inputs: dict) -> dict:
    if action not in {"start", "position", "end", "goto"}:
        raise HTTPException(status_code=404, detail=f"Unknown teach action '{action}'.")
    try:
        manifest = function_discovery_service.get_function("teach_tool_positions").manifest
        resolved = hardware_map_service.apply_function_defaults(manifest, inputs)
        request = GantryGotoXYRequest.model_validate(resolved)
        if action == "goto":
            return _goto_while_teaching(request, inputs)
        return gantry_controller_service.teach(request, action)
    except (HardwareMapError, GantryControllerError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _goto_while_teaching(request: GantryGotoXYRequest, inputs: dict) -> dict:
    """Drive to a typed position in the middle of a hand teach.

    Teach mode keeps the XY motors off and the board refuses to move, so:
    leave it (the pushed-to position is adopted, as on Finish), move, and
    enter it again so the operator can fine-tune by hand. Teach mode is
    re-entered even when the move fails, so the dialog stays usable."""
    try:
        target = request.model_copy(update={
            "x_cm": float(inputs["goto_x_cm"]),
            "y_cm": float(inputs["goto_y_cm"]),
            "speed_rpm": TEACH_GOTO_RPM,
        })
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Give goto_x_cm and goto_y_cm as numbers.") from exc
    target = GantryGotoXYRequest.model_validate(target.model_dump())

    gantry_controller_service.teach(request, "end")
    try:
        gantry_controller_service.goto_xy(target)
    finally:
        position = gantry_controller_service.teach(request, "start")
    return position
