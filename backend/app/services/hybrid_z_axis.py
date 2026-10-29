"""Dual Z-axis control split across two controllers.

The two Z stepper motors are wired to a dedicated ESP32 ("Double Z axis and
pumps"), which pulses them open-loop on request (STEP Z) and has no
electrical connection to any limit switch. The four limit switches are wired
directly to Raspberry Pi GPIO. The Pi is the brain: it tracks position,
decides when to stop, and never trusts the ESP32 to know where a switch is -
homing pulses steps in short bursts and checks its own GPIO between bursts,
which bounds how far a motor can overtravel past a switch to one burst's
worth of steps even under full serial round-trip latency, instead of relying
on an interrupt that a busy ESP32 loop might answer late.
"""

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Any

from app.core.safety import PRIORITY_SERIAL, CallableActor, safety_controller
from app.models.gantry import GantryZCalibrationRequest, GantryZMoveRequest
from app.services.gpio_backend import load_gpio_backend
from app.services.motor_power import Z_PUMP_DOMAIN, motor_power_service, powered_motors

STATE_VERSION = 1
DEFAULT_STEPS_PER_CM = 100.0
# Homing bursts. The limit switches are on the Pi but the motors are on the
# ESP32, so a burst cannot be interrupted mid-flight: the burst size is the
# worst-case overtravel past a switch. The coarse pass only has to get close
# (the slow re-touch below is what actually measures the switch position), so
# it uses a bigger burst to keep the number of serial round trips sane - at
# 40 steps a full-length probe was thousands of round trips and looked like a
# hang. The slow pass stays tiny for precision.
FAST_PROBE_CHUNK_STEPS = 200
SLOW_PROBE_CHUNK_STEPS = 4
# Safety margin on the probe budget, over the track length the user entered.
# Generous enough to absorb a wrong steps-per-cm estimate, small enough that a
# side which never reaches its switch (unpowered driver, broken wiring) fails
# in seconds with a clear message instead of grinding for minutes.
PROBE_BUDGET_MARGIN = 2.0
SLOW_HOMING_RPM = 10.0
# Zero sits on the min switch's trip point, so a move to (nearly) 0 ends on
# the switch by design. Within this distance of the bottom, the min switch
# tripping means "arrived", not "something is wrong".
MIN_SWITCH_ARRIVAL_CM = 0.2
# A limit switch counts as pressed only when this many reads in a row say so.
# Watching both Z switches while both motors run, one noisy read on the left
# max wire held the left motor short of its switch while the right drove into
# its end; a real press holds for far longer than these reads take.
SWITCH_CONFIRM_READS = 4
SWITCH_CONFIRM_INTERVAL_S = 0.0005
# Homing up together, both sides start on their min switch, so once one side
# reaches its max the other is at most (difference in track length + this)
# away. Taking longer means that motor is not moving - a stalled stepper
# keeps receiving steps without turning - so everything stops instead.
FOLLOW_MARGIN_CM = 3.0
FOLLOW_SLACK_S = 1.0


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


class HybridZAxisError(RuntimeError):
    pass


class HybridZAxisStoppedError(HybridZAxisError):
    """Motion was aborted by an emergency stop."""


@dataclass
class _ZPinPlan:
    left_step_pin: int
    left_dir_pin: int
    right_step_pin: int
    right_dir_pin: int
    left_min_limit_pin: int
    left_max_limit_pin: int
    right_min_limit_pin: int
    right_max_limit_pin: int

    def limit_pins(self) -> list[int]:
        return [self.left_min_limit_pin, self.left_max_limit_pin, self.right_min_limit_pin, self.right_max_limit_pin]


class _NullPowerHold:
    """Stand-in for a board with no enable line wired."""

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None


