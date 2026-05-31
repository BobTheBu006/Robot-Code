from fastapi import APIRouter, HTTPException

from app.models.hardware_map import HardwareMap, HardwareMapSaveResponse
from app.services.hardware_map import HardwareMapError, hardware_map_service

router = APIRouter(prefix="/api/hardware-map", tags=["hardware-map"])


@router.get("", response_model=HardwareMap)
def get_hardware_map() -> HardwareMap:
    try:
        return hardware_map_service.load_map()
    except HardwareMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("", response_model=HardwareMapSaveResponse)
def save_hardware_map(hardware_map: HardwareMap) -> HardwareMapSaveResponse:
    try:
        return hardware_map_service.save_map(hardware_map)
    except HardwareMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
