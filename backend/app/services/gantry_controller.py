import glob
import math
import time
from dataclasses import dataclass, field
from threading import Lock

from app.models.gantry import (
    GANTRY_WORKSPACE_X_CM,
    GantryCircleXYRequest,
    GantryCircleXYResponse,
    GantryGotoXYRequest,
    GantryGotoXYResponse,
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


def _effective_move_rpm(request) -> int:
    return int(getattr(request, "speed_rpm", SPEED_PROFILE_TO_RPM[getattr(request, "speed_profile", "normal")]))


def _effective_calibration_rpm(request) -> int:
    return int(getattr(
        request,
        "speed_rpm",
        CALIBRATION_SPEED_PROFILE_TO_RPM[getattr(request, "calibration_speed_profile", "safe")],
    ))


def _trapezoid_flag(request) -> int:
    return 1 if bool(getattr(request, "trapezoidal_speed", True)) else 0


def _acceleration_rpm_per_s(request) -> int:
    return int(getattr(request, "acceleration_rpm_per_s", 0))


class GantryControllerError(RuntimeError):
    pass


class GantryControllerReportedError(GantryControllerError):
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
        # Serial connections kept open and reused across commands so the ESP32 is
        # not reset (and the boot delay re-paid) on every workflow block.
        self._open_connections: dict[str, object] = {}

    def _baud_rate(self) -> int:
        return 115200

    def _serial_timeout(self) -> float:
        return 1.0

    def _boot_delay(self) -> float:
        return 2.0

    def _command_deadline(self) -> float:
        return 20.0

    def _move_deadline(self, dominant_steps: float, rpm: int, steps_per_revolution: int = STEPS_PER_REVOLUTION) -> float:
        steps_per_second = max((rpm * steps_per_revolution) / 60.0, 1.0)
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
        if not session.stop_sent:
            with session.io_lock:
                session.serial_port.write(b"STOP\n")
                session.serial_port.flush()
            session.stop_sent = True
        return {
            "ok": True,
            "message": f"STOP sent to the active gantry command on {port}.",
            "tool_port": port,
        }

    def emergency_stop(self) -> list[dict[str, object]]:
        with self._active_sessions_guard:
            active_sessions = list(self._active_sessions.items())

        results: list[dict[str, object]] = []
        for port, session in active_sessions:
            session.cancel_requested = True
            try:
                if not session.stop_sent:
                    with session.io_lock:
                        session.serial_port.write(b"STOP\n")
                        session.serial_port.flush()
                    session.stop_sent = True
                results.append({"ok": True, "tool": "gantry", "tool_port": port, "message": "STOP sent."})
            except Exception as exc:
                results.append({"ok": False, "tool": "gantry", "tool_port": port, "message": str(exc)})

        if not results:
            results.append({"ok": True, "tool": "gantry", "tool_port": None, "message": "No active gantry command."})

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

    def _reply_last_prefixed_line(self, reply: str | None, prefixes: tuple[str, ...]) -> str | None:
        if not reply:
            return None
        normalized_prefixes = tuple(prefix.upper() for prefix in prefixes)
        for line in reversed(reply.splitlines()):
            normalized_line = line.strip().upper()
            if any(normalized_line.startswith(prefix) for prefix in normalized_prefixes):
                return line.strip()
        return None

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

    def _acquire_connection(self, serial_module, port: str, baud_rate: int):
        """Return an open serial connection for the port, reusing a cached one.

        Reusing the connection keeps the ESP32 powered and awake between blocks,
        so the auto-reset + boot delay is only paid on the first command. Must be
        called while holding the port lock.
        """
        cached = self._open_connections.get(port)
        if cached is not None:
            try:
                if getattr(cached, "is_open", False):
                    return cached
            except Exception:
                pass
            self._close_connection(port)

        serial_port = serial_module.Serial(port, baud_rate, timeout=self._serial_timeout())
        try:
            boot_delay = self._boot_delay()
            if boot_delay > 0:
                time.sleep(boot_delay)
            self._drain_startup_output(serial_port)
        except Exception:
            try:
                serial_port.close()
            except Exception:
                pass
            raise

        self._open_connections[port] = serial_port
        return serial_port

    def _close_connection(self, port: str) -> None:
        serial_port = self._open_connections.pop(port, None)
        if serial_port is None:
            return
        try:
            serial_port.close()
        except Exception:
            pass

    def _send_config_and_action(
        self,
        *,
        port: str,
        baud_rate: int,
        pin_command: str | list[str],
        limit_command: str | list[str],
        action_command: str | list[str],
        action_prefix: str,
        action_deadline: float,
        enable_command: str | list[str] | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        serial = self._load_serial_module()
        try:
            with self._port_lock(port):
                serial_port = self._acquire_connection(serial, port, baud_rate)
                active_session = self._register_active_session(port, serial_port)

                try:
                    try:
                        if active_session.cancel_requested:
                            raise GantryControllerError("Gantry command was cancelled.")

                        pin_replies: list[str] = []
                        for next_pin_command in self._command_list(pin_command):
                            pin_reply, pin_completed = self._send_command(
                                serial_port,
                                next_pin_command,
                                terminal_prefixes=("OK XY PINS", "OK Z PINS", "ERR "),
                                deadline_seconds=self._command_deadline(),
                                active_session=active_session,
                            )
                            if not pin_completed or not self._reply_contains_prefix(pin_reply, ("OK XY PINS", "OK Z PINS")):
                                raise GantryControllerError(
                                    f"ESP32 did not acknowledge gantry pin configuration. Reply: {pin_reply}"
                                )
                            if pin_reply:
                                pin_replies.append(pin_reply)
                        pin_reply = "\n".join(pin_replies) if pin_replies else None

                        if enable_command is not None:
                            for next_enable_command in self._command_list(enable_command):
                                enable_reply, enable_completed = self._send_command(
                                    serial_port,
                                    next_enable_command,
                                    terminal_prefixes=("OK XY ENABLE", "OK Z ENABLE", "ERR "),
                                    deadline_seconds=self._command_deadline(),
                                    active_session=active_session,
                                )
                                if not enable_completed or not self._reply_contains_prefix(
                                    enable_reply, ("OK XY ENABLE", "OK Z ENABLE")
                                ):
                                    raise GantryControllerError(
                                        f"ESP32 did not acknowledge gantry enable configuration. Reply: {enable_reply}"
                                    )

                        limit_replies: list[str] = []
                        for next_limit_command in self._command_list(limit_command):
                            limit_reply, limit_completed = self._send_command(
                                serial_port,
                                next_limit_command,
                                terminal_prefixes=("OK XY LIMITS", "OK Z LIMITS", "ERR "),
                                deadline_seconds=self._command_deadline(),
                                active_session=active_session,
                            )
                            if not limit_completed or not self._reply_contains_prefix(limit_reply, ("OK XY LIMITS", "OK Z LIMITS")):
                                raise GantryControllerError(
                                    f"ESP32 did not acknowledge gantry limit configuration. Reply: {limit_reply}"
                                )
                            if limit_reply:
                                limit_replies.append(limit_reply)
                        limit_reply = "\n".join(limit_replies) if limit_replies else None

                        action_replies: list[str] = []
                        for next_action_command in self._command_list(action_command):
                            action_reply, action_completed = self._send_command(
                                serial_port,
                                next_action_command,
                                terminal_prefixes=(action_prefix, "OK STOP", "ERR "),
                                deadline_seconds=action_deadline,
                                active_session=active_session,
                            )
                            if self._reply_contains_prefix(action_reply, ("OK STOP",)):
                                raise GantryControllerError("Gantry command was cancelled.")
                            if self._reply_contains_prefix(action_reply, ("ERR ",)):
                                terminal_error = self._reply_last_prefixed_line(action_reply, ("ERR ",))
                                raise GantryControllerReportedError(
                                    f"ESP32 reported gantry error: {terminal_error}. Full reply: {action_reply}"
                                )
                            if not action_completed or not self._reply_contains_prefix(action_reply, (action_prefix,)):
                                raise GantryControllerError(
                                    f"ESP32 did not send expected completion '{action_prefix}'. Full reply: {action_reply}"
                                )
                            if action_reply:
                                action_replies.append(action_reply)
                        action_reply = "\n".join(action_replies) if action_replies else None
                    finally:
                        self._unregister_active_session(port, active_session)
                except Exception:
                    # Drop the (possibly broken) connection so the next command
                    # re-opens a fresh, reset board.
                    self._close_connection(port)
                    raise
        except Exception as exc:
            raise GantryControllerError(
                f"Failed to communicate with gantry ESP32 on {port}: {exc}"
            ) from exc

        return pin_reply, limit_reply, action_reply

    def _command_list(self, command: str | list[str]) -> list[str]:
        return command if isinstance(command, list) else [command]

    def _build_xy_pin_command(self, request: GantryXYMoveRequest | GantryXYCalibrationRequest | GantryCircleXYRequest) -> str:
        return (
            f"SET XY PINS {request.x_step_pin} {request.x_dir_pin} "
            f"{request.y_step_pin} {request.y_dir_pin}"
        )

    def _build_xy_limit_command(self, request: GantryXYMoveRequest | GantryXYCalibrationRequest | GantryCircleXYRequest) -> str:
        if isinstance(request, GantryXYCalibrationRequest):
            return (
                f"SET XY LIMITS {request.x_min_limit_pin} {request.x_max_limit_pin} "
                f"{request.y_min_limit_pin} {request.y_max_limit_pin}"
            )
        return (
            f"SET XY LIMITS {request.limit_switch_mode} {request.x_min_limit_pin} "
            f"{request.x_max_limit_pin} {request.y_min_limit_pin} {request.y_max_limit_pin}"
        )

    def _build_xy_enable_command(self, request: GantryXYMoveRequest | GantryXYCalibrationRequest | GantryCircleXYRequest) -> str | None:
        # Only configure driver enable pins when at least one is wired. When both
        # are unassigned (-1) the drivers are assumed hardwired-enabled, and we
        # skip the command entirely so older firmware without SET XY ENABLE keeps
        # working unchanged.
        if request.x_enable_pin < 0 and request.y_enable_pin < 0:
            return None
        return (
            f"SET XY ENABLE {request.x_enable_pin} {request.y_enable_pin} "
            f"{1 if request.enable_active_low else 0}"
        )

    def _build_move_xy_command(self, request: GantryXYMoveRequest) -> str:
        return (
            f"MOVE XYZ {request.x_cm:.3f} {request.y_cm:.3f} {request.z_cm:.3f} "
            f"{_effective_move_rpm(request)} {_trapezoid_flag(request)} {_acceleration_rpm_per_s(request)} "
            f"{1 if request.on_the_fly_calibration else 0} {request.calibration_max_diff_steps}"
        )

    def _build_calibrate_xy_command(self, request: GantryXYCalibrationRequest) -> str:
        return (
            f"CALIBRATE XY {request.x_track_length_cm:.3f} {request.y_track_length_cm:.3f} "
            f"{_effective_calibration_rpm(request)} {_trapezoid_flag(request)} {_acceleration_rpm_per_s(request)} "
            f"{request.steps_per_rotation} {request.max_probe_rotations}"
        )

    def _build_z_pin_command(self, request: GantryXYMoveRequest | GantryZMoveRequest | GantryZCalibrationRequest) -> str:
        return (
            f"SET Z PINS {request.z_left_step_pin} {request.z_left_dir_pin} "
            f"{request.z_right_step_pin} {request.z_right_dir_pin}"
        )

    def _build_z_limit_command(self, request: GantryXYMoveRequest | GantryZMoveRequest | GantryZCalibrationRequest) -> str:
        if isinstance(request, GantryZCalibrationRequest):
            return (
                f"SET Z LIMITS {request.z_left_min_limit_pin} {request.z_left_max_limit_pin} "
                f"{request.z_right_min_limit_pin} {request.z_right_max_limit_pin}"
            )
        return (
            f"SET Z LIMITS {request.limit_switch_mode} {request.z_left_min_limit_pin} "
            f"{request.z_left_max_limit_pin} {request.z_right_min_limit_pin} {request.z_right_max_limit_pin}"
        )

    def _build_move_z_command(self, request: GantryZMoveRequest) -> str:
        return (
            f"MOVE Z {request.z_left_cm:.3f} {request.z_right_cm:.3f} "
            f"{_effective_move_rpm(request)} {_trapezoid_flag(request)} {_acceleration_rpm_per_s(request)} "
            f"{1 if request.on_the_fly_calibration else 0} {request.calibration_max_diff_steps}"
        )

    def _build_calibrate_z_command(self, request: GantryZCalibrationRequest) -> str:
        return (
            f"CALIBRATE Z {request.z_left_track_length_cm:.3f} "
            f"{request.z_right_track_length_cm:.3f} "
            f"{_effective_calibration_rpm(request)} {_trapezoid_flag(request)} {_acceleration_rpm_per_s(request)}"
        )

    def move_xy(self, request: GantryXYMoveRequest) -> GantryXYMoveResponse:
        port = self._selected_port(request.tool_port)
        baud_rate = request.baud_rate or self._baud_rate()
        pin_command = [self._build_xy_pin_command(request), self._build_z_pin_command(request)]
        limit_command = [self._build_xy_limit_command(request), self._build_z_limit_command(request)]
        move_command = self._build_move_xy_command(request)
        dominant_steps = max(
            abs(request.x_cm) * XY_STEPS_PER_CM,
            abs(request.y_cm) * XY_STEPS_PER_CM,
            abs(request.z_cm) * Z_STEPS_PER_CM,
        )
        pin_reply, limit_reply, move_reply = self._send_config_and_action(
            port=port,
            baud_rate=baud_rate,
            pin_command=pin_command,
            enable_command=self._build_xy_enable_command(request),
            limit_command=limit_command,
            action_command=move_command,
            action_prefix="OK MOVE XYZ",
            action_deadline=self._move_deadline(dominant_steps, _effective_move_rpm(request)),
        )

        return GantryXYMoveResponse(
            port=port,
            baud_rate=baud_rate,
            speed_profile=request.speed_profile,
            speed_rpm=_effective_move_rpm(request),
            trapezoidal_speed=request.trapezoidal_speed,
            acceleration_rpm_per_s=request.acceleration_rpm_per_s,
            on_the_fly_calibration=request.on_the_fly_calibration,
            calibration_max_diff_steps=request.calibration_max_diff_steps,
            pin_command_sent="\n".join(pin_command),
            pin_reply=pin_reply,
            pins_applied=True,
            limit_command_sent="\n".join(limit_command),
            limit_reply=limit_reply,
            limits_applied=True,
            move_command_sent=move_command,
            move_reply=move_reply,
            move_applied=True,
            target={"x_cm": request.x_cm, "y_cm": request.y_cm, "z_cm": request.z_cm},
            configured_pins={
                "x_step_pin": request.x_step_pin,
                "x_dir_pin": request.x_dir_pin,
                "y_step_pin": request.y_step_pin,
                "y_dir_pin": request.y_dir_pin,
                "z_step_pin": request.z_left_step_pin,
                "z_dir_pin": request.z_left_dir_pin,
            },
            configured_limits={
                "limit_switch_mode": request.limit_switch_mode,
                "x_min_limit_pin": request.x_min_limit_pin,
                "x_max_limit_pin": request.x_max_limit_pin,
                "y_min_limit_pin": request.y_min_limit_pin,
                "y_max_limit_pin": request.y_max_limit_pin,
                "z_min_limit_pin": request.z_left_min_limit_pin,
                "z_max_limit_pin": request.z_left_max_limit_pin,
                "speed_rpm": _effective_move_rpm(request),
                "trapezoidal_speed": request.trapezoidal_speed,
                "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
                "on_the_fly_calibration": request.on_the_fly_calibration,
                "calibration_max_diff_steps": request.calibration_max_diff_steps,
            },
        )

    def calibrate_xy(self, request: GantryXYCalibrationRequest) -> GantryXYCalibrationResponse:
        port = self._selected_port(request.tool_port)
        baud_rate = request.baud_rate or self._baud_rate()
        pin_command = self._build_xy_pin_command(request)
        limit_command = self._build_xy_limit_command(request)
        calibration_command = self._build_calibrate_xy_command(request)
        max_probe_steps = request.steps_per_rotation * request.max_probe_rotations
        pin_reply, limit_reply, calibration_reply = self._send_config_and_action(
            port=port,
            baud_rate=baud_rate,
            pin_command=pin_command,
            enable_command=self._build_xy_enable_command(request),
            limit_command=limit_command,
            action_command=calibration_command,
            action_prefix="OK CALIBRATE XY",
            action_deadline=self._move_deadline(
                max_probe_steps * 5.0,
                _effective_calibration_rpm(request),
                request.steps_per_rotation,
            ),
        )

        return GantryXYCalibrationResponse(
            port=port,
            baud_rate=baud_rate,
            calibration_speed_profile=request.calibration_speed_profile,
            speed_rpm=_effective_calibration_rpm(request),
            trapezoidal_speed=request.trapezoidal_speed,
            acceleration_rpm_per_s=request.acceleration_rpm_per_s,
            steps_per_rotation=request.steps_per_rotation,
            max_probe_rotations=request.max_probe_rotations,
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
                "speed_rpm": _effective_calibration_rpm(request),
                "trapezoidal_speed": request.trapezoidal_speed,
                "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
                "steps_per_rotation": request.steps_per_rotation,
                "max_probe_rotations": request.max_probe_rotations,
            },
        )

    def goto_xy(self, request: GantryGotoXYRequest) -> GantryGotoXYResponse:
        port = self._selected_port(request.tool_port)
        baud_rate = request.baud_rate or self._baud_rate()
        pin_command = self._build_xy_pin_command(request)
        limit_command = self._build_xy_limit_command(request)
        move_command = (
            f"GOTOXY {request.x_cm:.3f} {request.y_cm:.3f} {_effective_move_rpm(request)} "
            f"{_trapezoid_flag(request)} {_acceleration_rpm_per_s(request)}"
        )
        # Generous deadline: a single move can traverse the whole calibrated track.
        action_deadline = self._move_deadline(
            GANTRY_WORKSPACE_X_CM * XY_STEPS_PER_CM * 8.0,
            _effective_move_rpm(request),
        )
        pin_reply, limit_reply, move_reply = self._send_config_and_action(
            port=port,
            baud_rate=baud_rate,
            pin_command=pin_command,
            enable_command=self._build_xy_enable_command(request),
            limit_command=limit_command,
            action_command=move_command,
            action_prefix="OK MOVE XY",
            action_deadline=action_deadline,
        )

        return GantryGotoXYResponse(
            port=port,
            baud_rate=baud_rate,
            speed_profile=request.speed_profile,
            speed_rpm=_effective_move_rpm(request),
            trapezoidal_speed=request.trapezoidal_speed,
            acceleration_rpm_per_s=request.acceleration_rpm_per_s,
            target={"x_cm": request.x_cm, "y_cm": request.y_cm},
            pin_command_sent=pin_command,
            pin_reply=pin_reply,
            pins_applied=True,
            limit_command_sent=limit_command,
            limit_reply=limit_reply,
            limits_applied=True,
            move_command_sent=move_command,
            move_reply=move_reply,
            move_applied=True,
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
                "speed_rpm": _effective_move_rpm(request),
            },
        )

    def circle_xy(self, request: GantryCircleXYRequest) -> GantryCircleXYResponse:
        port = self._selected_port(request.tool_port)
        baud_rate = request.baud_rate or self._baud_rate()
        pin_command = self._build_xy_pin_command(request)
        limit_command = self._build_xy_limit_command(request)
        circle_command = (
            f"CIRCLEXY {request.center_x_cm:.3f} {request.center_y_cm:.3f} {request.radius_cm:.3f} "
            f"{_effective_move_rpm(request)} {_trapezoid_flag(request)} {_acceleration_rpm_per_s(request)}"
        )
        move_command = [circle_command for _ in range(request.repeat_count)]
        # Approach move plus the full circumference, with generous headroom.
        circle_steps = (2.0 * math.pi * request.radius_cm + GANTRY_WORKSPACE_X_CM * 2.0) * XY_STEPS_PER_CM * 8.0
        action_deadline = self._move_deadline(circle_steps, _effective_move_rpm(request))
        pin_reply, limit_reply, move_reply = self._send_config_and_action(
            port=port,
            baud_rate=baud_rate,
            pin_command=pin_command,
            enable_command=self._build_xy_enable_command(request),
            limit_command=limit_command,
            action_command=move_command,
            action_prefix="OK CIRCLE XY",
            action_deadline=action_deadline,
        )

        return GantryCircleXYResponse(
            port=port,
            baud_rate=baud_rate,
            speed_profile=request.speed_profile,
            speed_rpm=_effective_move_rpm(request),
            trapezoidal_speed=request.trapezoidal_speed,
            acceleration_rpm_per_s=request.acceleration_rpm_per_s,
            center={"x_cm": request.center_x_cm, "y_cm": request.center_y_cm},
            radius_cm=request.radius_cm,
            repeat_count=request.repeat_count,
            pin_command_sent=pin_command,
            pin_reply=pin_reply,
            pins_applied=True,
            limit_command_sent=limit_command,
            limit_reply=limit_reply,
            limits_applied=True,
            move_command_sent="\n".join(move_command),
            move_reply=move_reply,
            move_applied=True,
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
                "speed_rpm": _effective_move_rpm(request),
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
            action_deadline=self._move_deadline(dominant_steps, _effective_move_rpm(request)),
        )

        return GantryZMoveResponse(
            port=port,
            baud_rate=baud_rate,
            speed_profile=request.speed_profile,
            speed_rpm=_effective_move_rpm(request),
            trapezoidal_speed=request.trapezoidal_speed,
            acceleration_rpm_per_s=request.acceleration_rpm_per_s,
            on_the_fly_calibration=request.on_the_fly_calibration,
            calibration_max_diff_steps=request.calibration_max_diff_steps,
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
                "speed_rpm": _effective_move_rpm(request),
                "trapezoidal_speed": request.trapezoidal_speed,
                "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
                "on_the_fly_calibration": request.on_the_fly_calibration,
                "calibration_max_diff_steps": request.calibration_max_diff_steps,
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
                _effective_calibration_rpm(request),
            ),
        )

        return GantryZCalibrationResponse(
            port=port,
            baud_rate=baud_rate,
            calibration_speed_profile=request.calibration_speed_profile,
            speed_rpm=_effective_calibration_rpm(request),
            trapezoidal_speed=request.trapezoidal_speed,
            acceleration_rpm_per_s=request.acceleration_rpm_per_s,
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
                "speed_rpm": _effective_calibration_rpm(request),
                "trapezoidal_speed": request.trapezoidal_speed,
                "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
            },
        )


gantry_controller_service = GantryControllerService()
