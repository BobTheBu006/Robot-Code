from fastapi import APIRouter

from app.services.gantry_controller import gantry_controller_service
from app.services.syringe_controller import syringe_controller_service

router = APIRouter(prefix="/api/emergency-stop", tags=["emergency-stop"])


@router.post("")
def emergency_stop() -> dict[str, object]:
    results = [
        *gantry_controller_service.emergency_stop(),
        *syringe_controller_service.emergency_stop(),
    ]

    return {
        "ok": all(bool(result.get("ok")) for result in results),
        "message": "Emergency stop signal sent.",
        "results": results,
    }
