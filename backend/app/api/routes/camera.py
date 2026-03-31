from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from app.models.camera import CameraStatusResponse
from app.services.camera import CameraUnavailableError, camera_service

router = APIRouter(prefix="/api/camera", tags=["camera"])


@router.get("/status", response_model=CameraStatusResponse)
def get_camera_status() -> CameraStatusResponse:
    return camera_service.get_status()


@router.get("/frame")
def get_camera_frame() -> Response:
    try:
        frame = camera_service.get_frame()
    except CameraUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return Response(content=frame, media_type="image/jpeg")


@router.get("/stream")
def get_camera_stream() -> StreamingResponse:
    status = camera_service.get_status()
    if not status.available:
        raise HTTPException(status_code=503, detail=status.error or "Camera feed is unavailable.")

    return StreamingResponse(
        camera_service.stream(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
