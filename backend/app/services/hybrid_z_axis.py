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

from app.models.gantry import GantryZCalibrationRequest, GantryZMoveRequest
from app.services.gpio_backend import load_gpio_backend

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
        self._stop_requested = Event()
        self._load_state()

    # ---- state persistence, mirroring gantry-state.json's pattern ----
    def _state_path(self) -> Path:
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
        self._stop_requested.clear()

    def _raise_if_stopped(self) -> None:
        if self._stop_requested.is_set():
            raise HybridZAxisStoppedError("Z axis motion stopped by emergency stop.")

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
        reply, completed = self._send(serial_port, command, terminal_prefixes=("OK STEP Z", "ERR "), deadline_seconds=deadline)
        if not completed:
            raise HybridZAxisError("Timed out waiting for the Z-axis ESP32 to finish a step burst.")
        if reply and "ERR STOP" in reply.upper():
            raise HybridZAxisStoppedError("Z axis motion stopped by emergency stop.")
        if not reply or "OK STEP Z" not in reply.upper():
            raise HybridZAxisError(f"ESP32 rejected a Z step command: {reply}")
        self._left_steps += left_delta
        self._right_steps += right_delta

    def _seek_switch(
        self, serial_port, gpio: Any, side: str, direction: int, limit_pin: int,
        max_steps: int, rpm: float, trapezoidal: bool, acceleration_rpm_per_s: float,
        steps_per_rotation: int,
    ) -> tuple[int, bool]:
        """Drive one side toward a switch in a single continuous move, sending
        STOP the instant this Pi's own GPIO sees the switch trip.

        The firmware checks for STOP between every step, so overtravel is one
        step period of serial latency rather than a whole burst - and because
        it is one uninterrupted move, the axis travels smoothly instead of
        hopping between round trips. Returns (steps actually travelled,
        whether the switch tripped).
        """
        if max_steps <= 0:
            return 0, self._limit_active(gpio, limit_pin)

        signed = direction * max_steps
        left = signed if side == "left" else 0
        right = signed if side == "right" else 0
        command = f"STEP Z {left} {right} {int(rpm)} {1 if trapezoidal else 0} {int(acceleration_rpm_per_s)}"

        serial_port.reset_input_buffer()
        serial_port.reset_output_buffer()
        serial_port.write((command + "\n").encode("utf-8"))
        serial_port.flush()

        steps_per_second = max(1.0, rpm * steps_per_rotation / 60.0)
        deadline = time.monotonic() + (max_steps / steps_per_second) * 2.0 + 10.0
        stop_sent = False
        buffer = b""

        while time.monotonic() < deadline:
            if self._stop_requested.is_set():
                if not stop_sent:
                    serial_port.write(b"STOP\n")
                    serial_port.flush()
                    stop_sent = True
                raise HybridZAxisStoppedError("Z axis motion stopped by emergency stop.")

            if not stop_sent and self._limit_active(gpio, limit_pin):
                serial_port.write(b"STOP\n")
                serial_port.flush()
                stop_sent = True

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
                        travelled = abs(travelled_left if side == "left" else travelled_right)
                        return travelled, self._limit_active(gpio, limit_pin)

        raise HybridZAxisError(
            f"Timed out waiting for the Z {side} axis to finish seeking its limit switch."
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

    def _assert_limits_clear(self, gpio: Any, pins: _ZPinPlan) -> None:
        active = [name for name, pin in (
            ("left_min", pins.left_min_limit_pin), ("left_max", pins.left_max_limit_pin),
            ("right_min", pins.right_min_limit_pin), ("right_max", pins.right_max_limit_pin),
        ) if self._limit_active(gpio, pin)]
        if active:
            raise HybridZAxisError(
                "Z limit switch active before move; emergency stop required: " + ", ".join(active)
            )

    # ---- three-pass homing for one side, chunked and Pi-polled ----
    def _probe_side(
        self, serial_port, gpio: Any, pins: _ZPinPlan, side: str, direction: int,
        max_probe_steps: int, steps_per_rotation: int, fast_rpm: float,
        trapezoidal: bool, acceleration_rpm_per_s: float,
    ) -> int:
        limit_pin = {
            ("left", 1): pins.left_max_limit_pin, ("left", -1): pins.left_min_limit_pin,
            ("right", 1): pins.right_max_limit_pin, ("right", -1): pins.right_min_limit_pin,
        }[(side, direction)]

        def pulse(steps: int, rpm: float) -> None:
            left = steps if side == "left" else 0
            right = steps if side == "right" else 0
            self._send_step(serial_port, left, right, rpm, trapezoidal, acceleration_rpm_per_s, steps_per_rotation)

        end = "max" if direction > 0 else "min"

        # Fast touch: one continuous move toward the switch, stopped the
        # instant the Pi sees it trip.
        self._raise_if_stopped()
        travelled, tripped = self._seek_switch(
            serial_port, gpio, side, direction, limit_pin, max_probe_steps,
            fast_rpm, trapezoidal, acceleration_rpm_per_s, steps_per_rotation,
        )
        if not tripped:
            raise HybridZAxisError(
                f"Z {side} {end} limit switch (Pi GPIO {limit_pin}) never tripped after {travelled} steps "
                f"toward it. Either the Z {side} motor is not reaching its switch (check that its driver is "
                f"powered and enabled, its step/dir wiring, and that the axis is free to move), or the axis "
                f"needs more travel than the probe allowed - raise 'Steps per cm (estimate)' if this machine "
                f"has a finer drive than the estimate."
            )

        # Back off one full rotation to release the switch.
        pulse(-direction * steps_per_rotation, fast_rpm)

        # Slow re-touch at homing speed for a repeatable, precise contact.
        self._raise_if_stopped()
        _, tripped = self._seek_switch(
            serial_port, gpio, side, direction, limit_pin, steps_per_rotation * 2,
            SLOW_HOMING_RPM, trapezoidal, acceleration_rpm_per_s, steps_per_rotation,
        )
        if not tripped:
            raise HybridZAxisError(
                f"Z {side} {end} limit switch (Pi GPIO {limit_pin}) tripped on the fast probe but not on the "
                "slow re-touch. The switch may be intermittent, or the axis slipped during back-off."
            )

        return self._left_steps if side == "left" else self._right_steps

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
    def calibrate_z(self, context: dict, request: GantryZCalibrationRequest) -> dict:
        self._raise_if_stopped()
        pins = self._pins_from_request(request)
        port = self._resolve_port(context, request.tool_port)
        baud_rate = request.baud_rate or 115200
        gpio, gpio_error = load_gpio_backend()
        if gpio is None:
            raise HybridZAxisError(f"Compatible Raspberry Pi GPIO backend is not available: {gpio_error}")

        sides = ("left", "right") if request.axes == "both" else (request.axes,)

        with self._lock:
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
                for side in sides:
                    self._set_axis_steps(side, 0)
                    self._probe_side(
                        serial_port, gpio, pins, side, -1, max_probe_steps, steps_per_rotation,
                        request.speed_rpm, request.trapezoidal_speed, request.acceleration_rpm_per_s,
                    )
                    self._set_axis_steps(side, 0)
                    measured_steps[side] = self._probe_side(
                        serial_port, gpio, pins, side, 1, max_probe_steps, steps_per_rotation,
                        request.speed_rpm, request.trapezoidal_speed, request.acceleration_rpm_per_s,
                    )
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

        with self._lock:
            self._setup_limit_gpio(gpio, pins)
            try:
                self._assert_limits_clear(gpio, pins)
                serial_port = self._open_serial(port, baud_rate)
                self._send_pins(serial_port, pins)

                target_left_steps = round(request.z_left_cm * self._steps_per_cm)
                target_right_steps = round(request.z_right_cm * self._steps_per_cm)
                delta_left = target_left_steps - self._left_steps
                delta_right = target_right_steps - self._right_steps

                self._send_step(
                    serial_port, delta_left, delta_right, request.speed_rpm,
                    request.trapezoidal_speed, request.acceleration_rpm_per_s,
                    getattr(request, "steps_per_rotation", 800),
                )
                self._save_state()
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
