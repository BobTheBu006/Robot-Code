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
# Homing bursts: small enough that even a slow/laggy serial round trip only
# lets the motor overtravel a fraction of a millimeter past a tripped switch.
FAST_PROBE_CHUNK_STEPS = 40
SLOW_PROBE_CHUNK_STEPS = 4
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
        if payload.get("calibrated"):
            self._calibrated = True
            self._left_track_length_cm = float(payload.get("left_track_length_cm", 60.0))
            self._right_track_length_cm = float(payload.get("right_track_length_cm", 60.0))
            self._left_steps = int(payload.get("left_steps", 0))
            self._right_steps = int(payload.get("right_steps", 0))

    def _invalidate_calibration(self) -> None:
        self._calibrated = False
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
        time.sleep(2.0)  # boot delay, matching the rest of this codebase's ESP32 handling
        self._drain_startup_output(serial_port)
        self._serial_port = serial_port
        self._serial_port_path = port
        return serial_port

    def _drain_startup_output(self, serial_port, *, quiet_seconds: float = 0.25, max_seconds: float = 3.0) -> None:
        deadline = time.monotonic() + max_seconds
        last_data_at = time.monotonic()
        while time.monotonic() < deadline:
            line = serial_port.readline().decode("utf-8", errors="replace").strip()
            if line:
                last_data_at = time.monotonic()
                continue
            if time.monotonic() - last_data_at >= quiet_seconds:
                break

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

        # Fast touch: chunked bursts toward the switch until it trips.
        travelled = 0
        while travelled < max_probe_steps:
            self._raise_if_stopped()
            if self._limit_active(gpio, limit_pin):
                break
            chunk = min(FAST_PROBE_CHUNK_STEPS, max_probe_steps - travelled)
            pulse(direction * chunk, fast_rpm)
            travelled += chunk
        else:
            if not self._limit_active(gpio, limit_pin):
                raise HybridZAxisError(f"Z {side} {'max' if direction > 0 else 'min'} limit switch was not hit during fast probe.")
        if not self._limit_active(gpio, limit_pin):
            raise HybridZAxisError(f"Z {side} {'max' if direction > 0 else 'min'} limit switch was not hit during fast probe.")

        # Back off one full rotation to release the switch.
        pulse(-direction * steps_per_rotation, fast_rpm)

        # Slow re-touch: small bursts, capped at two rotations of travel.
        slow_cap = steps_per_rotation * 2
        travelled = 0
        while travelled < slow_cap:
            self._raise_if_stopped()
            if self._limit_active(gpio, limit_pin):
                break
            chunk = min(SLOW_PROBE_CHUNK_STEPS, slow_cap - travelled)
            pulse(direction * chunk, SLOW_HOMING_RPM)
            travelled += chunk
        if not self._limit_active(gpio, limit_pin):
            raise HybridZAxisError(f"Z {side} {'max' if direction > 0 else 'min'} limit switch was not hit during slow probe.")

        return self._left_steps if side == "left" else self._right_steps

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
        port = request.tool_port or "/dev/ttyUSB0"
        baud_rate = request.baud_rate or 115200
        gpio, gpio_error = load_gpio_backend()
        if gpio is None:
            raise HybridZAxisError(f"Compatible Raspberry Pi GPIO backend is not available: {gpio_error}")

        with self._lock:
            self._invalidate_calibration()
            self._setup_limit_gpio(gpio, pins)
            try:
                serial_port = self._open_serial(port, baud_rate)
                self._send_pins(serial_port, pins)

                steps_per_rotation = request.steps_per_rotation if hasattr(request, "steps_per_rotation") else 800
                max_probe_steps = steps_per_rotation * 120

                self._left_steps = 0
                left_home_steps = self._probe_side(
                    serial_port, gpio, pins, "left", -1, max_probe_steps, steps_per_rotation,
                    request.speed_rpm, request.trapezoidal_speed, request.acceleration_rpm_per_s,
                )
                self._left_steps = 0
                left_max_steps = self._probe_side(
                    serial_port, gpio, pins, "left", 1, max_probe_steps, steps_per_rotation,
                    request.speed_rpm, request.trapezoidal_speed, request.acceleration_rpm_per_s,
                )

                self._right_steps = 0
                self._probe_side(
                    serial_port, gpio, pins, "right", -1, max_probe_steps, steps_per_rotation,
                    request.speed_rpm, request.trapezoidal_speed, request.acceleration_rpm_per_s,
                )
                self._right_steps = 0
                right_max_steps = self._probe_side(
                    serial_port, gpio, pins, "right", 1, max_probe_steps, steps_per_rotation,
                    request.speed_rpm, request.trapezoidal_speed, request.acceleration_rpm_per_s,
                )

                if left_max_steps <= 0 or right_max_steps <= 0:
                    raise HybridZAxisError("Z max homing measured zero travel from Z min; check the limit switches.")

                self._steps_per_cm = max(
                    left_max_steps / request.z_left_track_length_cm,
                    right_max_steps / request.z_right_track_length_cm,
                )
                self._left_track_length_cm = left_max_steps / self._steps_per_cm
                self._right_track_length_cm = right_max_steps / self._steps_per_cm
                self._limit_buffer_cm = request.limit_buffer_cm

                # Homing deliberately leaves both carriages resting on their max
                # switches. Walk back by one buffer on each side so calibration
                # never finishes with a limit pressed - otherwise the very next
                # move refuses (a limit switch is active) before it can even start.
                backoff_steps = round(request.limit_buffer_cm * self._steps_per_cm)
                if backoff_steps > 0:
                    self._send_step(
                        serial_port, -backoff_steps, -backoff_steps, request.speed_rpm,
                        request.trapezoidal_speed, request.acceleration_rpm_per_s, steps_per_rotation,
                    )

                self._calibrated = True
                self._save_state()
            finally:
                self._cleanup_limit_gpio(gpio, pins)

        return {
            "calibrated": True,
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
            raise HybridZAxisError("Z axis is not calibrated. Run Calibrate Z Axis before moving.")

        pins = self._pins_from_request(request)
        port = request.tool_port or "/dev/ttyUSB0"
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
