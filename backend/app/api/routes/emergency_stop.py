from fastapi import APIRouter

from app.services.esp32_builder import esp32_builder_service
from app.services.gantry_controller import gantry_controller_service
from app.services.hybrid_z_axis import hybrid_z_axis_service
from app.services.raspberry_gantry import emergency_stop_raspberry_gantry, rearm_raspberry_gantry
from app.services.syringe_controller import syringe_controller_service
from app.services.toolhead import toolhead_state_store

router = APIRouter(prefix="/api/emergency-stop", tags=["emergency-stop"])


@router.post("")
def emergency_stop() -> dict[str, object]:
    results = [
        # Stop Raspberry Pi GPIO motion first: it is driven in-process, so this
        # only sets a flag and returns immediately, whereas the serial stops
        # below can block on a busy port.
        emergency_stop_raspberry_gantry(),
        hybrid_z_axis_service.emergency_stop(),
        # Abort an in-progress board flash so the controller stops getting
        # reprogrammed, then stop any active motion.
        esp32_builder_service.emergency_stop(),
        *gantry_controller_service.emergency_stop(),
        *syringe_controller_service.emergency_stop(),
    ]

    # An E-Stop can land mid tool-change, so the recorded held tool is no
    # longer trustworthy - the tool may be seated, half-engaged, or dropped.
    # Forget it rather than let the next pickup route through a wrong slot;
    # the operator confirms the physical state when work resumes.
    toolhead_state_store.set_held_index(None)

    return {
        "ok": all(bool(result.get("ok")) for result in results),
        "message": "Emergency stop signal sent.",
        "results": results,
    }


@router.post("/rearm")
def rearm() -> dict[str, object]:
    """Clear a latched emergency stop so new work can move again.

    An E-Stop latches: it keeps blocking Raspberry Pi GPIO motion until the user
    explicitly starts new work (Run all, running a block, or Resume).
    """
    rearm_raspberry_gantry()
    hybrid_z_axis_service.rearm()
    return {"ok": True, "message": "Emergency stop cleared."}
