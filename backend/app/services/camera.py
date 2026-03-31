import os
import threading
import time
from typing import Iterator

from app.models.camera import CameraStatusResponse


class CameraUnavailableError(RuntimeError):
    pass


class CameraService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._capture = None
        self._cv2 = None
        self._active_device: str | None = None

    def _configured_device(self) -> str:
        return os.getenv("CAMERA_DEVICE", "0")

    def _configured_width(self) -> int:
        return int(os.getenv("CAMERA_FRAME_WIDTH", "1280"))

    def _configured_height(self) -> int:
        return int(os.getenv("CAMERA_FRAME_HEIGHT", "720"))

    def _configured_fps(self) -> int:
        return int(os.getenv("CAMERA_FPS", "15"))

    def _load_cv2(self):
        if self._cv2 is not None:
            return self._cv2

        try:
            import cv2  # type: ignore
        except ImportError as exc:
            raise CameraUnavailableError(
                "OpenCV is not installed. Install backend requirements again to enable the camera feed."
            ) from exc

        self._cv2 = cv2
        return cv2

    def _camera_source(self) -> int | str:
        configured_device = self._configured_device()
        return int(configured_device) if configured_device.isdigit() else configured_device

    def _ensure_capture(self):
        cv2 = self._load_cv2()

        if self._capture is not None and self._capture.isOpened():
            return self._capture

        source = self._camera_source()
        capture = cv2.VideoCapture(source)

        if not capture.isOpened():
            capture.release()
            raise CameraUnavailableError(
                f"Could not open camera device '{self._configured_device()}'. Check that the USB camera is attached and exposed as /dev/video*."
            )

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._configured_width())
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._configured_height())
        capture.set(cv2.CAP_PROP_FPS, self._configured_fps())

        self._capture = capture
        self._active_device = str(source)
        return capture

    def _read_frame_bytes(self) -> bytes:
        with self._lock:
            capture = self._ensure_capture()
            ok, frame = capture.read()

            if not ok:
                capture.release()
                self._capture = None
                self._active_device = None
                raise CameraUnavailableError("Camera opened, but no frames could be read from it.")

            cv2 = self._load_cv2()
            encoded_ok, encoded_frame = cv2.imencode(".jpg", frame)
            if not encoded_ok:
                raise CameraUnavailableError("Failed to encode a camera frame as JPEG.")

            return encoded_frame.tobytes()

    def get_status(self) -> CameraStatusResponse:
        try:
            self._read_frame_bytes()
        except CameraUnavailableError as exc:
            return CameraStatusResponse(
                available=False,
                configured_device=self._configured_device(),
                error=str(exc),
            )

        with self._lock:
            capture = self._capture
            cv2 = self._load_cv2()
            fps = float(capture.get(cv2.CAP_PROP_FPS)) if capture is not None else None
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)) if capture is not None else None
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)) if capture is not None else None

        return CameraStatusResponse(
            available=True,
            configured_device=self._configured_device(),
            active_device=self._active_device,
            width=width,
            height=height,
            fps=round(fps, 2) if fps and fps > 0 else None,
            stream_url="/api/camera/stream",
        )

    def get_frame(self) -> bytes:
        return self._read_frame_bytes()

    def stream(self) -> Iterator[bytes]:
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        frame_delay = 1 / max(self._configured_fps(), 1)

        while True:
            try:
                frame = self.get_frame()
            except CameraUnavailableError:
                break

            yield boundary + frame + b"\r\n"
            time.sleep(frame_delay)


camera_service = CameraService()
