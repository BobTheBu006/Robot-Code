import glob
import json
import os
import time
from pathlib import Path

from app.models.syringe import (
    SyringeCalibrationEntry,
    SyringeDispenseRequest,
    SyringeDispenseResponse,
    SyringeHead,
    SyringeStatusResponse,
)

HEADS: tuple[SyringeHead, ...] = ("A", "B", "C", "D", "E", "F", "G")
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CALIBRATION_PATH = str(REPO_ROOT / "functions" / "syringe control code" / "calibration.json")
LEGACY_CALIBRATION_PATH = "/home/robot/robot control/syringe control code/calibration.json"
AUTO_COMMAND_FORMATS: tuple[str, ...] = (
    "json",
    "dispense_csv",
    "dispense_space",
    "raw_csv",
    "csv",
    "plain",
)
AUTO_SPEED_COMMAND_FORMATS: tuple[str, ...] = (
    "speed_csv",
    "speed_space",
    "set_speed_csv",
    "set_speed_space",
)


class SyringeControllerError(RuntimeError):
    pass


class SyringeControllerService:
    def _calibration_path(self, requested_path: str | None = None) -> Path:
        if requested_path:
            requested = Path(requested_path)
            if requested.exists():
                return requested

            if str(requested) == LEGACY_CALIBRATION_PATH and Path(DEFAULT_CALIBRATION_PATH).exists():
                return Path(DEFAULT_CALIBRATION_PATH)

            if requested.name == "calibration.json" and Path(DEFAULT_CALIBRATION_PATH).exists():
                return Path(DEFAULT_CALIBRATION_PATH)

            return requested

        return Path(os.getenv("SYRINGE_CALIBRATION_FILE", DEFAULT_CALIBRATION_PATH))

    def _baud_rate(self) -> int:
        return int(os.getenv("SYRINGE_BAUD_RATE", "115200"))

    def _serial_timeout(self) -> float:
        return float(os.getenv("SYRINGE_SERIAL_TIMEOUT_SECONDS", "2.0"))

    def _boot_delay(self) -> float:
        return float(os.getenv("SYRINGE_SERIAL_BOOT_DELAY_SECONDS", "2.0"))

    def _command_format(self) -> str:
        return os.getenv("SYRINGE_COMMAND_FORMAT", "auto")

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

    def _load_calibration(
        self,
        requested_path: str | None = None,
    ) -> dict[SyringeHead, SyringeCalibrationEntry]:
        calibration_path = self._calibration_path(requested_path)
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

    def _build_command(self, steps: dict[SyringeHead, int], command_format: str) -> str:
        command_format = command_format.lower()
        if command_format == "json":
            return json.dumps({"command": "dispense", "steps": steps}, separators=(",", ":"))

        if command_format == "csv":
            return ",".join(f"{head}:{steps[head]}" for head in HEADS)

        if command_format == "plain":
            return " ".join(f"{head}{steps[head]}" for head in HEADS)

        if command_format == "raw_csv":
            return ",".join(str(steps[head]) for head in HEADS)

        if command_format == "dispense_csv":
            return "DISPENSE," + ",".join(str(steps[head]) for head in HEADS)

        if command_format == "dispense_space":
            return "DISPENSE " + " ".join(str(steps[head]) for head in HEADS)

        raise SyringeControllerError(
            f"Unsupported SYRINGE_COMMAND_FORMAT '{command_format}'. Use auto, json, csv, plain, raw_csv, dispense_csv, or dispense_space."
        )

    def _command_formats_to_try(self) -> list[str]:
        configured_format = self._command_format().lower()
        if configured_format == "auto":
            return list(AUTO_COMMAND_FORMATS)

        return [configured_format]

    def _build_speed_command(self, speed: int, command_format: str) -> str:
        command_format = command_format.lower()

        if command_format == "speed_csv":
            return f"SPEED,{speed}"

        if command_format == "speed_space":
            return f"SPEED {speed}"

        if command_format == "set_speed_csv":
            return f"SET_SPEED,{speed}"

        if command_format == "set_speed_space":
            return f"SET SPEED {speed}"

        raise SyringeControllerError(
            f"Unsupported syringe speed command format '{command_format}'."
        )

    def _send_command(self, serial_port, command: str) -> str | None:
        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
        serial_port.write((command + "\n").encode("utf-8"))
        serial_port.flush()
        reply_bytes = serial_port.readline()
        return reply_bytes.decode("utf-8", errors="replace").strip() or None

    def _try_apply_speed(self, serial_port, speed: int) -> tuple[str | None, str | None, bool]:
        for command_format in AUTO_SPEED_COMMAND_FORMATS:
            command = self._build_speed_command(speed, command_format)
            reply = self._send_command(serial_port, command)
            if not self._is_unknown_command_reply(reply):
                return command, reply, True

        return None, None, False

    def _is_unknown_command_reply(self, reply: str | None) -> bool:
        if not reply:
            return False

        normalized_reply = reply.upper()
        return "UNKNOWN CMD" in normalized_reply or "INVALID CMD" in normalized_reply

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
        calibration_path = self._calibration_path(request.calibration_file)
        calibration = self._load_calibration(request.calibration_file)
        steps = self._calculate_steps(request, calibration)
        port = self._selected_port(request.port)
        baud_rate = request.baud_rate or self._baud_rate()
        serial = self._load_serial_module()
        try:
            with serial.Serial(port, baud_rate, timeout=self._serial_timeout()) as serial_port:
                boot_delay = self._boot_delay()
                if boot_delay > 0:
                    time.sleep(boot_delay)

                selected_format = None
                command = None
                reply = None
                speed_command = None
                speed_reply = None
                speed_applied = False

                if request.speed:
                    speed_command, speed_reply, speed_applied = self._try_apply_speed(
                        serial_port,
                        request.speed,
                    )

                for command_format in self._command_formats_to_try():
                    command = self._build_command(steps, command_format)
                    reply = self._send_command(serial_port, command)
                    selected_format = command_format

                    if not self._is_unknown_command_reply(reply):
                        break
        except Exception as exc:
            raise SyringeControllerError(
                f"Failed to communicate with ESP32 on {port}: {exc}"
            ) from exc

        if command is None or selected_format is None:
            raise SyringeControllerError("No syringe command format was available to try.")

        requested_amounts = {head: float(getattr(request, head)) for head in HEADS}

        return SyringeDispenseResponse(
            port=port,
            baud_rate=baud_rate,
            calibration_file=str(calibration_path),
            command_format=selected_format,
            speed=request.speed,
            speed_command_sent=speed_command,
            speed_reply=speed_reply,
            speed_applied=speed_applied,
            requested_amounts=requested_amounts,
            calculated_steps=steps,
            command_sent=command,
            reply=reply,
        )


syringe_controller_service = SyringeControllerService()
