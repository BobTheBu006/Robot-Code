from fastapi import APIRouter, HTTPException

from app.models.esp32_builder import (
    Esp32BoardDetail,
    Esp32BoardListResponse,
    Esp32CustomBlockDeleteResponse,
    Esp32CustomBlockSaveRequest,
    Esp32CustomBlockSaveResponse,
    Esp32FirmwareActionResponse,
    Esp32FileSaveRequest,
    Esp32FileSaveResponse,
    Esp32WorkflowFirmwarePlanRequest,
    Esp32WorkflowFirmwarePlanResponse,
)
from app.services.esp32_builder import Esp32BuilderError, esp32_builder_service

router = APIRouter(prefix="/api/esp32-builder", tags=["esp32-builder"])


@router.get("/boards", response_model=Esp32BoardListResponse)
def list_esp32_boards() -> Esp32BoardListResponse:
    return esp32_builder_service.list_boards()


@router.get("/boards/{board_id}", response_model=Esp32BoardDetail)
def get_esp32_board(board_id: str) -> Esp32BoardDetail:
    try:
        return esp32_builder_service.get_board(board_id)
    except Esp32BuilderError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/boards/{board_id}/files", response_model=Esp32FileSaveResponse)
def save_esp32_board_file(board_id: str, request: Esp32FileSaveRequest) -> Esp32FileSaveResponse:
    try:
        return esp32_builder_service.save_board_file(
            board_id=board_id,
            relative_path=request.relative_path,
            content=request.content,
        )
    except Esp32BuilderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/boards/{board_id}/build", response_model=Esp32FirmwareActionResponse)
def build_esp32_board_firmware(board_id: str) -> Esp32FirmwareActionResponse:
    try:
        return esp32_builder_service.build_firmware(board_id)
    except Esp32BuilderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/boards/{board_id}/flash", response_model=Esp32FirmwareActionResponse)
def flash_esp32_board_firmware(
    board_id: str,
    skip_if_current: bool = False,
) -> Esp32FirmwareActionResponse:
    """Flash a controller.

    `skip_if_current` asks the board who it is first and leaves it alone when
    it already runs the expected firmware - what a workflow run wants, so it
    stops reflashing every controller before every run. It defaults to false so
    that pressing Flash in the builder UI always flashes, which is what someone
    who clicked the button meant.
    """
    try:
        return esp32_builder_service.flash_firmware(board_id, skip_if_current=skip_if_current)
    except Esp32BuilderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/boards/{board_id}/preflight")
def preflight_esp32_board(board_id: str) -> dict:
    """Ask the board who it is and whether its firmware is already correct."""
    try:
        result = esp32_builder_service.preflight_board(board_id)
    except Esp32BuilderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "controller_id": result.controller_id,
        "verdict": result.verdict.value,
        "message": result.message,
        "port": result.port,
        "expected_fingerprint": result.expected_fingerprint,
        "reported_fingerprint": result.reported_fingerprint,
        "reported_controller_id": result.reported_controller_id,
        "missing_routines": result.missing_routines,
        "needs_flash": result.needs_flash,
        "blocks_run": result.verdict.blocks_run,
    }


@router.post("/workflow-firmware/plan", response_model=Esp32WorkflowFirmwarePlanResponse)
def plan_workflow_firmware(
    request: Esp32WorkflowFirmwarePlanRequest,
) -> Esp32WorkflowFirmwarePlanResponse:
    try:
        return esp32_builder_service.plan_workflow_firmware(request)
    except Esp32BuilderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/boards/{board_id}/blocks", response_model=Esp32CustomBlockSaveResponse)
def save_esp32_custom_block(
    board_id: str,
    request: Esp32CustomBlockSaveRequest,
) -> Esp32CustomBlockSaveResponse:
    try:
        return esp32_builder_service.save_custom_block(
            board_id=board_id,
            source_function_id=request.source_function_id,
            display_name=request.display_name,
            description=request.description,
            defaults=request.defaults,
        )
    except Esp32BuilderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/boards/{board_id}/blocks/{function_id}", response_model=Esp32CustomBlockDeleteResponse)
def delete_esp32_custom_block(
    board_id: str,
    function_id: str,
) -> Esp32CustomBlockDeleteResponse:
    try:
        return esp32_builder_service.delete_custom_block(
            board_id=board_id,
            function_id=function_id,
        )
    except Esp32BuilderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
