from fastapi import APIRouter, HTTPException

from app.models.syringe import (
    SyringeDispenseRequest,
    SyringeDispenseResponse,
    SyringeStatusResponse,
)
from app.services.syringe_controller import (
    SyringeControllerError,
    syringe_controller_service,
)

router = APIRouter(prefix="/api/tools/syringe", tags=["syringe"])


@router.get("/status", response_model=SyringeStatusResponse)
def get_syringe_status() -> SyringeStatusResponse:
    return syringe_controller_service.get_status()


@router.post("/dispense", response_model=SyringeDispenseResponse)
def dispense_syringes(request: SyringeDispenseRequest) -> SyringeDispenseResponse:
    try:
        return syringe_controller_service.dispense(request)
    except SyringeControllerError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
