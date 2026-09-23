from fastapi import APIRouter, HTTPException

from app.models.hardware_map import HardwareBoardConnectionStatus, HardwareMap, HardwareMapSaveResponse
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


@router.get("/boards/{board_id}/connection", response_model=HardwareBoardConnectionStatus)
def get_board_connection_status(board_id: str) -> HardwareBoardConnectionStatus:
    try:
        return hardware_map_service.verify_board_connection(board_id)
    except HardwareMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/connectors/status")
def get_connector_status() -> list[dict]:
    """Which tool is recorded as docked on each dynamic connector."""
    from app.services.pogo_connector import pogo_connector_service

    try:
        return pogo_connector_service.status()
    except HardwareMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/connectors/check-contact")
def check_connector_contact() -> dict:
    """Is TXD shorted to RXD on the pogo connector right now? Drives only the
    connector's TXD pin; moves nothing and changes no recorded state."""
    from app.services.pogo_connector import pogo_connector_service

    try:
        ok, message = pogo_connector_service.check_contact()
    except HardwareMapError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": ok, "message": message}
