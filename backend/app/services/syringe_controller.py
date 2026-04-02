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
AUTO_INTAKE_SPEED_COMMAND_FORMATS: tuple[str, ...] = (
    "intake_speed_csv",
    "intake_speed_space",
    "set_intake_speed_csv",
    "set_intake_speed_space",
)
AUTO_OUTTAKE_SPEED_COMMAND_FORMATS: tuple[str, ...] = (
    "outtake_speed_csv",
    "outtake_speed_space",
    "set_outtake_speed_csv",
    "set_outtake_speed_space",
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

        if command_format == "intake_speed_csv":
            return f"INTAKE_SPEED,{speed}"

        if command_format == "intake_speed_space":
            return f"INTAKE_SPEED {speed}"

        if command_format == "set_intake_speed_csv":
            return f"SET_INTAKE_SPEED,{speed}"

        if command_format == "set_intake_speed_space":
            return f"SET INTAKE SPEED {speed}"

        if command_format == "outtake_speed_csv":
            return f"OUTTAKE_SPEED,{speed}"

        if command_format == "outtake_speed_space":
            return f"OUTTAKE_SPEED {speed}"

        if command_format == "set_outtake_speed_csv":
            return f"SET_OUTTAKE_SPEED,{speed}"

        if command_format == "set_outtake_speed_space":
            return f"SET OUTTAKE SPEED {speed}"

        raise SyringeControllerError(
            f"Unsupported syringe speed command format '{command_format}'."
        )

    def _send_command(self, serial_port, command: str) -> str | None:
        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
        serial_port.write((command + "\n").encode("utf-8"))
        serial_port.flush()
        replies: list[str] = []

        while True:
            reply_bytes = serial_port.readline()
            reply_line = reply_bytes.decode("utf-8", errors="replace").strip()
            if not reply_line:
                break

            replies.append(reply_line)

            normalized = reply_line.upper()
            if normalized.startswith("OK ") or normalized.startswith("ERR "):
                break

            if normalized in {"PONG", "READY"}:
                break

        if not replies:
            return None

        return "\n".join(replies)

    def _try_apply_speed(self, serial_port, speed: int) -> tuple[str | None, str | None, bool]:
        for command_format in AUTO_SPEED_COMMAND_FORMATS:
            command = self._build_speed_command(speed, command_format)
            reply = self._send_command(serial_port, command)
            if not self._is_unknown_command_reply(reply):
                return command, reply, True

        return None, None, False

    def _try_apply_speed_with_formats(
        self,
        serial_port,
        speed: int,
        command_formats: tuple[str, ...],
    ) -> tuple[str | None, str | None, bool]:
        for command_format in command_formats:
            command = self._build_speed_command(speed, command_format)
            reply = self._send_command(serial_port, command)
            if not self._is_unknown_command_reply(reply):
                return command, reply, True

        return None, None, False

    def _apply_speed_profile(
        self,
        serial_port,
        speed: int | None,
        intake_speed: int | None,
        outtake_speed: int | None,
    ) -> dict[str, str | bool | None | int]:
        effective_intake_speed = intake_speed or speed
        effective_outtake_speed = outtake_speed or speed

        speed_command = None
        speed_reply = None
        speed_applied = False
        intake_speed_command = None
        intake_speed_reply = None
        intake_speed_applied = False
        outtake_speed_command = None
        outtake_speed_reply = None
        outtake_speed_applied = False

        if effective_intake_speed and effective_outtake_speed and effective_intake_speed == effective_outtake_speed:
            speed_command, speed_reply, speed_applied = self._try_apply_speed(
                serial_port,
                effective_intake_speed,
            )
        else:
            if effective_intake_speed:
                intake_speed_command, intake_speed_reply, intake_speed_applied = self._try_apply_speed_with_formats(
                    serial_port,
                    effective_intake_speed,
                    AUTO_INTAKE_SPEED_COMMAND_FORMATS,
                )

            if effective_outtake_speed:
                outtake_speed_command, outtake_speed_reply, outtake_speed_applied = self._try_apply_speed_with_formats(
                    serial_port,
                    effective_outtake_speed,
                    AUTO_OUTTAKE_SPEED_COMMAND_FORMATS,
                )

        return {
            "speed": speed,
            "intake_speed": effective_intake_speed,
            "outtake_speed": effective_outtake_speed,
            "speed_command_sent": speed_command,
            "speed_reply": speed_reply,
            "speed_applied": speed_applied,
            "intake_speed_command_sent": intake_speed_command,
            "intake_speed_reply": intake_speed_reply,
            "intake_speed_applied": intake_speed_applied,
            "outtake_speed_command_sent": outtake_speed_command,
            "outtake_speed_reply": outtake_speed_reply,
            "outtake_speed_applied": outtake_speed_applied,
        }

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
                speed_result: dict[str, str | bool | None | int] = {
                    "speed": request.speed,
                    "intake_speed": request.intake_speed,
                    "outtake_speed": request.outtake_speed,
                    "speed_command_sent": None,
                    "speed_reply": None,
                    "speed_applied": False,
                    "intake_speed_command_sent": None,
                    "intake_speed_reply": None,
                    "intake_speed_applied": False,
                    "outtake_speed_command_sent": None,
                    "outtake_speed_reply": None,
                    "outtake_speed_applied": False,
                }

                if request.speed or request.intake_speed or request.outtake_speed:
                    speed_result = self._apply_speed_profile(
                        serial_port,
                        request.speed,
                        request.intake_speed,
                        request.outtake_speed,
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
            speed=speed_result["speed"],
            intake_speed=speed_result["intake_speed"],
            outtake_speed=speed_result["outtake_speed"],
            speed_command_sent=speed_result["speed_command_sent"],
            speed_reply=speed_result["speed_reply"],
            speed_applied=bool(speed_result["speed_applied"]),
            intake_speed_command_sent=speed_result["intake_speed_command_sent"],
            intake_speed_reply=speed_result["intake_speed_reply"],
            intake_speed_applied=bool(speed_result["intake_speed_applied"]),
            outtake_speed_command_sent=speed_result["outtake_speed_command_sent"],
            outtake_speed_reply=speed_result["outtake_speed_reply"],
            outtake_speed_applied=bool(speed_result["outtake_speed_applied"]),
            requested_amounts=requested_amounts,
            calculated_steps=steps,
            command_sent=command,
            reply=reply,
        )


syringe_controller_service = SyringeControllerService()
