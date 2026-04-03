import glob
import math
import time
from dataclasses import dataclass, field
from threading import Lock

from app.models.gantry import (
    GantryXYCalibrationRequest,
    GantryXYCalibrationResponse,
    GantryXYMoveRequest,
    GantryXYMoveResponse,
    GantryZCalibrationRequest,
    GantryZCalibrationResponse,
    GantryZMoveRequest,
    GantryZMoveResponse,
)

STEPS_PER_REVOLUTION = 200
XY_STEPS_PER_CM = 100.0
Z_STEPS_PER_CM = 100.0

SPEED_PROFILE_TO_RPM = {
    "slow": 120,
    "normal": 240,
    "fast": 420,
}

CALIBRATION_SPEED_PROFILE_TO_RPM = {
    "safe": 100,
    "normal": 180,
}


class GantryControllerError(RuntimeError):
    pass


@dataclass
class _ActiveGantrySession:
    serial_port: object
    io_lock: Lock = field(default_factory=Lock)
    cancel_requested: bool = False
    stop_sent: bool = False


class GantryControllerService:
    def __init__(self) -> None:
        self._port_locks: dict[str, Lock] = {}
        self._port_locks_guard = Lock()
        self._active_sessions: dict[str, _ActiveGantrySession] = {}
        self._active_sessions_guard = Lock()

    def _baud_rate(self) -> int:
        return 115200

    def _serial_timeout(self) -> float:
        return 1.0

    def _boot_delay(self) -> float:
        return 2.0

    def _command_deadline(self) -> float:
        return 20.0

    def _move_deadline(self, dominant_steps: float, rpm: int) -> float:
        steps_per_second = max((rpm * STEPS_PER_REVOLUTION) / 60.0, 1.0)
        estimated_runtime = dominant_steps / steps_per_second
        return max(20.0, math.ceil(estimated_runtime * 2.0 + 8.0))

    def _load_serial_module(self):
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise GantryControllerError(
                "pyserial is not installed. Install backend requirements again to enable ESP32 communication."
            ) from exc

        return serial

    def _port_candidates(self) -> list[str]:
        return sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))

    def _selected_port(self, requested_port: str | None = None) -> str:
        if requested_port:
            return requested_port

        candidates = self._port_candidates()
        if not candidates:
            raise GantryControllerError(
                "No ESP32 serial port found. Connect the board or select one explicitly."
            )
        return candidates[0]

    def _port_lock(self, port: str) -> Lock:
        with self._port_locks_guard:
            if port not in self._port_locks:
                self._port_locks[port] = Lock()
            return self._port_locks[port]

    def _register_active_session(self, port: str, serial_port) -> _ActiveGantrySession:
        session = _ActiveGantrySession(serial_port=serial_port)
        with self._active_sessions_guard:
            self._active_sessions[port] = session
        return session

    def _unregister_active_session(self, port: str, session: _ActiveGantrySession) -> None:
        with self._active_sessions_guard:
            if self._active_sessions.get(port) is session:
                del self._active_sessions[port]

    def cancel_operation(self, requested_port: str | None = None) -> dict[str, object]:
        port = self._selected_port(requested_port)
        with self._active_sessions_guard:
            session = self._active_sessions.get(port)

        if session is None:
            return {
                "ok": False,
                "message": f"No active gantry command is running on {port}.",
                "tool_port": port,
            }

        session.cancel_requested = True
        return {
            "ok": True,
            "message": f"Cancellation requested for the active gantry command on {port}.",
            "tool_port": port,
        }

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
        active_session: _ActiveGantrySession | None = None,
    ) -> tuple[str | None, bool]:
        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
        serial_port.write((command + "\n").encode("utf-8"))
        serial_port.flush()

        replies: list[str] = []
        deadline = time.monotonic() + deadline_seconds
        normalized_terminal_prefixes = tuple(prefix.upper() for prefix in terminal_prefixes)

        while time.monotonic() < deadline:
            if active_session and active_session.cancel_requested and not active_session.stop_sent:
                with active_session.io_lock:
                    active_session.serial_port.write(b"STOP\n")
                    active_session.serial_port.flush()
                active_session.stop_sent = True

            reply_bytes = serial_port.readline()
            reply_line = reply_bytes.decode("utf-8", errors="replace").strip()
            if not reply_line:
                continue

            replies.append(reply_line)
            normalized_line = reply_line.upper()
            if any(normalized_line.startswith(prefix) for prefix in normalized_terminal_prefixes):
                return "\n".join(replies), True

        if not replies:
            return None, False

        return "\n".join(replies), False

    def _drain_startup_output(self, serial_port, *, quiet_seconds: float = 0.25, max_seconds: float = 3.0) -> None:
        deadline = time.monotonic() + max_seconds
        last_data_at = time.monotonic()

        while time.monotonic() < deadline:
            reply_bytes = serial_port.readline()
            reply_line = reply_bytes.decode("utf-8", errors="replace").strip()
            if reply_line:
                last_data_at = time.monotonic()
                continue

            if time.monotonic() - last_data_at >= quiet_seconds:
                break

    def _send_config_and_action(
        self,
        *,
        port: str,
        baud_rate: int,
        pin_command: str,
        limit_command: str,
        action_command: str,
        action_prefix: str,
        action_deadline: float,
    ) -> tuple[str | None, str | None, str | None]:
        serial = self._load_serial_module()
        try:
            with self._port_lock(port):
                with serial.Serial(port, baud_rate, timeout=self._serial_timeout()) as serial_port:
                    active_session = self._register_active_session(port, serial_port)
                    boot_delay = self._boot_delay()
                    if boot_delay > 0:
                        time.sleep(boot_delay)
                    self._drain_startup_output(serial_port)

                    try:
                        if active_session.cancel_requested:
                            raise GantryControllerError("Gantry command was cancelled.")

                        pin_reply, pin_completed = self._send_command(
                            serial_port,
                            pin_command,
                            terminal_prefixes=("OK XY PINS", "OK Z PINS", "ERR "),
                            deadline_seconds=self._command_deadline(),
                            active_session=active_session,
                        )
                        if not pin_completed or not self._reply_contains_prefix(pin_reply, ("OK XY PINS", "OK Z PINS")):
                            raise GantryControllerError(
                                f"ESP32 did not acknowledge gantry pin configuration. Reply: {pin_reply}"
                            )

                        limit_reply, limit_completed = self._send_command(
                            serial_port,
                            limit_command,
                            terminal_prefixes=("OK XY LIMITS", "OK Z LIMITS", "ERR "),
                            deadline_seconds=self._command_deadline(),
                            active_session=active_session,
                        )
                        if not limit_completed or not self._reply_contains_prefix(limit_reply, ("OK XY LIMITS", "OK Z LIMITS")):
                            raise GantryControllerError(
                                f"ESP32 did not acknowledge gantry limit configuration. Reply: {limit_reply}"
                            )

                        action_reply, action_completed = self._send_command(
                            serial_port,
                            action_command,
                            terminal_prefixes=(action_prefix, "OK STOP", "ERR "),
                            deadline_seconds=action_deadline,
                            active_session=active_session,
                        )
                        if self._reply_contains_prefix(action_reply, ("OK STOP",)):
                            raise GantryControllerError("Gantry command was cancelled.")
                        if not action_completed or not self._reply_contains_prefix(action_reply, (action_prefix,)):
                            raise GantryControllerError(
                                f"ESP32 did not acknowledge gantry command completion. Reply: {action_reply}"
                            )
                    finally:
                        self._unregister_active_session(port, active_session)
        except Exception as exc:
            raise GantryControllerError(
                f"Failed to communicate with gantry ESP32 on {port}: {exc}"
            ) from exc

        return pin_reply, limit_reply, action_reply

    def _build_xy_pin_command(self, request: GantryXYMoveRequest | GantryXYCalibrationRequest) -> str:
        return (
            f"SET XY PINS {request.x_step_pin} {request.x_dir_pin} "
            f"{request.y_step_pin} {request.y_dir_pin}"
        )

    def _build_xy_limit_command(self, request: GantryXYMoveRequest | GantryXYCalibrationRequest) -> str:
        return (
            f"SET XY LIMITS {request.limit_switch_mode} {request.x_min_limit_pin} "
            f"{request.x_max_limit_pin} {request.y_min_limit_pin} {request.y_max_limit_pin}"
        )

    def _build_move_xy_command(self, request: GantryXYMoveRequest) -> str:
        return f"MOVE XY {request.x_cm:.3f} {request.y_cm:.3f} {request.speed_profile}"

    def _build_calibrate_xy_command(self, request: GantryXYCalibrationRequest) -> str:
        return (
            f"CALIBRATE XY {request.x_track_length_cm:.3f} "
            f"{request.y_track_length_cm:.3f} {request.calibration_speed_profile}"
        )

    def _build_z_pin_command(self, request: GantryZMoveRequest | GantryZCalibrationRequest) -> str:
        return (
            f"SET Z PINS {request.z_left_step_pin} {request.z_left_dir_pin} "
            f"{request.z_right_step_pin} {request.z_right_dir_pin}"
        )

    def _build_z_limit_command(self, request: GantryZMoveRequest | GantryZCalibrationRequest) -> str:
        return (
            f"SET Z LIMITS {request.limit_switch_mode} {request.z_left_min_limit_pin} "
            f"{request.z_left_max_limit_pin} {request.z_right_min_limit_pin} {request.z_right_max_limit_pin}"
        )

    def _build_move_z_command(self, request: GantryZMoveRequest) -> str:
        return f"MOVE Z {request.z_left_cm:.3f} {request.z_right_cm:.3f} {request.speed_profile}"

    def _build_calibrate_z_command(self, request: GantryZCalibrationRequest) -> str:
        return (
            f"CALIBRATE Z {request.z_left_track_length_cm:.3f} "
            f"{request.z_right_track_length_cm:.3f} {request.calibration_speed_profile}"
        )

    def move_xy(self, request: GantryXYMoveRequest) -> GantryXYMoveResponse:
        port = self._selected_port(request.tool_port)
        baud_rate = request.baud_rate or self._baud_rate()
        pin_command = self._build_xy_pin_command(request)
        limit_command = self._build_xy_limit_command(request)
        move_command = self._build_move_xy_command(request)
        dominant_steps = max(abs(request.x_cm) * XY_STEPS_PER_CM, abs(request.y_cm) * XY_STEPS_PER_CM)
        pin_reply, limit_reply, move_reply = self._send_config_and_action(
            port=port,
            baud_rate=baud_rate,
            pin_command=pin_command,
            limit_command=limit_command,
            action_command=move_command,
            action_prefix="OK MOVE XY",
            action_deadline=self._move_deadline(dominant_steps, SPEED_PROFILE_TO_RPM[request.speed_profile]),
        )

        return GantryXYMoveResponse(
            port=port,
            baud_rate=baud_rate,
            speed_profile=request.speed_profile,
            pin_command_sent=pin_command,
            pin_reply=pin_reply,
            pins_applied=True,
            limit_command_sent=limit_command,
            limit_reply=limit_reply,
            limits_applied=True,
            move_command_sent=move_command,
            move_reply=move_reply,
            move_applied=True,
            target={"x_cm": request.x_cm, "y_cm": request.y_cm},
            configured_pins={
                "x_step_pin": request.x_step_pin,
                "x_dir_pin": request.x_dir_pin,
                "y_step_pin": request.y_step_pin,
                "y_dir_pin": request.y_dir_pin,
            },
            configured_limits={
                "limit_switch_mode": request.limit_switch_mode,
                "x_min_limit_pin": request.x_min_limit_pin,
                "x_max_limit_pin": request.x_max_limit_pin,
                "y_min_limit_pin": request.y_min_limit_pin,
                "y_max_limit_pin": request.y_max_limit_pin,
                "speed_rpm": SPEED_PROFILE_TO_RPM[request.speed_profile],
            },
        )

    def calibrate_xy(self, request: GantryXYCalibrationRequest) -> GantryXYCalibrationResponse:
        port = self._selected_port(request.tool_port)
        baud_rate = request.baud_rate or self._baud_rate()
        pin_command = self._build_xy_pin_command(request)
        limit_command = self._build_xy_limit_command(request)
        calibration_command = self._build_calibrate_xy_command(request)
        dominant_steps = max(
            request.x_track_length_cm * XY_STEPS_PER_CM,
            request.y_track_length_cm * XY_STEPS_PER_CM,
        )
        pin_reply, limit_reply, calibration_reply = self._send_config_and_action(
            port=port,
            baud_rate=baud_rate,
            pin_command=pin_command,
            limit_command=limit_command,
            action_command=calibration_command,
            action_prefix="OK CALIBRATE XY",
            action_deadline=self._move_deadline(
                dominant_steps * 3.0,
                CALIBRATION_SPEED_PROFILE_TO_RPM[request.calibration_speed_profile],
            ),
        )

        return GantryXYCalibrationResponse(
            port=port,
            baud_rate=baud_rate,
            calibration_speed_profile=request.calibration_speed_profile,
            pin_command_sent=pin_command,
            pin_reply=pin_reply,
            pins_applied=True,
            limit_command_sent=limit_command,
            limit_reply=limit_reply,
            limits_applied=True,
            calibration_command_sent=calibration_command,
            calibration_reply=calibration_reply,
            calibrated=True,
            workspace={
                "x_track_length_cm": request.x_track_length_cm,
                "y_track_length_cm": request.y_track_length_cm,
            },
            configured_pins={
                "x_step_pin": request.x_step_pin,
                "x_dir_pin": request.x_dir_pin,
                "y_step_pin": request.y_step_pin,
                "y_dir_pin": request.y_dir_pin,
            },
            configured_limits={
                "limit_switch_mode": request.limit_switch_mode,
                "x_min_limit_pin": request.x_min_limit_pin,
                "x_max_limit_pin": request.x_max_limit_pin,
                "y_min_limit_pin": request.y_min_limit_pin,
                "y_max_limit_pin": request.y_max_limit_pin,
                "speed_rpm": CALIBRATION_SPEED_PROFILE_TO_RPM[request.calibration_speed_profile],
            },
        )

    def move_z(self, request: GantryZMoveRequest) -> GantryZMoveResponse:
        port = self._selected_port(request.tool_port)
        baud_rate = request.baud_rate or self._baud_rate()
        pin_command = self._build_z_pin_command(request)
        limit_command = self._build_z_limit_command(request)
        move_command = self._build_move_z_command(request)
        dominant_steps = max(abs(request.z_left_cm) * Z_STEPS_PER_CM, abs(request.z_right_cm) * Z_STEPS_PER_CM)
        pin_reply, limit_reply, move_reply = self._send_config_and_action(
            port=port,
            baud_rate=baud_rate,
            pin_command=pin_command,
            limit_command=limit_command,
            action_command=move_command,
            action_prefix="OK MOVE Z",
            action_deadline=self._move_deadline(dominant_steps, SPEED_PROFILE_TO_RPM[request.speed_profile]),
        )

        return GantryZMoveResponse(
            port=port,
            baud_rate=baud_rate,
            speed_profile=request.speed_profile,
            pin_command_sent=pin_command,
            pin_reply=pin_reply,
            pins_applied=True,
            limit_command_sent=limit_command,
            limit_reply=limit_reply,
            limits_applied=True,
            move_command_sent=move_command,
            move_reply=move_reply,
            move_applied=True,
            target={"z_left_cm": request.z_left_cm, "z_right_cm": request.z_right_cm},
            configured_pins={
                "z_left_step_pin": request.z_left_step_pin,
                "z_left_dir_pin": request.z_left_dir_pin,
                "z_right_step_pin": request.z_right_step_pin,
                "z_right_dir_pin": request.z_right_dir_pin,
            },
            configured_limits={
                "limit_switch_mode": request.limit_switch_mode,
                "z_left_min_limit_pin": request.z_left_min_limit_pin,
                "z_left_max_limit_pin": request.z_left_max_limit_pin,
                "z_right_min_limit_pin": request.z_right_min_limit_pin,
                "z_right_max_limit_pin": request.z_right_max_limit_pin,
                "speed_rpm": SPEED_PROFILE_TO_RPM[request.speed_profile],
            },
        )

    def calibrate_z(self, request: GantryZCalibrationRequest) -> GantryZCalibrationResponse:
        port = self._selected_port(request.tool_port)
        baud_rate = request.baud_rate or self._baud_rate()
        pin_command = self._build_z_pin_command(request)
        limit_command = self._build_z_limit_command(request)
        calibration_command = self._build_calibrate_z_command(request)
        dominant_steps = max(
            request.z_left_track_length_cm * Z_STEPS_PER_CM,
            request.z_right_track_length_cm * Z_STEPS_PER_CM,
        )
        pin_reply, limit_reply, calibration_reply = self._send_config_and_action(
            port=port,
            baud_rate=baud_rate,
            pin_command=pin_command,
            limit_command=limit_command,
            action_command=calibration_command,
            action_prefix="OK CALIBRATE Z",
            action_deadline=self._move_deadline(
                dominant_steps * 3.0,
                CALIBRATION_SPEED_PROFILE_TO_RPM[request.calibration_speed_profile],
            ),
        )

        return GantryZCalibrationResponse(
            port=port,
            baud_rate=baud_rate,
            calibration_speed_profile=request.calibration_speed_profile,
            pin_command_sent=pin_command,
            pin_reply=pin_reply,
            pins_applied=True,
            limit_command_sent=limit_command,
            limit_reply=limit_reply,
            limits_applied=True,
            calibration_command_sent=calibration_command,
            calibration_reply=calibration_reply,
            calibrated=True,
            workspace={
                "z_left_track_length_cm": request.z_left_track_length_cm,
                "z_right_track_length_cm": request.z_right_track_length_cm,
            },
            configured_pins={
                "z_left_step_pin": request.z_left_step_pin,
                "z_left_dir_pin": request.z_left_dir_pin,
                "z_right_step_pin": request.z_right_step_pin,
                "z_right_dir_pin": request.z_right_dir_pin,
            },
            configured_limits={
                "limit_switch_mode": request.limit_switch_mode,
                "z_left_min_limit_pin": request.z_left_min_limit_pin,
                "z_left_max_limit_pin": request.z_left_max_limit_pin,
                "z_right_min_limit_pin": request.z_right_min_limit_pin,
                "z_right_max_limit_pin": request.z_right_max_limit_pin,
                "speed_rpm": CALIBRATION_SPEED_PROFILE_TO_RPM[request.calibration_speed_profile],
            },
        )


gantry_controller_service = GantryControllerService()
