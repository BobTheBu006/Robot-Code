import glob
import json
import os
from pathlib import Path

from app.models.syringe import (
    SyringeCalibrationEntry,
    SyringeDispenseRequest,
    SyringeDispenseResponse,
    SyringeHead,
    SyringeStatusResponse,
)

HEADS: tuple[SyringeHead, ...] = ("A", "B", "C", "D", "E", "F", "G")
DEFAULT_CALIBRATION_PATH = "/home/robot/robot control/syringe control code/calibration.json"


class SyringeControllerError(RuntimeError):
    pass


class SyringeControllerService:
    def _calibration_path(self) -> Path:
        return Path(os.getenv("SYRINGE_CALIBRATION_FILE", DEFAULT_CALIBRATION_PATH))

    def _baud_rate(self) -> int:
        return int(os.getenv("SYRINGE_BAUD_RATE", "115200"))

    def _serial_timeout(self) -> float:
        return float(os.getenv("SYRINGE_SERIAL_TIMEOUT_SECONDS", "2.0"))

    def _command_format(self) -> str:
        return os.getenv("SYRINGE_COMMAND_FORMAT", "json")

    def _port_candidates(self) -> list[str]:
        configured_port = os.getenv("SYRINGE_SERIAL_PORT")
        if configured_port:
            return [configured_port]

        ports = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
        return ports

    def _selected_port(self, requested_port: str | None = None) -> str:
        if requested_port:
            return requested_port

        candidates = self._port_candidates()
        if not candidates:
            raise SyringeControllerError(
                "No ESP32 serial port found. Connect the board or set SYRINGE_SERIAL_PORT."
            )

        return candidates[0]

    def _load_serial_module(self):
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise SyringeControllerError(
                "pyserial is not installed. Install backend requirements again to enable ESP32 communication."
            ) from exc

        return serial

    def _load_calibration(self) -> dict[SyringeHead, SyringeCalibrationEntry]:
        calibration_path = self._calibration_path()
        if not calibration_path.exists():
            raise SyringeControllerError(
                f"Calibration file not found: {calibration_path}"
            )

        with calibration_path.open("r", encoding="utf-8") as calibration_file:
            raw_calibration = json.load(calibration_file)

        calibration: dict[SyringeHead, SyringeCalibrationEntry] = {}
        for head in HEADS:
            if head not in raw_calibration:
                raise SyringeControllerError(f"Calibration is missing head '{head}'.")
            calibration[head] = SyringeCalibrationEntry.model_validate(raw_calibration[head])

        return calibration

    def _calculate_steps(
        self,
        request: SyringeDispenseRequest,
        calibration: dict[SyringeHead, SyringeCalibrationEntry],
    ) -> dict[SyringeHead, int]:
        steps: dict[SyringeHead, int] = {}

        for head in HEADS:
            requested_amount = getattr(request, head)
            coefficients = calibration[head]
            calculated_steps = (coefficients.a * requested_amount) + coefficients.b
            steps[head] = max(0, round(calculated_steps))

        return steps

    def _build_command(self, steps: dict[SyringeHead, int]) -> str:
        command_format = self._command_format().lower()
        if command_format == "json":
            return json.dumps({"command": "dispense", "steps": steps}, separators=(",", ":"))

        if command_format == "csv":
            return ",".join(f"{head}:{steps[head]}" for head in HEADS)

        if command_format == "plain":
            return " ".join(f"{head}{steps[head]}" for head in HEADS)

        raise SyringeControllerError(
            f"Unsupported SYRINGE_COMMAND_FORMAT '{self._command_format()}'. Use json, csv, or plain."
        )

    def get_status(self) -> SyringeStatusResponse:
        available_ports = self._port_candidates()
        calibration_path = str(self._calibration_path())

        try:
            self._load_calibration()
            calibration_loaded = True
            calibration_error = None
        except SyringeControllerError as exc:
            calibration_loaded = False
            calibration_error = str(exc)

        selected_port = available_ports[0] if available_ports else os.getenv("SYRINGE_SERIAL_PORT")

        return SyringeStatusResponse(
            connected=bool(available_ports),
            selected_port=selected_port,
            available_ports=available_ports,
            calibration_file=calibration_path,
            calibration_loaded=calibration_loaded,
            command_format=self._command_format(),
            error=calibration_error if not calibration_loaded else None,
        )

    def dispense(self, request: SyringeDispenseRequest) -> SyringeDispenseResponse:
        calibration = self._load_calibration()
        steps = self._calculate_steps(request, calibration)
        port = self._selected_port(request.port)
        baud_rate = request.baud_rate or self._baud_rate()
        command = self._build_command(steps)

        serial = self._load_serial_module()
        try:
            with serial.Serial(port, baud_rate, timeout=self._serial_timeout()) as serial_port:
                serial_port.reset_input_buffer()
                serial_port.reset_output_buffer()
                serial_port.write((command + "\n").encode("utf-8"))
                serial_port.flush()
                reply_bytes = serial_port.readline()
        except Exception as exc:
            raise SyringeControllerError(
                f"Failed to communicate with ESP32 on {port}: {exc}"
            ) from exc

        reply = reply_bytes.decode("utf-8", errors="replace").strip() or None
        requested_amounts = {head: float(getattr(request, head)) for head in HEADS}

        return SyringeDispenseResponse(
            port=port,
            baud_rate=baud_rate,
            command_format=self._command_format(),
            requested_amounts=requested_amounts,
            calculated_steps=steps,
            command_sent=command,
            reply=reply,
        )


syringe_controller_service = SyringeControllerService()
