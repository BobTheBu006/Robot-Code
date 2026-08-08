import glob
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from app.core.safety import PRIORITY_SERIAL, CallableActor, safety_controller
from app.models.syringe import (
    SyringeCalibrationEntry,
    SyringeDispenseRequest,
    SyringeDispenseResponse,
    SyringePrimeRequest,
    SyringePrimeResponse,
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
AUTO_PIN_COMMAND_FORMATS: tuple[str, ...] = (
    "set_head_pins_space",
    "head_pins_space",
)
DEFAULT_HEAD_PINS: dict[SyringeHead, dict[str, int]] = {
    "A": {"step": 33, "dir": 32},
    "B": {"step": 25, "dir": 4},
    "C": {"step": 26, "dir": 5},
    "D": {"step": 27, "dir": 18},
    "E": {"step": 14, "dir": 19},
    "F": {"step": 12, "dir": 21},
    "G": {"step": 13, "dir": 22},
}


class SyringeControllerError(RuntimeError):
    pass


@dataclass
class _ActiveSyringeSession:
    serial_port: object
    io_lock: Lock = field(default_factory=Lock)
    emergency_stop_requested: bool = False
    stop_sent: bool = False


class SyringeControllerService:
    def __init__(self) -> None:
        self._port_locks: dict[str, Lock] = {}
        self._port_locks_guard = Lock()
        self._active_sessions: dict[str, _ActiveSyringeSession] = {}
        self._active_sessions_guard = Lock()

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

    def _speed_command_deadline(self) -> float:
        return float(os.getenv("SYRINGE_SPEED_COMMAND_DEADLINE_SECONDS", "6.0"))

    def _dispense_command_deadline(self) -> float:
        return float(os.getenv("SYRINGE_DISPENSE_COMMAND_DEADLINE_SECONDS", "120.0"))

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

    def _requested_head_pins(self, request: SyringeDispenseRequest) -> dict[SyringeHead, dict[str, int]]:
        head_pins: dict[SyringeHead, dict[str, int]] = {}
        for head in HEADS:
            lower_head = head.lower()
            step_pin = getattr(request, f"head_{lower_head}_step_pin", None)
            dir_pin = getattr(request, f"head_{lower_head}_dir_pin", None)
            defaults = DEFAULT_HEAD_PINS[head]
            head_pins[head] = {
                "step": int(step_pin) if step_pin is not None else defaults["step"],
                "dir": int(dir_pin) if dir_pin is not None else defaults["dir"],
            }

        return head_pins

    def _build_pin_command(
        self,
        head: SyringeHead,
        step_pin: int,
        dir_pin: int,
        command_format: str,
    ) -> str:
        command_format = command_format.lower()

        if command_format == "set_head_pins_space":
            return f"SET HEAD PINS {head} {step_pin} {dir_pin}"

        if command_format == "head_pins_space":
            return f"HEAD PINS {head} {step_pin} {dir_pin}"

        raise SyringeControllerError(
            f"Unsupported syringe pin command format '{command_format}'."
        )

    def _port_lock(self, port: str) -> Lock:
        with self._port_locks_guard:
            if port not in self._port_locks:
                self._port_locks[port] = Lock()
            return self._port_locks[port]

    def _register_active_session(self, port: str, serial_port) -> _ActiveSyringeSession:
        session = _ActiveSyringeSession(serial_port=serial_port)
        with self._active_sessions_guard:
            self._active_sessions[port] = session
        return session

    def _unregister_active_session(self, port: str, session: _ActiveSyringeSession) -> None:
        with self._active_sessions_guard:
            if self._active_sessions.get(port) is session:
                del self._active_sessions[port]

    def emergency_stop(self) -> list[dict[str, object]]:
        with self._active_sessions_guard:
            active_sessions = list(self._active_sessions.items())

        results: list[dict[str, object]] = []
        for port, session in active_sessions:
            session.emergency_stop_requested = True
            try:
                if not session.stop_sent:
                    with session.io_lock:
                        session.serial_port.write(b"STOP\n")
                        session.serial_port.flush()
                    session.stop_sent = True
                results.append({"ok": True, "tool": "syringe", "tool_port": port, "message": "STOP sent."})
            except Exception as exc:
                results.append({"ok": False, "tool": "syringe", "tool_port": port, "message": str(exc)})

        if not results:
            results.append({"ok": True, "tool": "syringe", "tool_port": None, "message": "No active syringe command."})

        return results

    def _reply_contains_prefix(self, reply: str | None, prefixes: tuple[str, ...]) -> bool:
        if not reply:
            return False

        normalized_prefixes = tuple(prefix.upper() for prefix in prefixes)
        for line in reply.splitlines():
            normalized_line = line.strip().upper()
            if any(normalized_line.startswith(prefix) for prefix in normalized_prefixes):
                return True

        return False

    def _send_command(
        self,
        serial_port,
        command: str,
        *,
        terminal_prefixes: tuple[str, ...],
        deadline_seconds: float,
        active_session: _ActiveSyringeSession | None = None,
    ) -> tuple[str | None, bool]:
        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
        serial_port.write((command + "\n").encode("utf-8"))
        serial_port.flush()
        replies: list[str] = []
        deadline = time.monotonic() + max(deadline_seconds, self._serial_timeout())
        normalized_terminal_prefixes = tuple(prefix.upper() for prefix in terminal_prefixes)

        while time.monotonic() < deadline:
            if active_session and active_session.emergency_stop_requested:
                if not active_session.stop_sent:
                    with active_session.io_lock:
                        active_session.serial_port.write(b"STOP\n")
                        active_session.serial_port.flush()
                    active_session.stop_sent = True
                raise SyringeControllerError("Syringe command was stopped by E-Stop.")

            reply_bytes = serial_port.readline()
            reply_line = reply_bytes.decode("utf-8", errors="replace").strip()
            if not reply_line:
                continue

            replies.append(reply_line)

            normalized = reply_line.upper()
            if any(normalized.startswith(prefix) for prefix in normalized_terminal_prefixes):
                return "\n".join(replies), True

        if not replies:
            return None, False

        return "\n".join(replies), False

    def _try_apply_speed(self, serial_port, speed: int) -> tuple[str | None, str | None, bool]:
        for command_format in AUTO_SPEED_COMMAND_FORMATS:
            command = self._build_speed_command(speed, command_format)
            reply, completed = self._send_command(
                serial_port,
                command,
                terminal_prefixes=("OK SPEED", "ERR "),
                deadline_seconds=self._speed_command_deadline(),
            )
            if completed and self._reply_contains_prefix(reply, ("OK SPEED",)):
                return command, reply, True
            if completed and not self._is_unknown_command_reply(reply):
                return command, reply, False

        return None, None, False

    def _try_apply_speed_with_formats(
        self,
        serial_port,
        speed: int,
        command_formats: tuple[str, ...],
    ) -> tuple[str | None, str | None, bool]:
        for command_format in command_formats:
            command = self._build_speed_command(speed, command_format)
            expected_prefixes = ("OK SPEED",)
            if "intake" in command_format:
                expected_prefixes = ("OK INTAKE SPEED",)
            elif "outtake" in command_format:
                expected_prefixes = ("OK OUTTAKE SPEED",)

            reply, completed = self._send_command(
                serial_port,
                command,
                terminal_prefixes=(*expected_prefixes, "ERR "),
                deadline_seconds=self._speed_command_deadline(),
            )
            if completed and self._reply_contains_prefix(reply, expected_prefixes):
                return command, reply, True
            if completed and not self._is_unknown_command_reply(reply):
                return command, reply, False

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

    def _apply_head_pin_profile(
        self,
        serial_port,
        configured_pins: dict[SyringeHead, dict[str, int]],
    ) -> dict[str, object]:
        commands_sent: list[str] = []
        replies: list[str] = []

        for head, pins in configured_pins.items():
            expected_prefix = f"OK HEAD {head} PINS"
            applied = False

            for command_format in AUTO_PIN_COMMAND_FORMATS:
                command = self._build_pin_command(
                    head,
                    pins["step"],
                    pins["dir"],
                    command_format,
                )
                reply, completed = self._send_command(
                    serial_port,
                    command,
                    terminal_prefixes=(expected_prefix, "ERR "),
                    deadline_seconds=self._speed_command_deadline(),
                )

                if command not in commands_sent:
                    commands_sent.append(command)

                if reply:
                    replies.append(reply)

                if completed and self._reply_contains_prefix(reply, (expected_prefix,)):
                    applied = True
                    break

                if completed and not self._is_unknown_command_reply(reply):
                    raise SyringeControllerError(
                        f"ESP32 rejected head {head} pin configuration: {reply}"
                    )

            if not applied:
                raise SyringeControllerError(
                    f"ESP32 did not acknowledge head {head} pin configuration."
                )

        return {
            "pin_config_commands_sent": commands_sent,
            "pin_config_replies": replies,
            "pin_config_applied": True,
            "configured_pins": configured_pins,
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
        configured_pins = self._requested_head_pins(request)
        port = self._selected_port(request.port)
        baud_rate = request.baud_rate or self._baud_rate()
        serial = self._load_serial_module()
        try:
            with self._port_lock(port):
                with serial.Serial(port, baud_rate, timeout=self._serial_timeout()) as serial_port:
                    active_session = self._register_active_session(port, serial_port)
                    try:
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
                        pin_result: dict[str, object] = {
                            "pin_config_commands_sent": [],
                            "pin_config_replies": [],
                            "pin_config_applied": False,
                            "configured_pins": configured_pins,
                        }

                        pin_result = self._apply_head_pin_profile(
                            serial_port,
                            configured_pins,
                        )

                        if request.speed or request.intake_speed or request.outtake_speed:
                            speed_result = self._apply_speed_profile(
                                serial_port,
                                request.speed,
                                request.intake_speed,
                                request.outtake_speed,
                            )

                        for command_format in self._command_formats_to_try():
                            command = self._build_command(steps, command_format)
                            reply, completed = self._send_command(
                                serial_port,
                                command,
                                terminal_prefixes=("OK DISPENSE", "ERR "),
                                deadline_seconds=self._dispense_command_deadline(),
                                active_session=active_session,
                            )
                            selected_format = command_format

                            if not completed:
                                raise SyringeControllerError(
                                    "Timed out while waiting for the ESP32 to finish dispensing."
                                )

                            if self._reply_contains_prefix(reply, ("OK DISPENSE",)):
                                break

                            if not self._is_unknown_command_reply(reply):
                                raise SyringeControllerError(
                                    f"ESP32 rejected the dispense command: {reply}"
                                )
                    finally:
                        self._unregister_active_session(port, active_session)
        except Exception as exc:
            raise SyringeControllerError(
                f"Failed to communicate with ESP32 on {port}: {exc}"
            ) from exc

        if command is None or selected_format is None:
            raise SyringeControllerError("No syringe command format was available to try.")

        if not self._reply_contains_prefix(reply, ("OK DISPENSE",)):
            raise SyringeControllerError(
                f"ESP32 did not acknowledge a completed dispense command. Last reply: {reply}"
            )

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
            pin_config_commands_sent=list(pin_result["pin_config_commands_sent"]),
            pin_config_replies=list(pin_result["pin_config_replies"]),
            pin_config_applied=bool(pin_result["pin_config_applied"]),
            configured_pins=dict(pin_result["configured_pins"]),
            requested_amounts=requested_amounts,
            calculated_steps=steps,
            command_sent=command,
            reply=reply,
        )

    def _move_command_deadline(self, max_steps: int, rpm: int) -> float:
        # Full-step firmware: steps/s = rpm * 200 / 60. Generous 2x margin plus
        # serial slack so a slow prime stroke is never cut off mid-move.
        steps_per_second = max(1.0, rpm * 200.0 / 60.0)
        return (max_steps / steps_per_second) * 2.0 + 5.0

    def _send_move(
        self,
        serial_port,
        steps_by_head: dict[SyringeHead, int],
        direction: int,
        rpm: int,
        active_session: _ActiveSyringeSession | None,
        commands_sent: list[str],
        replies: list[str],
    ) -> None:
        """One-directional MOVE: positive direction pushes the plungers
        (dispense direction, toward the bottom hard stop), negative draws."""
        ordered = [direction * steps_by_head[head] for head in HEADS]
        command = "MOVE " + " ".join(str(value) for value in ordered) + f" {rpm}"
        reply, completed = self._send_command(
            serial_port,
            command,
            terminal_prefixes=("OK MOVE", "ERR "),
            deadline_seconds=self._move_command_deadline(max(steps_by_head.values()), rpm),
            active_session=active_session,
        )
        commands_sent.append(command)
        if reply:
            replies.append(reply)
        if not completed:
            raise SyringeControllerError("Timed out while waiting for the ESP32 to finish a MOVE.")
        if not self._reply_contains_prefix(reply, ("OK MOVE",)):
            raise SyringeControllerError(f"ESP32 rejected the MOVE command: {reply}")

    def prime(self, request: SyringePrimeRequest) -> SyringePrimeResponse:
        """Home all plungers against the bottom hard stop, then run draw/push
        prime cycles.

        There is no plunger position feedback: homing deliberately over-drives
        every plunger in the dispense (push) direction so each one bottoms out
        on the mechanical stop, which becomes the known zero. The steppers
        skip steps at the stop by design. Each prime cycle then draws
        prime_volume up and pushes it back out, ending at the stop again.
        """
        calibration_path = self._calibration_path(request.calibration_file)
        calibration = self._load_calibration(request.calibration_file)

        home_steps = {
            head: max(1, round(calibration[head].a * request.home_overtravel_ul + calibration[head].b))
            for head in HEADS
        }
        prime_steps = {
            head: max(1, round(calibration[head].a * request.prime_volume_ul + calibration[head].b))
            for head in HEADS
        }
        final_draw_steps = {
            head: (
                max(1, round(calibration[head].a * request.final_draw_ul + calibration[head].b))
                if request.final_draw_ul > 0
                else 0
            )
            for head in HEADS
        }

        configured_pins = self._requested_head_pins(request)
        port = self._selected_port(request.port)
        baud_rate = request.baud_rate or self._baud_rate()
        serial = self._load_serial_module()
        commands_sent: list[str] = []
        replies: list[str] = []

        try:
            with self._port_lock(port):
                with serial.Serial(port, baud_rate, timeout=self._serial_timeout()) as serial_port:
                    active_session = self._register_active_session(port, serial_port)
                    try:
                        boot_delay = self._boot_delay()
                        if boot_delay > 0:
                            time.sleep(boot_delay)

                        pin_result = self._apply_head_pin_profile(serial_port, configured_pins)

                        # Home: push everything to the bottom hard stop.
                        self._send_move(
                            serial_port, home_steps, +1, request.speed,
                            active_session, commands_sent, replies,
                        )

                        # Prime cycles: draw up, push back out.
                        for _ in range(request.prime_cycles):
                            self._send_move(
                                serial_port, prime_steps, -1, request.speed,
                                active_session, commands_sent, replies,
                            )
                            self._send_move(
                                serial_port, prime_steps, +1, request.speed,
                                active_session, commands_sent, replies,
                            )

                        # Final draw: leave the plungers pulled up and ready to
                        # dispense rather than seated on the stop.
                        if request.final_draw_ul > 0:
                            self._send_move(
                                serial_port, final_draw_steps, -1, request.speed,
                                active_session, commands_sent, replies,
                            )
                    finally:
                        self._unregister_active_session(port, active_session)
        except SyringeControllerError:
            raise
        except Exception as exc:
            raise SyringeControllerError(
                f"Failed to communicate with ESP32 on {port}: {exc}"
            ) from exc

        return SyringePrimeResponse(
            port=port,
            baud_rate=baud_rate,
            calibration_file=str(calibration_path),
            speed=request.speed,
            prime_volume_ul=request.prime_volume_ul,
            prime_cycles=request.prime_cycles,
            home_overtravel_ul=request.home_overtravel_ul,
            final_draw_ul=request.final_draw_ul,
            final_draw_steps=final_draw_steps,
            home_steps=home_steps,
            prime_steps=prime_steps,
            pin_config_commands_sent=list(pin_result["pin_config_commands_sent"]),
            pin_config_replies=list(pin_result["pin_config_replies"]),
            pin_config_applied=bool(pin_result["pin_config_applied"]),
            configured_pins=dict(pin_result["configured_pins"]),
            commands_sent=commands_sent,
            replies=replies,
        )


syringe_controller_service = SyringeControllerService()

safety_controller.register_actor(
    CallableActor("syringe-serial", syringe_controller_service.emergency_stop),
    priority=PRIORITY_SERIAL,
    description="Syringe pump ESP32 serial sessions",
)