class HybridZAxisService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._left_steps = 0
        self._right_steps = 0
        self._left_track_length_cm = 60.0
        self._right_track_length_cm = 60.0
        self._steps_per_cm = DEFAULT_STEPS_PER_CM
        self._calibrated = False
        # Tracked per side so one-sided bring-up calibration stays honest:
        # moves need both sides established, not just whichever was last run.
        self._left_calibrated = False
        self._right_calibrated = False
        self._limit_buffer_cm = 0.5
        self._serial_port_path: str | None = None
        self._serial_port: Any = None
        # Whether the open port's firmware understands "STOP <source>",
        # asked once per opened port (a reflash reopens it).
        self._stop_sources_port: Any = None
        self._stop_sources = False
        # Shared by reference with every other motion driver - see
        # app/core/safety.py. One latch, not one per service.
        self._stop_requested = safety_controller.motion_blocked
        self._load_state()

    # ---- state persistence, mirroring gantry-state.json's pattern ----
    def _state_path(self) -> Path:
        # Overridable so tests get an isolated file - see the matching note in
        # raspberry_gantry._state_path.
        override = os.getenv("ROBOT_Z_GANTRY_STATE_FILE")
        if override:
            return Path(override)
        return Path(__file__).resolve().parents[3] / "z-gantry-state.json"

    def _save_state(self) -> None:
        payload = {
            "version": STATE_VERSION,
            "calibrated": self._calibrated,
            "left_calibrated": self._left_calibrated,
            "right_calibrated": self._right_calibrated,
            "steps_per_cm": self._steps_per_cm,
            "limit_buffer_cm": self._limit_buffer_cm,
            "left_track_length_cm": self._left_track_length_cm,
            "right_track_length_cm": self._right_track_length_cm,
            "left_steps": self._left_steps,
            "right_steps": self._right_steps,
        }
        try:
            temp_path = self._state_path().with_suffix(".json.tmp")
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            temp_path.replace(self._state_path())
        except OSError:
            pass

    def _load_state(self) -> None:
        path = self._state_path()
        if not path.exists():
            return
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return
        if payload.get("version") != STATE_VERSION:
            return
        steps_per_cm = payload.get("steps_per_cm")
        if isinstance(steps_per_cm, (int, float)) and steps_per_cm > 0:
            self._steps_per_cm = float(steps_per_cm)
        buffer_cm = payload.get("limit_buffer_cm")
        if isinstance(buffer_cm, (int, float)) and buffer_cm >= 0:
            self._limit_buffer_cm = float(buffer_cm)
        # Per-side flags fall back to the old single flag so a state file
        # written before one-sided calibration existed still loads correctly.
        legacy_calibrated = bool(payload.get("calibrated"))
        self._left_calibrated = bool(payload.get("left_calibrated", legacy_calibrated))
        self._right_calibrated = bool(payload.get("right_calibrated", legacy_calibrated))
        self._calibrated = self._left_calibrated and self._right_calibrated
        if self._left_calibrated or self._right_calibrated:
            self._left_track_length_cm = float(payload.get("left_track_length_cm", 60.0))
            self._right_track_length_cm = float(payload.get("right_track_length_cm", 60.0))
            self._left_steps = int(payload.get("left_steps", 0))
            self._right_steps = int(payload.get("right_steps", 0))

    def _invalidate_calibration(self, sides: tuple[str, ...] = ("left", "right")) -> None:
        """Drop calibration for the sides about to be re-homed. A side that is
        not being touched keeps the calibration it already had."""
        if "left" in sides:
            self._left_calibrated = False
        if "right" in sides:
            self._right_calibrated = False
        self._calibrated = self._left_calibrated and self._right_calibrated
        self._save_state()

    # ---- emergency stop ----
    def emergency_stop(self) -> dict[str, object]:
        self._stop_requested.set()
        if self._serial_port is not None:
            try:
                self._serial_port.write(b"STOP\n")
                self._serial_port.flush()
            except Exception:
                pass
        return {
            "ok": True,
            "tool": "hybrid-z-axis",
            "tool_port": self._serial_port_path,
            "message": "Z axis motion stop requested.",
        }

    def rearm(self) -> None:
        """Deprecated: only the SafetyController may clear the shared latch."""
        return None

    def _raise_if_stopped(self) -> None:
        if self._stop_requested.is_set():
            raise HybridZAxisStoppedError(f"Z axis motion is blocked. {self._blocked_reason()}")

    def _blocked_reason(self) -> str:
        """Explain the block in terms the operator can act on.

        The stop flag is shared with the safety controller, so it stays set
        while a physical fact is unconfirmed - long after the stop itself. Just
        saying "stopped by emergency stop" then sends the operator looking for a
        limit switch that is not pressed."""
        try:
            from app.core.safety import safety_controller

            return safety_controller.blocked_reason()
        except Exception:
            return "Clear the emergency stop once the machine is safe."

    # ---- serial connection to the Z-axis ESP32 ----
    def _resolve_port(self, context: dict, requested_port: str | None) -> str:
        """Pick the port to talk to the Z controller on.

        Linux renumbers /dev/ttyUSB* by plug order, so the port recorded in
        the Hardware Map goes stale as soon as the board is reconnected. The
        board that owns the Z motors is looked up instead and resolved by its
        USB serial number, falling back to the recorded port when there is no
        workspace to identify it from.
        """
        from app.services.esp32_builder import esp32_builder_service

        hardware_map = context.get("hardware_map")
        board_id = None
        if isinstance(hardware_map, dict):
            for device in hardware_map.get("devices", []):
                if isinstance(device, dict) and device.get("id") in ("z-left-motor", "z-right-motor"):
                    board_id = device.get("board_id")
                    if board_id:
                        break

        if board_id:
            resolved = esp32_builder_service.resolve_board_port(board_id)
            if resolved:
                return resolved

        if requested_port:
            return requested_port
        raise HybridZAxisError(
            "No serial port is configured for the Z controller, and it could not be found by USB serial number."
        )

    def _load_serial_module(self):
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise HybridZAxisError(
                "pyserial is not installed. Install backend requirements to enable ESP32 communication."
            ) from exc
        return serial

    def _open_serial(self, port: str, baud_rate: int):
        if self._serial_port is not None and self._serial_port_path == port:
            try:
                if getattr(self._serial_port, "is_open", False):
                    return self._serial_port
            except Exception:
                pass

        serial_module = self._load_serial_module()
        serial_port = serial_module.Serial(port, baud_rate, timeout=1.0)

        # Opening the port toggles DTR/RTS, which resets the ESP32. Drive the
        # reset deliberately and wait the board out, then throw away every
        # byte of boot output. Reading it as a command reply is what produced
        # replacement characters instead of an acknowledgement - the ROM's
        # early boot chatter is not valid UTF-8 at this baud rate.
        try:
            serial_port.dtr = False
            time.sleep(0.1)
            serial_port.dtr = True
        except Exception:
            pass
        time.sleep(2.5)
        self._drain_startup_output(serial_port)

        # Confirm the firmware is actually listening before trusting any
        # reply. A board still mid-boot answers with garbage; PING/PONG is
        # the cheapest proof that we are in sync.
        if not self._handshake(serial_port):
            try:
                serial_port.close()
            except Exception:
                pass
            raise HybridZAxisError(
                f"The Z controller on {port} did not respond to PING. It may still be booting, "
                "running the wrong firmware, or another program may be holding the port."
            )

        self._serial_port = serial_port
        self._serial_port_path = port
        return serial_port

    def _drain_startup_output(self, serial_port, *, quiet_seconds: float = 0.3, max_seconds: float = 4.0) -> None:
        """Discard everything the board emits after reset, bytes not lines:
        boot chatter arrives without newlines and can sit in the buffer as a
        partial line that a later readline() would splice onto a real reply."""
        deadline = time.monotonic() + max_seconds
        last_data_at = time.monotonic()
        while time.monotonic() < deadline:
            waiting = serial_port.in_waiting
            if waiting:
                serial_port.read(waiting)
                last_data_at = time.monotonic()
                continue
            if time.monotonic() - last_data_at >= quiet_seconds:
                break
            time.sleep(0.02)
        serial_port.reset_input_buffer()

    def _handshake(self, serial_port, attempts: int = 4) -> bool:
        for _ in range(attempts):
            serial_port.reset_input_buffer()
            serial_port.reset_output_buffer()
            serial_port.write(b"PING\n")
            serial_port.flush()
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                line = serial_port.readline().decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if "PONG" in line.upper():
                    serial_port.reset_input_buffer()
                    return True
        return False

    def _send(self, serial_port, command: str, *, terminal_prefixes: tuple[str, ...], deadline_seconds: float) -> tuple[str | None, bool]:
        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
        serial_port.write((command + "\n").encode("utf-8"))
        serial_port.flush()

        replies: list[str] = []
        deadline = time.monotonic() + deadline_seconds
        normalized_prefixes = tuple(prefix.upper() for prefix in terminal_prefixes)
        while time.monotonic() < deadline:
            self._raise_if_stopped()
            line = serial_port.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            replies.append(line)
            if any(line.upper().startswith(prefix) for prefix in normalized_prefixes):
                return "\n".join(replies), True
        if not replies:
            return None, False
        return "\n".join(replies), False

    def _send_pins(self, serial_port, pins: _ZPinPlan) -> None:
        command = f"SET Z PINS {pins.left_step_pin} {pins.left_dir_pin} {pins.right_step_pin} {pins.right_dir_pin}"
        reply, completed = self._send(serial_port, command, terminal_prefixes=("OK",), deadline_seconds=5.0)
        if not completed or not reply or "OK" not in reply.upper():
            raise HybridZAxisError(f"ESP32 did not acknowledge Z pin configuration: {reply}")

    def _send_step(
        self, serial_port, left_delta: int, right_delta: int, rpm: float,
        trapezoidal: bool, acceleration_rpm_per_s: float, steps_per_rotation: int,
    ) -> None:
        """One open-loop STEP Z burst. Deadline sized generously off the
        larger side's step count so a burst can never time out mid-flight."""
        max_steps = max(abs(left_delta), abs(right_delta))
        if max_steps == 0:
            return
        steps_per_second = max(1.0, rpm * steps_per_rotation / 60.0)
        deadline = max(3.0, (max_steps / steps_per_second) * 2.0 + 2.0)
        command = f"STEP Z {left_delta} {right_delta} {int(rpm)} {1 if trapezoidal else 0} {int(acceleration_rpm_per_s)}"
        # "OK STOP STEP Z" has to be listed too: an aborted burst answers with
        # that, and it does not start with "OK STEP Z", so without it the reply
        # was never recognised as terminal and the move timed out instead.
        reply, completed = self._send(
            serial_port, command,
            terminal_prefixes=("OK STOP STEP Z", "OK STEP Z", "ERR "),
            deadline_seconds=deadline,
        )
        if not completed:
            raise HybridZAxisError("Timed out waiting for the Z-axis ESP32 to finish a step burst.")
        upper = (reply or "").upper()
        if "ERR STOP" in upper:
            raise HybridZAxisStoppedError(f"Z axis motion is blocked. {self._blocked_reason()}")
        if "STEP Z" not in upper or "OK" not in upper:
            raise HybridZAxisError(f"ESP32 rejected a Z step command: {reply}")

        # Adopt what the firmware says actually happened, not what was asked
        # for. Every pulse it issued was counted, so after an abort the position
        # is still exactly known - and an emergency stop must not cost the
        # calibration. Falls back to the commanded delta only when the reply
        # cannot be read, which is the best guess available at that point.
        done_left, done_right = self._parse_step_done(reply, left_delta, right_delta)
        self._left_steps += done_left
        self._right_steps += done_right

        if "OK STOP STEP Z" in upper:
            self._save_state()
            raise HybridZAxisStoppedError(
                f"Z axis motion stopped after {abs(done_left)} left / {abs(done_right)} right steps. "
                f"{self._blocked_reason()}"
            )

    def _assert_sides_calibrated(self, delta_left: int, delta_right: int) -> None:
        """Refuse to drive a side whose position was never measured.

        Track lengths and the step counter default to plausible-looking
        numbers, so an uncalibrated axis will happily accept a target and drive
        against a workspace it has no knowledge of - into a hard stop, or short
        of one. This is the difference between "calibrated to 60 cm" and "never
        homed, assuming 60 cm", which the range check alone cannot tell apart.

        Only the sides actually being moved are checked. Commanding a side to
        the position it already holds is how a caller moves one axis while
        leaving the other alone, and that needs no calibration because it needs
        no motion.
        """
        uncalibrated = [
            side
            for side, delta, calibrated in (
                ("left", delta_left, self._left_calibrated),
                ("right", delta_right, self._right_calibrated),
            )
            if delta != 0 and not calibrated
        ]
        if uncalibrated:
            sides = " and ".join(uncalibrated)
            raise HybridZAxisError(
                f"The Z {sides} axis has not been calibrated, so its position is unknown and a "
                f"move could drive into a limit. Run Calibrate Z Axis first."
            )

    def _parse_step_done(self, reply: str | None, left_delta: int, right_delta: int) -> tuple[int, int]:
        """Read the signed step counts out of an OK [STOP] STEP Z reply."""
        for line in reversed((reply or "").splitlines()):
            if "STEP Z" not in line.upper():
                continue
            tail = line.upper().split("STEP Z", 1)[1].split()
            try:
                return int(tail[0]), int(tail[1])
            except (IndexError, ValueError):
                continue
        return left_delta, right_delta

    def _switch_pressed(self, gpio: Any, pin: int) -> bool:
        """A debounced read: pressed only if every one of a few quick reads
        says so. An unpressed switch costs a single read."""
        for attempt in range(SWITCH_CONFIRM_READS):
            if not self._limit_active(gpio, pin):
                return False
            if attempt + 1 < SWITCH_CONFIRM_READS:
                time.sleep(SWITCH_CONFIRM_INTERVAL_S)
        return True

    def _homing_log(self, message: str) -> None:
        """Append one line to logs/z-homing.log: what each seek asked for,
        which switch tripped, which stop went out, what the board replied.
        The record to read when homing misbehaves on the machine."""
        try:
            path = Path(os.getenv("ROBOT_Z_HOMING_LOG") or Path(__file__).resolve().parents[3] / "logs" / "z-homing.log")
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} {message}\n")
        except OSError:
            pass

    def _supports_stop_sources(self, serial_port) -> bool:
        """Whether the board understands "STOP <source>" (firmware with
        FEATURES?). Older firmware ignores a sourced stop mid-move, which
        would leave a motor driving into its switch, so a single motor is
        only ever stopped by source when this says yes."""
        if self._stop_sources_port is serial_port:
            return self._stop_sources
        reply, _completed = self._send(
            serial_port, "FEATURES?", terminal_prefixes=("OK FEATURES", "ERR"), deadline_seconds=2.0,
        )
        self._stop_sources_port = serial_port
        self._stop_sources = bool(reply) and "STOP_SOURCE" in reply.upper()
        return self._stop_sources

    def _step_watching_limits(
        self, serial_port, gpio: Any, pins: _ZPinPlan, left_delta: int, right_delta: int, rpm: float,
        trapezoidal: bool, acceleration_rpm_per_s: float, steps_per_rotation: int, *, stop_sources: bool,
    ) -> list[tuple[str, str]]:
        """One STEP Z burst with the Pi watching, for each moving side, the
        switch it is heading toward. A switch that trips stops its own motor
        at once ("STOP Z_LEFT_MIN"; the other side finishes its move), or
        both motors on firmware without stop sources. Positions adopt what
        the firmware reports it actually did. Returns the (side, end)
        switches that tripped."""
        deltas = {"left": left_delta, "right": right_delta}
        switch_pins = {
            ("left", "min"): pins.left_min_limit_pin, ("left", "max"): pins.left_max_limit_pin,
            ("right", "min"): pins.right_min_limit_pin, ("right", "max"): pins.right_max_limit_pin,
        }
        watched = {
            side: ("max" if delta > 0 else "min") for side, delta in deltas.items() if delta != 0
        }
        if not watched:
            return []

        command = f"STEP Z {left_delta} {right_delta} {int(rpm)} {1 if trapezoidal else 0} {int(acceleration_rpm_per_s)}"
        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
        serial_port.write((command + "\n").encode("utf-8"))
        serial_port.flush()

        max_steps = max(abs(left_delta), abs(right_delta))
        steps_per_second = max(1.0, rpm * steps_per_rotation / 60.0)
        deadline = time.monotonic() + max(3.0, (max_steps / steps_per_second) * 2.0 + 2.0)
        tripped: list[tuple[str, str]] = []
        held: set[str] = set()
        stop_sent = False
        buffer = b""

        while time.monotonic() < deadline:
            if self._stop_requested.is_set():
                if not stop_sent:
                    serial_port.write(b"STOP\n")
                    serial_port.flush()
                    stop_sent = True
                raise HybridZAxisStoppedError(f"Z axis motion is blocked. {self._blocked_reason()}")

            if not stop_sent:
                for side, end in watched.items():
                    if side in held or not self._switch_pressed(gpio, switch_pins[(side, end)]):
                        continue
                    held.add(side)
                    tripped.append((side, end))
                    if stop_sources and len(held) < len(watched):
                        serial_port.write(f"STOP Z_{side.upper()}_{end.upper()}\n".encode("utf-8"))
                    else:
                        serial_port.write(b"STOP\n")
                        stop_sent = True
                    serial_port.flush()

            waiting = serial_port.in_waiting
            if waiting:
                buffer += serial_port.read(waiting)
                if b"\n" in buffer:
                    for raw_line in buffer.split(b"\n"):
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        upper = line.upper()
                        if upper.startswith("ERR"):
                            raise HybridZAxisError(f"ESP32 rejected a Z step command: {line}")
                        if not upper.startswith(("OK STEP Z", "OK STOP STEP Z")):
                            continue
                        parts = line.split()
                        self._left_steps += int(parts[-2])
                        self._right_steps += int(parts[-1])
                        return tripped

        raise HybridZAxisError("Timed out waiting for the Z-axis ESP32 to finish a step burst.")

    def _seek_switches(
        self, serial_port, gpio: Any, limit_pins: dict[str, int], direction: int,
        max_steps: int, rpm: float, trapezoidal: bool, acceleration_rpm_per_s: float,
        steps_per_rotation: int, follow_steps: int | None = None,
    ) -> dict[str, tuple[int, bool]]:
        """Drive the given sides toward their switches in one continuous move,
        stopping each the instant this Pi's own GPIO sees its switch trip.

        The firmware checks for a stop between every step, so overtravel is
        one step period of serial latency rather than a whole burst. With two
        sides moving, the first switch is stopped by its source ("STOP
        Z_LEFT_MIN"): the firmware holds only that motor and the other carries
        on in the same move. The last side moving gets a plain STOP, which
        ends the move. Two sides need firmware with stop sources - see
        _supports_stop_sources. A side already on its switch does not move.
        With `follow_steps`, once one side has stopped the others get that
        many steps' worth of time to reach their own switch; then everything
        stops and the seek fails, naming the side that never arrived.
        Returns per side (steps travelled, whether the switch tripped).
        """
        end = "MAX" if direction > 0 else "MIN"
        result: dict[str, tuple[int, bool]] = {}
        moving = []
        for side, pin in limit_pins.items():
            if self._switch_pressed(gpio, pin):
                result[side] = (0, True)
                self._homing_log(f"seek {end}: {side} already on its switch (GPIO {pin}), not moved")
            else:
                moving.append(side)
        if not moving or max_steps <= 0:
            for side in moving:
                result[side] = (0, self._switch_pressed(gpio, limit_pins[side]))
            return result

        signed = direction * max_steps
        left = signed if "left" in moving else 0
        right = signed if "right" in moving else 0
        command = f"STEP Z {left} {right} {int(rpm)} {1 if trapezoidal else 0} {int(acceleration_rpm_per_s)}"
        self._homing_log(f"seek {end}: {command} watching " + ", ".join(f"{side} GPIO {limit_pins[side]}" for side in moving))

        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
        serial_port.write((command + "\n").encode("utf-8"))
        serial_port.flush()

        steps_per_second = max(1.0, rpm * steps_per_rotation / 60.0)
        deadline = time.monotonic() + (max_steps / steps_per_second) * 2.0 + 10.0
        started = time.monotonic()
        held: set[str] = set()
        stop_sent = False
        follow_deadline: float | None = None
        buffer = b""

        while time.monotonic() < deadline:
            if self._stop_requested.is_set():
                if not stop_sent:
                    serial_port.write(b"STOP\n")
                    serial_port.flush()
                    stop_sent = True
                raise HybridZAxisStoppedError(f"Z axis motion is blocked. {self._blocked_reason()}")

            if follow_deadline is not None and not stop_sent and time.monotonic() > follow_deadline:
                serial_port.write(b"STOP\n")
                serial_port.flush()
                stop_sent = True
                late = [side for side in moving if side not in held]
                first = next(iter(held))
                margin_cm = follow_steps / max(self._steps_per_cm, 1.0)
                self._homing_log(f"seek {end}: {', '.join(late)} did not follow within {margin_cm:.1f} cm -> sent STOP")
                raise HybridZAxisError(
                    f"Z {first} reached its {end.lower()} switch, but Z {' and '.join(late)} did not reach "
                    f"its own within about {margin_cm:.1f} cm more travel, so both were stopped. That motor "
                    "has probably stalled (common when both sides climb together at high speed - try a lower "
                    "speed), or its switch is not being reached. Calibrate that side alone to check."
                )

            if not stop_sent:
                for side in moving:
                    if side in held or not self._switch_pressed(gpio, limit_pins[side]):
                        continue
                    held.add(side)
                    if len(held) == len(moving):
                        stop = "STOP"
                        stop_sent = True
                    else:
                        stop = f"STOP Z_{side.upper()}_{end}"
                        if follow_steps is not None and follow_deadline is None:
                            follow_deadline = time.monotonic() + follow_steps / steps_per_second + FOLLOW_SLACK_S
                    serial_port.write((stop + "\n").encode("utf-8"))
                    serial_port.flush()
                    self._homing_log(
                        f"seek {end}: {side} switch GPIO {limit_pins[side]} pressed after "
                        f"{time.monotonic() - started:.2f}s -> sent {stop}"
                    )

            waiting = serial_port.in_waiting
            if waiting:
                buffer += serial_port.read(waiting)
                if b"\n" in buffer:
                    for raw_line in buffer.split(b"\n"):
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.upper().startswith(("OK STEP Z", "OK STOP STEP Z")):
                            continue
                        parts = line.split()
                        travelled_left = int(parts[-2])
                        travelled_right = int(parts[-1])
                        self._left_steps += travelled_left
                        self._right_steps += travelled_right
                        for side in moving:
                            travelled = abs(travelled_left if side == "left" else travelled_right)
                            result[side] = (travelled, self._switch_pressed(gpio, limit_pins[side]))
                        self._homing_log(
                            f"seek {end}: board replied '{line}'; switches now "
                            + ", ".join(f"{side} {'pressed' if result[side][1] else 'NOT pressed'}" for side in moving)
                        )
                        return result

        raise HybridZAxisError(
            f"Timed out waiting for the Z {' and '.join(moving)} axis to finish seeking its limit switch."
        )

    # ---- Pi-side limit switch reading ----
    def _setup_limit_gpio(self, gpio: Any, pins: _ZPinPlan) -> None:
        gpio.setwarnings(False)
        gpio.setmode(gpio.BCM)
        pull = gpio.PUD_UP if _bool_env("ROBOT_GPIO_LIMIT_ACTIVE_LOW", True) else gpio.PUD_DOWN
        for pin in pins.limit_pins():
            gpio.setup(pin, gpio.IN, pull_up_down=pull)

    def _cleanup_limit_gpio(self, gpio: Any, pins: _ZPinPlan) -> None:
        gpio.cleanup(pins.limit_pins())

    def _limit_active(self, gpio: Any, pin: int) -> bool:
        active_low = _bool_env("ROBOT_GPIO_LIMIT_ACTIVE_LOW", True)
        value = gpio.input(pin)
        return value == gpio.LOW if active_low else value == gpio.HIGH

    def _raise_for_unexpected_switches(self, tripped: list[tuple[str, str]], request: GantryZMoveRequest) -> None:
        """A limit switch inside the calibrated range means that side's
        position is not what the machine believes - steps were lost, or the
        switch moved. That side's calibration is dropped, so nothing moves it
        again on a guessed position. Arriving at the bottom is not a fault:
        zero sits on the min switch."""
        faults = []
        for side, end in tripped:
            target_cm = request.z_left_cm if side == "left" else request.z_right_cm
            if end == "min" and target_cm <= MIN_SWITCH_ARRIVAL_CM:
                continue
            steps = self._left_steps if side == "left" else self._right_steps
            faults.append((side, end, steps / self._steps_per_cm, target_cm))
        if not faults:
            return
        self._invalidate_calibration(tuple(side for side, *_rest in faults))
        details = "; ".join(
            f"the {side} {end} switch tripped at {at_cm:.2f} cm on the way to {target_cm:g} cm"
            for side, end, at_cm, target_cm in faults
        )
        raise HybridZAxisError(
            f"Z move stopped: {details}. That motor was stopped there and its calibration is no longer "
            "trusted - run Calibrate Z Axis before moving it again."
        )

    def _deltas_respecting_switches(
        self, gpio: Any, pins: _ZPinPlan, delta_left: int, delta_right: int,
        target_left_cm: float, target_right_cm: float,
    ) -> tuple[int, int]:
        """A pressed switch only matters for a move *into* it. Zero sits on
        the min switch's trip point, so a bed at (or a hair above) 0 cm has
        its min switch pressed: asked to go to the bottom, it is already
        there and is left alone. A move down to anywhere clearly above the
        switch, or up into a pressed max switch, is refused - the recorded
        position cannot be right."""
        adjusted = {"left": delta_left, "right": delta_right}
        targets = {"left": target_left_cm, "right": target_right_cm}
        blocked = []
        for side, min_pin, max_pin in (
            ("left", pins.left_min_limit_pin, pins.left_max_limit_pin),
            ("right", pins.right_min_limit_pin, pins.right_max_limit_pin),
        ):
            delta = adjusted[side]
            if delta < 0 and self._switch_pressed(gpio, min_pin):
                if targets[side] <= MIN_SWITCH_ARRIVAL_CM:
                    adjusted[side] = 0
                else:
                    blocked.append(f"{side} is on its min switch and the move goes down to {targets[side]:g} cm")
            if delta > 0 and self._switch_pressed(gpio, max_pin):
                blocked.append(f"{side} is on its max switch and the move goes up")
        if blocked:
            raise HybridZAxisError("Z move refused: " + "; ".join(blocked) + ".")
        return adjusted["left"], adjusted["right"]

    def _assert_limits_clear(self, gpio: Any, pins: _ZPinPlan) -> None:
        active = [name for name, pin in (
            ("left_min", pins.left_min_limit_pin), ("left_max", pins.left_max_limit_pin),
            ("right_min", pins.right_min_limit_pin), ("right_max", pins.right_max_limit_pin),
        ) if self._limit_active(gpio, pin)]
        if active:
            raise HybridZAxisError(
                "Z limit switch active before move; emergency stop required: " + ", ".join(active)
            )

    # ---- three-pass homing, one side or both together, Pi-polled ----
    def _probe_sides(
        self, serial_port, gpio: Any, pins: _ZPinPlan, sides: tuple[str, ...], direction: int,
        max_probe_steps: int, steps_per_rotation: int, fast_rpm: float,
        trapezoidal: bool, acceleration_rpm_per_s: float, follow_steps: int | None = None,
    ) -> dict[str, int]:
        limit_pins = {
            side: {
                ("left", 1): pins.left_max_limit_pin, ("left", -1): pins.left_min_limit_pin,
                ("right", 1): pins.right_max_limit_pin, ("right", -1): pins.right_min_limit_pin,
            }[(side, direction)]
            for side in sides
        }
        end = "max" if direction > 0 else "min"

        # Fast touch: one continuous move toward the switches, each side
        # stopped the instant the Pi sees its own switch trip.
        self._raise_if_stopped()
        fast = self._seek_switches(
            serial_port, gpio, limit_pins, direction, max_probe_steps,
            fast_rpm, trapezoidal, acceleration_rpm_per_s, steps_per_rotation,
            follow_steps=follow_steps,
        )
        for side in sides:
            travelled, tripped = fast[side]
            if not tripped:
                raise HybridZAxisError(
                    f"Z {side} {end} limit switch (Pi GPIO {limit_pins[side]}) never tripped after {travelled} steps "
                    f"toward it. Either the Z {side} motor is not reaching its switch (check that its driver is "
                    f"powered and enabled, its step/dir wiring, and that the axis is free to move), or the axis "
                    f"needs more travel than the probe allowed - raise 'Steps per cm (estimate)' if this machine "
                    f"has a finer drive than the estimate."
                )

        # Back off one full rotation to release the switches.
        backoff = -direction * steps_per_rotation
        self._send_step(
            serial_port, backoff if "left" in sides else 0, backoff if "right" in sides else 0,
            fast_rpm, trapezoidal, acceleration_rpm_per_s, steps_per_rotation,
        )

        # Slow re-touch at homing speed for a repeatable, precise contact.
        self._raise_if_stopped()
        slow = self._seek_switches(
            serial_port, gpio, limit_pins, direction, steps_per_rotation * 2,
            SLOW_HOMING_RPM, trapezoidal, acceleration_rpm_per_s, steps_per_rotation,
        )
        for side in sides:
            if not slow[side][1]:
                raise HybridZAxisError(
                    f"Z {side} {end} limit switch (Pi GPIO {limit_pins[side]}) tripped on the fast probe but not on "
                    "the slow re-touch. The switch may be intermittent, or the axis slipped during back-off."
                )

        return {side: self._left_steps if side == "left" else self._right_steps for side in sides}

    def _set_axis_steps(self, side: str, value: int) -> None:
        if side == "left":
            self._left_steps = value
        else:
            self._right_steps = value

    def _pins_from_request(self, request: GantryZCalibrationRequest | GantryZMoveRequest) -> _ZPinPlan:
        return _ZPinPlan(
            left_step_pin=request.z_left_step_pin,
            left_dir_pin=request.z_left_dir_pin,
            right_step_pin=request.z_right_step_pin,
            right_dir_pin=request.z_right_dir_pin,
            left_min_limit_pin=request.z_left_min_limit_pin,
            left_max_limit_pin=request.z_left_max_limit_pin,
            right_min_limit_pin=request.z_right_min_limit_pin,
            right_max_limit_pin=request.z_right_max_limit_pin,
        )

    # ---- public API ----

    # ---- shared driver-enable line (GPIO 17 on this board) ----

    def enable_pin_from_hardware_map(self, context: dict | None) -> int | None:
        """Find the shared driver-enable pin for this board.

        Read from the Hardware Map rather than a manifest input so it applies
        to every function on this controller - Z moves, calibration and the
        pumps - without each manifest having to declare it.
        """
        if context is None:
            return None
        hardware_map = context.get("hardware_map")
        devices = hardware_map.get("devices") if isinstance(hardware_map, dict) else None
        for device in devices or []:
            if not isinstance(device, dict) or device.get("board_id") != "controller-ykkl80":
                continue
            for pin in device.get("pins") or []:
                if isinstance(pin, dict) and pin.get("function_input_key") == "motor_enable_pin":
                    gpio = str(pin.get("gpio") or "").strip()
                    if gpio.lstrip("-").isdigit() and int(gpio) >= 0:
                        return int(gpio)
        return None

    def register_power_domain(self, port: str, enable_pin: int) -> None:
        """Teach the power service to switch this board's drivers over serial.

        The enable line is an ESP32 pin, so unlike the CoreXY drivers the Pi
        cannot toggle it directly - it has to be asked for down the same serial
        connection everything else on this board uses.
        """
        def apply(on: bool) -> None:
            serial_port = self._open_serial(port, 115200)
            self._send(
                serial_port, f"SET MOTOR ENABLE PIN {enable_pin}",
                terminal_prefixes=("OK", "ERR"), deadline_seconds=5.0,
            )
            reply, completed = self._send(
                serial_port, f"MOTOR ENABLE {1 if on else 0}",
                terminal_prefixes=("OK", "ERR"), deadline_seconds=5.0,
            )
            if not completed or not reply or "OK" not in reply.upper():
                raise HybridZAxisError(f"The controller did not acknowledge MOTOR ENABLE: {reply}")

        motor_power_service.register(
            Z_PUMP_DOMAIN,
            f"Z axes and peristaltic pumps (ESP32 GPIO {enable_pin})",
            apply,
        )

    def _hold_power(self, context: dict, port: str):
        """Power the drivers for the duration of a move, if an enable is wired.

        Returns something usable with `with`. On a board with no enable line
        this is a no-op, which is how it behaved before the line existed.
        """
        enable_pin = self.enable_pin_from_hardware_map(context)
        if enable_pin is None:
            return _NullPowerHold()
        self.register_power_domain(port, enable_pin)
        return powered_motors(Z_PUMP_DOMAIN)

    def calibrate_z(self, context: dict, request: GantryZCalibrationRequest) -> dict:
        self._raise_if_stopped()
        pins = self._pins_from_request(request)
        port = self._resolve_port(context, request.tool_port)
        baud_rate = request.baud_rate or 115200
        gpio, gpio_error = load_gpio_backend()
        if gpio is None:
            raise HybridZAxisError(f"Compatible Raspberry Pi GPIO backend is not available: {gpio_error}")

        sides = ("left", "right") if request.axes == "both" else (request.axes,)

        # Power the drivers before probing, and let go afterwards. Release only
        # starts the linger timer, so a calibration followed by a move does not
        # power-cycle in between.
        with self._hold_power(context, port), self._lock:
            self._invalidate_calibration(sides)
            self._setup_limit_gpio(gpio, pins)
            try:
                serial_port = self._open_serial(port, baud_rate)
                self._send_pins(serial_port, pins)

                steps_per_rotation = request.steps_per_rotation if hasattr(request, "steps_per_rotation") else 800
                # Budget the probe against the track length the operator
                # actually entered rather than an arbitrary rotation count: a
                # side that never reaches its switch then fails in seconds
                # naming that side, instead of pulsing a dead axis for minutes.
                longest_track_cm = max(request.z_left_track_length_cm, request.z_right_track_length_cm)
                # Prefer a previously measured steps-per-cm; before the first
                # successful calibration there is nothing measured, so fall
                # back to the operator's estimate rather than a belt-drive
                # default that badly under-budgets a fine lead screw.
                budget_steps_per_cm = (
                    self._steps_per_cm if self._calibrated else request.steps_per_cm_estimate
                )
                max_probe_steps = max(
                    steps_per_rotation,
                    round(longest_track_cm * budget_steps_per_cm * PROBE_BUDGET_MARGIN),
                )

                # Home each selected side: down to its min switch (that becomes
                # zero), then up to its max switch to measure the real travel.
                measured_steps: dict[str, int] = {}
                track_length_cm = {
                    "left": request.z_left_track_length_cm,
                    "right": request.z_right_track_length_cm,
                }
                # Both sides home together when the board can stop each motor
                # on its own (stop sources); otherwise one side after the other.
                homed_together = len(sides) == 2 and self._supports_stop_sources(serial_port)
                passes = [sides] if homed_together else [(side,) for side in sides]
                for group in passes:
                    for side in group:
                        self._set_axis_steps(side, 0)
                    self._probe_sides(
                        serial_port, gpio, pins, group, -1, max_probe_steps, steps_per_rotation,
                        request.speed_rpm, request.trapezoidal_speed, request.acceleration_rpm_per_s,
                    )
                    for side in group:
                        self._set_axis_steps(side, 0)
                    # Both sides start this climb on their min switch, so they
                    # should reach their max within the track-length difference.
                    follow_steps = None
                    if len(group) == 2:
                        follow_cm = abs(request.z_left_track_length_cm - request.z_right_track_length_cm) + FOLLOW_MARGIN_CM
                        follow_steps = round(follow_cm * budget_steps_per_cm)
                    measured_steps.update(self._probe_sides(
                        serial_port, gpio, pins, group, 1, max_probe_steps, steps_per_rotation,
                        request.speed_rpm, request.trapezoidal_speed, request.acceleration_rpm_per_s,
                        follow_steps=follow_steps,
                    ))
                for side in sides:
                    if measured_steps[side] <= 0:
                        raise HybridZAxisError(
                            f"Z {side} measured zero travel between its min and max switches; "
                            "check that both switches are wired to the right pins."
                        )

                # Steps-per-cm is a property of the drive train, so it is
                # measured from the sides actually homed in this run and left
                # untouched when a side is skipped.
                self._steps_per_cm = max(
                    measured_steps[side] / track_length_cm[side] for side in sides
                )
                for side in sides:
                    length_cm = measured_steps[side] / self._steps_per_cm
                    if side == "left":
                        self._left_track_length_cm = length_cm
                    else:
                        self._right_track_length_cm = length_cm
                self._limit_buffer_cm = request.limit_buffer_cm

                # Homing deliberately leaves each carriage resting on its max
                # switch. Walk back by one buffer so calibration never finishes
                # with a limit pressed - otherwise the very next move refuses
                # (a limit switch is active) before it can even start. Only the
                # sides actually homed are moved.
                backoff_steps = round(request.limit_buffer_cm * self._steps_per_cm)
                if backoff_steps > 0:
                    self._send_step(
                        serial_port,
                        -backoff_steps if "left" in sides else 0,
                        -backoff_steps if "right" in sides else 0,
                        request.speed_rpm,
                        request.trapezoidal_speed, request.acceleration_rpm_per_s, steps_per_rotation,
                    )

                for side in sides:
                    if side == "left":
                        self._left_calibrated = True
                    else:
                        self._right_calibrated = True
                self._calibrated = self._left_calibrated and self._right_calibrated
                self._save_state()
            finally:
                self._cleanup_limit_gpio(gpio, pins)

        return {
            "calibrated": self._calibrated,
            "calibrated_axes": list(sides),
            "homed_together": homed_together,
            "left_calibrated": self._left_calibrated,
            "right_calibrated": self._right_calibrated,
            "steps_per_cm": self._steps_per_cm,
            "workspace": {
                "z_left_track_length_cm": self._left_track_length_cm,
                "z_right_track_length_cm": self._right_track_length_cm,
            },
            "tool_port": port,
            "configured_pins": {
                "z_left_step_pin": pins.left_step_pin, "z_left_dir_pin": pins.left_dir_pin,
                "z_right_step_pin": pins.right_step_pin, "z_right_dir_pin": pins.right_dir_pin,
            },
            "configured_limits": {
                "z_left_min_limit_pin": pins.left_min_limit_pin, "z_left_max_limit_pin": pins.left_max_limit_pin,
                "z_right_min_limit_pin": pins.right_min_limit_pin, "z_right_max_limit_pin": pins.right_max_limit_pin,
            },
            "mode": context.get("mode"),
        }

    def move_z(self, context: dict, request: GantryZMoveRequest) -> dict:
        self._raise_if_stopped()
        if not self._calibrated:
            missing = [
                name for name, done in (("left", self._left_calibrated), ("right", self._right_calibrated))
                if not done
            ]
            raise HybridZAxisError(
                f"Z axis is not calibrated ({', '.join(missing)} not homed). "
                "Run Calibrate Z Axis for both sides before moving."
            )

        pins = self._pins_from_request(request)
        port = self._resolve_port(context, request.tool_port)
        baud_rate = request.baud_rate or 115200
        # The usable range is inset from the max switch by the calibrated
        # buffer (the position calibration parks at), matching the buffer
        # convention used by the XY gantry.
        usable_left_max = self._left_track_length_cm - self._limit_buffer_cm
        usable_right_max = self._right_track_length_cm - self._limit_buffer_cm
        if not 0.0 <= request.z_left_cm <= usable_left_max:
            raise HybridZAxisError(f"z_left_cm must be between 0 and the usable max of {usable_left_max:g} cm.")
        if not 0.0 <= request.z_right_cm <= usable_right_max:
            raise HybridZAxisError(f"z_right_cm must be between 0 and the usable max of {usable_right_max:g} cm.")

        gpio, gpio_error = load_gpio_backend()
        if gpio is None:
            raise HybridZAxisError(f"Compatible Raspberry Pi GPIO backend is not available: {gpio_error}")

        with self._hold_power(context, port), self._lock:
            self._setup_limit_gpio(gpio, pins)
            try:
                target_left_steps = round(request.z_left_cm * self._steps_per_cm)
                target_right_steps = round(request.z_right_cm * self._steps_per_cm)
                delta_left = target_left_steps - self._left_steps
                delta_right = target_right_steps - self._right_steps
                delta_left, delta_right = self._deltas_respecting_switches(
                    gpio, pins, delta_left, delta_right, request.z_left_cm, request.z_right_cm,
                )

                serial_port = self._open_serial(port, baud_rate)
                self._send_pins(serial_port, pins)

                self._assert_sides_calibrated(delta_left, delta_right)

                tripped = self._step_watching_limits(
                    serial_port, gpio, pins, delta_left, delta_right, request.speed_rpm,
                    request.trapezoidal_speed, request.acceleration_rpm_per_s,
                    getattr(request, "steps_per_rotation", 800),
                    stop_sources=self._supports_stop_sources(serial_port),
                )
                self._save_state()
                self._raise_for_unexpected_switches(tripped, request)
            finally:
                self._cleanup_limit_gpio(gpio, pins)

        return {
            "target": {"z_left_cm": request.z_left_cm, "z_right_cm": request.z_right_cm},
            "tool_port": port,
            "speed_rpm": request.speed_rpm,
            "trapezoidal_speed": request.trapezoidal_speed,
            "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
            "configured_pins": {
                "z_left_step_pin": pins.left_step_pin, "z_left_dir_pin": pins.left_dir_pin,
                "z_right_step_pin": pins.right_step_pin, "z_right_dir_pin": pins.right_dir_pin,
            },
            "configured_limits": {
                "z_left_min_limit_pin": pins.left_min_limit_pin, "z_left_max_limit_pin": pins.left_max_limit_pin,
                "z_right_min_limit_pin": pins.right_min_limit_pin, "z_right_max_limit_pin": pins.right_max_limit_pin,
            },
            "mode": context.get("mode"),
        }


hybrid_z_axis_service = HybridZAxisService()

safety_controller.register_actor(
    CallableActor("hybrid-z-axis", hybrid_z_axis_service.emergency_stop),
    priority=PRIORITY_SERIAL,
    description="Z axis controller (GPIO flag plus STOP over serial)",
)
