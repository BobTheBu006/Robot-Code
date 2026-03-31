from pydantic import BaseModel


class CameraStatusResponse(BaseModel):
    available: bool
    configured_device: str
    active_device: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    error: str | None = None
    stream_url: str | None = None
