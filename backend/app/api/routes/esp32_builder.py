from fastapi import APIRouter, HTTPException

from app.models.esp32_builder import (
    Esp32BoardDetail,
    Esp32BoardListResponse,
    Esp32FileSaveRequest,
    Esp32FileSaveResponse,
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

