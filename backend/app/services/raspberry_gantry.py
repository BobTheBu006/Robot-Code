import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import Any

# Bumped whenever the meaning of the saved calibration changes, so a record
# written under older semantics is discarded instead of misread. Matches the
# ESP32 firmware's GANTRY_STATE_VERSION scheme.
GANTRY_STATE_VERSION = 2

# Slow re-touch speed for the three-pass homing, matching XY_SLOW_HOMING_RPM in
# the ESP32 firmware so both execution paths home identically.
XY_SLOW_HOMING_RPM = 10.0

from app.models.gantry import (
    GANTRY_WORKSPACE_X_CM,
    GANTRY_WORKSPACE_Y_CM,
    GantryCircleXYRequest,
    GantryRepeatabilityLimitResult,
    GantryRepeatabilityTestRequest,
    GantryRepeatabilityTrial,
    GantryXYCalibrationRequest,
    GantryXYMoveRequest,
)
from app.core.safety import PRIORITY_FLAG, CallableActor, safety_controller
from app.services.gpio_backend import load_gpio_backend
from app.services.motor_power import GANTRY_XY_DOMAIN, motor_power_service, powered_motors

RASPBERRY_BOARD_ID = "raspberry-pi"
# A Y-max switch is optional: the gantry homes against Y-min, so a machine with
# only a Y-min switch is a valid setup and must not be treated as "not on the Pi".
REQUIRED_XY_DEVICE_IDS = {
    "x-axis-motor",
    "y-axis-motor",
    "x-min-limit-switch",
    "x-max-limit-switch",
    "y-min-limit-switch",
}
OPTIONAL_XY_DEVICE_IDS = {
    "y-max-limit-switch",
}
XY_DEVICE_IDS = REQUIRED_XY_DEVICE_IDS | OPTIONAL_XY_DEVICE_IDS

# How long the CoreXY drivers stay energised after a move finishes. Holding
# position matters more here than saving the current: belts back-drive.
GANTRY_IDLE_HOLD_SECONDS = 300.0

# How far past the believed X position a re-home will hunt for the switch.
# Generous next to real step loss, tight enough that a genuinely lost carriage
# fails instead of grinding the length of the rail.
_X_REHOME_MARGIN_CM = 5.0

# How far a re-home will keep nudging before deciding the X min switch is not
# going to release at all.
_X_REHOME_RELEASE_CM = 1.0

DEFAULT_STEPS_PER_CM = 100.0
# STEP pulse width. Drivers only need ~1-2us; the width also floors the step
# interval (interval >= 2x pulse), which caps the step rate at 5000/s - a
# ceiling this Python loop can still time accurately. Stall protection does
# not come from this cap but from the trapezoidal ramp in _move_corexy_steps:
# commanding a stepper from standstill straight at full speed stalls it, and
# stalls hit the two CoreXY motors unevenly, which bends commanded straight
# lines into diagonals - observed on this machine before the ramp existed.
DEFAULT_STEP_PULSE_SECONDS = float(os.getenv("ROBOT_GPIO_STEP_PULSE_SECONDS", "0.0001"))
# Ramp floor, matching the firmware's rpmForTrapezoidIteration lower clamp:
# every ramped move starts and ends at this speed, which is well inside the
# motors' pull-in range, so a move can never begin above what a stationary
# rotor can follow.
MIN_RAMP_RPM = 10.0
# Settle time between writing the DIR pins and the first STEP edge, mirroring
# the firmware's delayMicroseconds(20) (drivers latch direction on the step
# edge and need the level stable first).
DIR_SETTLE_SECONDS = 0.0002
# time.sleep()/Event.wait() only resolve to ~50-100us and overshoot badly below
# that, so short waits spin on perf_counter instead. Waits longer than this
# sleep first (to yield the CPU) and spin only for the tail.
STEP_SPIN_THRESHOLD_SECONDS = 0.002
DEFAULT_BACKOFF_CM = 1.0


@dataclass
class _GPIOPinPlan:
    a_step_pin: int
    a_dir_pin: int
    b_step_pin: int
    b_dir_pin: int
    x_min_limit_pin: int
    x_max_limit_pin: int
    y_min_limit_pin: int
    # None when the machine has no Y-max switch; that end is then unguarded.
    y_max_limit_pin: int | None = None
    # One line enabling both CoreXY drivers. None on a machine that has the
    # drivers permanently enabled, which is what this was before.
    enable_pin: int | None = None

    def limit_pins(self) -> list[int]:
        pins = [self.x_min_limit_pin, self.x_max_limit_pin, self.y_min_limit_pin]
        if self.y_max_limit_pin is not None:
            pins.append(self.y_max_limit_pin)
        return pins

    def named_limit_pins(self) -> list[tuple[str, int]]:
        named = [("x_min", self.x_min_limit_pin), ("x_max", self.x_max_limit_pin), ("y_min", self.y_min_limit_pin)]
        if self.y_max_limit_pin is not None:
            named.append(("y_max", self.y_max_limit_pin))
        return named


@dataclass
class _GPIOExecution:
    status: str
    message: str
    simulated: bool
    unavailable_reason: str | None = None


def _hardware_map_devices(context: dict) -> list[dict]:
    hardware_map = context.get("hardware_map")
    if not isinstance(hardware_map, dict):
        return []

    devices = hardware_map.get("devices")
    return devices if isinstance(devices, list) else []


def _enable_pin_from_hardware_map(context: dict | None) -> int | None:
    """Find the shared CoreXY driver-enable pin, if one is wired.

    Read from the Hardware Map rather than from the request because two of the
    gantry manifests are generated from ESP32 workspace blueprints - a new input
    added to those manifests is overwritten the next time they regenerate. The
    Hardware Map is the thing an operator actually edits, and it is already
    passed to every gantry function, so resolving here means the enable line
    works for all of them without a manifest change anywhere.
    """
    if context is None:
        return None

    for device in _hardware_map_devices(context):
        if not isinstance(device, dict) or not _device_is_on_raspberry_pi(device):
            continue
        for pin in device.get("pins") or []:
            if not isinstance(pin, dict):
                continue
            if pin.get("function_input_key") != "gantry_enable_pin":
                continue
            gpio = str(pin.get("gpio") or "").strip()
            if gpio.lstrip("-").isdigit() and int(gpio) >= 0:
                return int(gpio)
    return None


class RaspberryGantryConfigError(RuntimeError):
    """The XY hardware is partly mapped to the Raspberry Pi, but not usably so."""


def _device_is_on_raspberry_pi(device: dict | None) -> bool:
    return bool(
        device
        and device.get("board_id") == RASPBERRY_BOARD_ID
        and device.get("enabled") is not False
    )


def xy_hardware_is_on_raspberry_pi(context: dict) -> bool:
    """True when the XY gantry should be driven from Raspberry Pi GPIO.

    Raises instead of returning False when the XY hardware is *partly* on the Pi.
    Falling back to the ESP32 serial path in that case would send gantry motion
    commands to whatever else is wired to that board (e.g. the syringe motors),
    so a half-finished mapping has to fail loudly rather than move the wrong axis.
    """
    devices_by_id = {
        device.get("id"): device
        for device in _hardware_map_devices(context)
        if isinstance(device, dict)
    }

    missing = sorted(
        device_id
        for device_id in REQUIRED_XY_DEVICE_IDS
        if not _device_is_on_raspberry_pi(devices_by_id.get(device_id))
    )
    if not missing:
        return True

    on_pi = sorted(
        device_id
        for device_id in XY_DEVICE_IDS
        if _device_is_on_raspberry_pi(devices_by_id.get(device_id))
    )
    if on_pi:
        raise RaspberryGantryConfigError(
            "The XY gantry is only partly mapped to the Raspberry Pi, so it cannot be driven safely. "
            f"On the Raspberry Pi: {', '.join(on_pi)}. "
            f"Still missing (must be on the '{RASPBERRY_BOARD_ID}' board and enabled): {', '.join(missing)}. "
            "Fix the Hardware Map before running gantry motion - the previous behaviour fell back to the "
            "ESP32 controller and moved whichever motors were wired to it."
        )

    return False


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        # A typo in an environment variable must not change how long the
        # motors hold; fall back to the considered default.
        return default


class GantryStoppedError(RuntimeError):
    """Motion was aborted by an emergency stop."""


class RaspberryGantryGPIOService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._x_cm = 0.0
        self._y_cm = 0.0
        self._x_track_length_cm = GANTRY_WORKSPACE_X_CM
        self._y_track_length_cm = GANTRY_WORKSPACE_Y_CM
        self._calibrated = False
        # Physical position in steps, origin at the min-switch slow touch of the
        # last calibration. This mirrors the ESP32 firmware's currentX/YSteps: the
        # steps are the source of truth and user cm are derived from them.
        self._x_steps = 0
        self._y_steps = 0
        self._y_known = False
        # Steps-per-cm measured by the last X calibration (track length / counted
        # steps), like the firmware's xStepsPerCm. None until first measured; the
        # ROBOT_GPIO_XY_STEPS_PER_CM estimate is only a pre-calibration fallback.
        self._measured_steps_per_cm: float | None = None
        # Steps-per-rotation the machine was calibrated with; later moves use it
        # to turn RPM into a step rate, like the firmware's stepsPerRevolution.
        self._steps_per_rotation: int | None = None
        self._limit_buffer_cm = 0.5
        # Signed pulses issued to each motor by the last _move_corexy_steps call,
        # including runs stopped early by a limit; probes measure travel from it.
        self._last_a_steps = 0
        self._last_b_steps = 0
        # The process-wide safety latch, shared by reference rather than owned
        # here. The stepping loop checks it every step so motion aborts
        # mid-move rather than running to completion, and because it is the
        # same Event the serial drivers and the E-Stop route use, there is one
        # answer to "is the machine allowed to move" instead of five.
        # Never cleared by motion itself - only by an explicit operator rearm.
        self._stop_requested = safety_controller.motion_blocked
        self._load_state()

    def _state_path(self) -> Path:
        # Overridable so tests get an isolated file. Pointing at the repo-root
        # state unconditionally made the suite order-dependent: a test that
        # moved the gantry rewrote the calibration another test then read.
        override = os.getenv("ROBOT_GANTRY_STATE_FILE")
        if override:
            return Path(override)
        return Path(__file__).resolve().parents[3] / "gantry-state.json"

    def _save_state(self) -> None:
        """Persist calibration the way the firmware persists to NVS.

        Steps-per-cm and the buffer survive an invalidated calibration on
        purpose: they describe the belts and the workspace mapping, not where
        the carriage happens to be.
        """
        payload = {
            "version": GANTRY_STATE_VERSION,
            "calibrated": self._calibrated,
            "steps_per_cm": self._measured_steps_per_cm,
            "steps_per_rotation": self._steps_per_rotation,
            "limit_buffer_cm": self._limit_buffer_cm,
            "x_track_length_cm": self._x_track_length_cm,
            "y_track_length_cm": self._y_track_length_cm,
            "x_steps": self._x_steps,
            "y_steps": self._y_steps,
            "y_known": self._y_known,
        }
        try:
            temp_path = self._state_path().with_suffix(".json.tmp")
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
            temp_path.replace(self._state_path())
        except OSError:
            # Persistence is a convenience; never fail motion over it.
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
        # A record written under a different meaning of the fields is discarded
        # rather than misread, mirroring the firmware's versioned NVS state.
        if payload.get("version") != GANTRY_STATE_VERSION:
            return
        steps_per_cm = payload.get("steps_per_cm")
        if isinstance(steps_per_cm, (int, float)) and steps_per_cm > 0:
            self._measured_steps_per_cm = float(steps_per_cm)
        steps_per_rotation = payload.get("steps_per_rotation")
        if isinstance(steps_per_rotation, int) and steps_per_rotation > 0:
            self._steps_per_rotation = steps_per_rotation
        buffer_cm = payload.get("limit_buffer_cm")
        if isinstance(buffer_cm, (int, float)) and buffer_cm >= 0:
            self._limit_buffer_cm = float(buffer_cm)
        if payload.get("calibrated"):
            self._calibrated = True
            self._x_track_length_cm = float(payload.get("x_track_length_cm", GANTRY_WORKSPACE_X_CM))
            self._y_track_length_cm = float(payload.get("y_track_length_cm", GANTRY_WORKSPACE_Y_CM))
            self._x_steps = int(payload.get("x_steps", 0))
            self._y_steps = int(payload.get("y_steps", 0))
            self._y_known = bool(payload.get("y_known", False))

    def _effective_steps_per_cm(self) -> float:
        return self._measured_steps_per_cm if self._measured_steps_per_cm else self._steps_per_cm()

    def _invalidate_calibration(self) -> None:
        """Forget the stored calibration so moves refuse rather than run against
        a position that is no longer true. Steps-per-cm is kept."""
        self._calibrated = False
        self._y_known = False
        self._save_state()

    def emergency_stop(self) -> dict[str, object]:
        """Abort any in-progress GPIO motion. Safe to call when nothing is moving."""
        self._stop_requested.set()
        return {
            "ok": True,
            "tool": "raspberry-pi-gantry",
            "tool_port": None,
            "message": "Raspberry Pi GPIO gantry motion stop requested.",
        }

    def rearm(self) -> None:
        """Deprecated: the latch is process-wide and only the SafetyController
        may clear it, after the operator has confirmed any uncertain physical
        state. Kept so older call sites do not break, but it no longer clears
        anything on its own - that silent clearing is what made E-Stop
        advisory."""
        return None

    def stop_is_requested(self) -> bool:
        return self._stop_requested.is_set()

    def _raise_if_stopped(self) -> None:
        if self._stop_requested.is_set():
            raise GantryStoppedError("Gantry motion stopped by emergency stop.")

    def _wait_until(self, deadline: float) -> None:
        """Wait until perf_counter reaches deadline, aborting on emergency stop.

        Sleeps for the bulk of long waits so the CPU is not pinned, then spins
        for the remainder: step intervals are tens to hundreds of microseconds,
        which time.sleep() cannot resolve without large overshoot.
        """
        remaining = deadline - time.perf_counter()
        if remaining > STEP_SPIN_THRESHOLD_SECONDS:
            if self._stop_requested.wait(remaining - STEP_SPIN_THRESHOLD_SECONDS):
                raise GantryStoppedError("Gantry motion stopped by emergency stop.")

        while time.perf_counter() < deadline:
            if self._stop_requested.is_set():
                raise GantryStoppedError("Gantry motion stopped by emergency stop.")

    def calibrate_xy(self, context: dict, request: GantryXYCalibrationRequest) -> dict:
        # A latched emergency stop blocks new motion until the next run rearms it.
        self._raise_if_stopped()
        pins = self._pins_from_request(request, context)
        execution = self._execution_mode()

        if execution.simulated:
            self._adopt_calibration(request, self._effective_steps_per_cm())
            return self._calibration_result(context, request, pins, execution)

        gpio, _ = self._gpio_module()
        if gpio is None:
            raise RuntimeError("Compatible Raspberry Pi GPIO backend became unavailable during calibration.")
        with self._lock:
            try:
                self._setup_gpio(gpio, pins)
            except Exception as exc:
                execution = self._gpio_unavailable_execution(str(exc))
                self._adopt_calibration(request, self._effective_steps_per_cm())
                return self._calibration_result(context, request, pins, execution)
            try:
                # Everything below moves the carriage, so a run that fails part
                # way through leaves the stored position wrong. Drop the old
                # calibration first; moves refuse until a run completes.
                self._invalidate_calibration()

                fast_rpm = request.speed_rpm
                max_probe_steps = request.steps_per_rotation * request.max_probe_rotations
                trapezoidal = request.trapezoidal_speed
                acceleration = request.acceleration_rpm_per_s

                # ---- Step clear of the tool holders before anything else: the
                # carriage may be parked among them, and the Y homing that
                # follows would drag a mounted tool through the holder rack.
                # The distance converts through the carried-over steps-per-cm
                # estimate; precision does not matter for a clearance hop. The
                # move stops silently on X-max, which the nudge below frees. ----
                clear_steps = round(request.x_start_clear_cm * self._effective_steps_per_cm())
                if clear_steps > 0:
                    self._move_corexy_steps(
                        gpio, pins, clear_steps, clear_steps, fast_rpm,
                        stop_limit_pin=pins.x_max_limit_pin,
                        steps_per_rotation=request.steps_per_rotation,
                        trapezoidal=trapezoidal, acceleration_rpm_per_s=acceleration,
                    )

                self._nudge_away_from_pressed_limits(
                    gpio, pins, fast_rpm, request.steps_per_rotation, trapezoidal, acceleration
                )

                # ---- Y first: home against the Y-min switch so the Y position
                # is known, then park clear of the switch so the X sweep does not
                # drag the frame along its Y stop. The park cm converts with the
                # steps-per-cm carried over from the last calibration (or the
                # pre-calibration estimate) and is corrected onto the exact cm
                # once X has measured the true value, like the firmware. ----
                self._probe_axis(
                    gpio, pins, "y", -1, max_probe_steps, request.steps_per_rotation, fast_rpm,
                    trapezoidal, acceleration,
                )
                self._y_steps = 0
                park_steps = max(1, round(request.x_calibration_y_cm * self._effective_steps_per_cm()))
                self._move_corexy_steps(
                    gpio, pins, park_steps, -park_steps, fast_rpm,
                    steps_per_rotation=request.steps_per_rotation,
                    trapezoidal=trapezoidal, acceleration_rpm_per_s=acceleration,
                )
                self._y_steps = park_steps

                # ---- X: the min slow touch defines X = 0, then the max home
                # measures the physical track in steps -- that measurement is
                # what makes cm real on this machine. ----
                self._probe_axis(
                    gpio, pins, "x", -1, max_probe_steps, request.steps_per_rotation, fast_rpm,
                    trapezoidal, acceleration,
                )
                self._x_steps = 0
                measured_x_steps = self._probe_axis(
                    gpio, pins, "x", 1, max_probe_steps, request.steps_per_rotation, fast_rpm,
                    trapezoidal, acceleration,
                )
                if measured_x_steps <= 0:
                    raise RuntimeError(
                        "X max homing measured zero travel from X min; check the X limit switches."
                    )
                self._x_steps = measured_x_steps
                steps_per_cm = measured_x_steps / request.x_track_length_cm

                # The park above used an estimated steps-per-cm; only now is the
                # real value measured. Correct Y onto the exact requested cm so
                # the recorded Y position is true rather than approximate,
                # mirroring the firmware's post-measurement Y correction.
                desired_y_steps = round(request.x_calibration_y_cm * steps_per_cm)
                y_correction = desired_y_steps - self._y_steps
                if y_correction != 0:
                    self._move_corexy_steps(
                        gpio, pins, y_correction, -y_correction, fast_rpm,
                        stop_limit_pin=pins.y_min_limit_pin if y_correction < 0 else None,
                        steps_per_rotation=request.steps_per_rotation,
                        trapezoidal=trapezoidal, acceleration_rpm_per_s=acceleration,
                    )
                    self._y_steps = desired_y_steps

                # Walk back off the X-max switch so calibration never finishes
                # with a limit pressed: at least one buffer (the usable max),
                # extended to the requested end clearance so the gantry parks
                # well clear of the switch and the tool holders at the far end.
                backoff_steps = round(max(request.limit_buffer_cm, request.x_end_clear_cm) * steps_per_cm)
                if backoff_steps > 0:
                    self._move_corexy_steps(
                        gpio, pins, -backoff_steps, -backoff_steps, fast_rpm,
                        steps_per_rotation=request.steps_per_rotation,
                        trapezoidal=trapezoidal, acceleration_rpm_per_s=acceleration,
                    )
                    self._x_steps = measured_x_steps - backoff_steps

                self._adopt_calibration(request, steps_per_cm)
            finally:
                self._cleanup_gpio(gpio, pins)

        return self._calibration_result(context, request, pins, execution)

    def _adopt_calibration(self, request: GantryXYCalibrationRequest, steps_per_cm: float) -> None:
        """Record a completed (or simulated) calibration and persist it.

        User coordinates sit one buffer inside the physical track, exactly like
        the firmware: user 0 is one buffer off the min switch, so the physical
        position maps to user cm as physical/steps_per_cm - buffer.
        """
        self._measured_steps_per_cm = steps_per_cm
        self._steps_per_rotation = request.steps_per_rotation
        self._limit_buffer_cm = request.limit_buffer_cm
        self._x_track_length_cm = request.x_track_length_cm
        self._y_track_length_cm = request.y_track_length_cm
        if not self._x_steps and not self._y_steps:
            # Simulated / GPIO-unavailable path: adopt the post-calibration rest
            # position (walked back to the usable X max, parked at the Y park).
            self._x_steps = round(
                (request.x_track_length_cm - max(request.limit_buffer_cm, request.x_end_clear_cm)) * steps_per_cm
            )
            self._y_steps = round(request.x_calibration_y_cm * steps_per_cm)
        self._x_cm = max(0.0, self._x_steps / steps_per_cm - self._limit_buffer_cm)
        self._y_cm = max(0.0, self._y_steps / steps_per_cm - self._limit_buffer_cm)
        self._y_known = True
        self._calibrated = True
        self._save_state()

    def test_motor(self, context: dict, request) -> dict:
        """Pulse one CoreXY motor on its own so the operator can identify it.

        CoreXY couples both belts, so driving a single motor moves the carriage
        diagonally rather than along an axis -- that diagonal, and its direction,
        is what distinguishes A from B by eye. Every switch is watched because a
        diagonal can reach any of them.
        """
        pins = self._pins_from_request(request, context)
        execution = self._execution_mode()
        signed_steps = int(request.steps) * (1 if request.forward else -1)
        a_steps = signed_steps if request.motor == "A" else 0
        b_steps = signed_steps if request.motor == "B" else 0

        stopped_on_limit = False
        tripped_limit_names: list[str] = []
        if not execution.simulated:
            gpio, _ = self._gpio_module()
            if gpio is None:
                raise RuntimeError("Compatible Raspberry Pi GPIO backend became unavailable during motor test.")
            with self._lock:
                try:
                    self._setup_gpio(gpio, pins)
                except Exception as exc:
                    execution = self._gpio_unavailable_execution(str(exc))
                else:
                    try:
                        stopped_on_limit = self._move_corexy_steps(
                            gpio,
                            pins,
                            a_steps,
                            b_steps,
                            request.speed_rpm,
                            stop_limit_pins=pins.limit_pins(),
                            steps_per_rotation=request.steps_per_rotation,
                        )
                        if stopped_on_limit:
                            # Read which switch(es) tripped before cleanup frees
                            # the pins below.
                            tripped_limit_names = [
                                name for name, pin in pins.named_limit_pins() if self._limit_active(gpio, pin)
                            ]
                    finally:
                        self._cleanup_gpio(gpio, pins)

        # The carriage moved without cartesian tracking, so the stored position is
        # no longer true. Drop it rather than leave later moves computing from it.
        self._invalidate_calibration()

        message = (
            f"Pulsed CoreXY motor {request.motor} {request.steps} steps "
            f"{'forward' if request.forward else 'backward'} at {request.speed_rpm} RPM through "
            "Raspberry Pi GPIO. On a CoreXY only one motor turning moves the carriage diagonally. "
            "The gantry calibration was dropped because this move is not position-tracked."
        )
        if stopped_on_limit:
            tripped_label = ", ".join(tripped_limit_names) if tripped_limit_names else "unknown"
            message = (
                f"Motor {request.motor} test stopped early: limit switch tripped ({tripped_label}). "
                "The gantry calibration was dropped."
            )
        if execution.simulated:
            message = execution.message

        return {
            "accepted": not stopped_on_limit,
            "status": execution.status,
            "message": message,
            "tool_port": None,
            "motor": request.motor,
            "steps": request.steps,
            "forward": request.forward,
            "speed_rpm": request.speed_rpm,
            "stopped_on_limit": stopped_on_limit,
            "a_steps": a_steps,
            "b_steps": b_steps,
            "configured_pins": {
                "a_step_pin": pins.a_step_pin,
                "a_dir_pin": pins.a_dir_pin,
                "b_step_pin": pins.b_step_pin,
                "b_dir_pin": pins.b_dir_pin,
            },
            "mode": context.get("mode"),
        }

    def move_xy(self, context: dict, request: GantryXYMoveRequest) -> dict:
        # A latched emergency stop blocks new motion until the next run rearms it.
        self._raise_if_stopped()
        pins = self._pins_from_request(request, context)
        execution = self._execution_mode()
        self._assert_target_within_calibrated_workspace(request)

        if execution.simulated:
            self._x_cm = request.x_cm
            self._y_cm = request.y_cm
            return self._move_result(context, request, pins, execution, applied=True)

        # A real move computes its path from the stored position, so it is only
        # meaningful after a calibration has established one. The firmware
        # refuses identically (ERR X NOT CALIBRATED).
        if not self._calibrated:
            raise RuntimeError("Gantry is not calibrated. Run Calibrate Gantry XY before moving.")

        gpio, _ = self._gpio_module()
        if gpio is None:
            raise RuntimeError("Compatible Raspberry Pi GPIO backend became unavailable during move.")
        with self._lock:
            try:
                self._setup_gpio(gpio, pins)
            except Exception as exc:
                execution = self._gpio_unavailable_execution(str(exc))
                self._x_cm = request.x_cm
                self._y_cm = request.y_cm
                return self._move_result(context, request, pins, execution, applied=True)
            try:
                self._assert_limits_clear(gpio, pins, request)

                # User coordinates map through the calibrated buffer exactly as
                # in the firmware: user 0 sits one buffer off the min switch.
                steps_per_cm = self._effective_steps_per_cm()
                target_x_steps = round((request.x_cm + self._limit_buffer_cm) * steps_per_cm)
                target_y_steps = round((request.y_cm + self._limit_buffer_cm) * steps_per_cm)
                delta_x = target_x_steps - self._x_steps
                delta_y = target_y_steps - self._y_steps

                # CoreXY: motor A = X + Y, motor B = X - Y (in steps).
                try:
                    self._move_corexy_steps(
                        gpio,
                        pins,
                        delta_x + delta_y,
                        delta_x - delta_y,
                        request.speed_rpm,
                        request=request,
                        steps_per_rotation=self._steps_per_rotation,
                        trapezoidal=request.trapezoidal_speed,
                        acceleration_rpm_per_s=request.acceleration_rpm_per_s,
                    )
                except BaseException:
                    # The move was aborted part way (emergency stop, limit trip)
                    # but every pulse issued so far was counted, so the position
                    # is still exactly known. Adopt the partial travel instead of
                    # discarding it - an E-Stop must not cost the calibration.
                    self._x_steps += (self._last_a_steps + self._last_b_steps) // 2
                    self._y_steps += (self._last_a_steps - self._last_b_steps) // 2
                    self._x_cm = max(0.0, self._x_steps / steps_per_cm - self._limit_buffer_cm)
                    self._y_cm = max(0.0, self._y_steps / steps_per_cm - self._limit_buffer_cm)
                    self._save_state()
                    raise
                self._x_steps = target_x_steps
                self._y_steps = target_y_steps
                self._x_cm = request.x_cm
                self._y_cm = request.y_cm
                self._save_state()
            finally:
                self._cleanup_gpio(gpio, pins)

        return self._move_result(context, request, pins, execution, applied=True)

    def circle_xy(self, context: dict, request: GantryCircleXYRequest) -> dict:
        """Trace a circle by walking short straight chords around it, matching
        the ESP32 firmware's circleGantryXY algorithm exactly: ~0.5mm chords
        approximate the arc, and one acceleration/deceleration profile is
        shaped across the whole circumference rather than per chord."""
        self._raise_if_stopped()
        pins = self._pins_from_request(request, context)
        execution = self._execution_mode()

        if execution.simulated:
            self._x_cm = request.center_x_cm + request.radius_cm
            self._y_cm = request.center_y_cm
            return self._circle_result(context, request, pins, execution)

        if not self._calibrated:
            raise RuntimeError("Gantry is not calibrated. Run Calibrate Gantry XY before moving.")

        # The full circle must fit inside the usable (buffer-inset) workspace,
        # exactly as the firmware enforces.
        usable_x_max = self._x_track_length_cm - 2.0 * self._limit_buffer_cm
        usable_y_max = self._y_track_length_cm - 2.0 * self._limit_buffer_cm
        if (
            request.center_x_cm - request.radius_cm < 0.0
            or request.center_x_cm + request.radius_cm > usable_x_max
            or request.center_y_cm - request.radius_cm < 0.0
            or request.center_y_cm + request.radius_cm > usable_y_max
        ):
            raise RuntimeError(
                f"Circle center ({request.center_x_cm:g}, {request.center_y_cm:g}) cm with radius "
                f"{request.radius_cm:g} cm does not fit inside the usable workspace "
                f"(0-{usable_x_max:g} x 0-{usable_y_max:g} cm)."
            )

        gpio, _ = self._gpio_module()
        if gpio is None:
            raise RuntimeError("Compatible Raspberry Pi GPIO backend became unavailable during move.")
        with self._lock:
            try:
                self._setup_gpio(gpio, pins)
            except Exception as exc:
                execution = self._gpio_unavailable_execution(str(exc))
                self._x_cm = request.center_x_cm + request.radius_cm
                self._y_cm = request.center_y_cm
                return self._circle_result(context, request, pins, execution)
            try:
                self._assert_limits_clear(gpio, pins, None)
                steps_per_cm = self._effective_steps_per_cm()
                self._run_circle_sweep(gpio, pins, request, steps_per_cm)
                self._save_state()
            finally:
                self._cleanup_gpio(gpio, pins)

        return self._circle_result(context, request, pins, execution)

    def _run_circle_sweep(
        self,
        gpio: Any,
        pins: _GPIOPinPlan,
        request: GantryCircleXYRequest,
        steps_per_cm: float,
    ) -> None:
        """Trace the circle repeat_count times back to back with a single
        acceleration/deceleration profile spanning every lap, so repeats flow
        into one another at cruise speed instead of decelerating toward a
        near-stall and re-accelerating at every lap boundary."""
        # Approach: straight move to the circle start point (angle 0, right of
        # center), with its own ramp - same as a normal move.
        start_x_steps = round((request.center_x_cm + request.radius_cm + self._limit_buffer_cm) * steps_per_cm)
        start_y_steps = round((request.center_y_cm + self._limit_buffer_cm) * steps_per_cm)
        self._run_circle_chord(
            gpio, pins, start_x_steps, start_y_steps, request.speed_rpm,
            trapezoidal=request.trapezoidal_speed, acceleration_rpm_per_s=request.acceleration_rpm_per_s,
        )

        circumference_cm = 2.0 * math.pi * request.radius_cm
        segments = max(24, math.ceil(circumference_cm / 0.05))
        steps_per_rotation = self._steps_per_rotation or 200
        # Motor iterations per chord are |dx| + |dy| steps, which integrates to
        # (4 / pi) x circumference over a lap; multiplied by repeat_count so the
        # ramp treats the whole multi-lap sweep as one continuous move, ramping
        # up once at the start and down once at the very end.
        total_profile_iterations = round(circumference_cm * steps_per_cm * 4.0 / math.pi) * request.repeat_count
        ramp_steps = self._ramp_steps(
            total_profile_iterations, request.speed_rpm, request.acceleration_rpm_per_s, steps_per_rotation
        )
        profile_done = 0

        for _ in range(request.repeat_count):
            for segment in range(1, segments + 1):
                angle = (2.0 * math.pi * segment) / segments
                target_x_steps = round(
                    (request.center_x_cm + self._limit_buffer_cm + request.radius_cm * math.cos(angle)) * steps_per_cm
                )
                target_y_steps = round(
                    (request.center_y_cm + self._limit_buffer_cm + request.radius_cm * math.sin(angle)) * steps_per_cm
                )
                delta_x = target_x_steps - self._x_steps
                delta_y = target_y_steps - self._y_steps
                if delta_x == 0 and delta_y == 0:
                    continue

                chord_iterations = abs(delta_x) + abs(delta_y)
                if request.trapezoidal_speed:
                    segment_rpm = self._trapezoid_rpm(
                        profile_done + chord_iterations // 2, total_profile_iterations, request.speed_rpm,
                        ramp_steps, request.acceleration_rpm_per_s, steps_per_rotation,
                    )
                else:
                    segment_rpm = request.speed_rpm

                self._run_circle_chord(gpio, pins, target_x_steps, target_y_steps, segment_rpm, trapezoidal=False)
                profile_done += chord_iterations

    def _run_circle_chord(
        self,
        gpio: Any,
        pins: _GPIOPinPlan,
        target_x_steps: int,
        target_y_steps: int,
        speed_rpm: float,
        trapezoidal: bool,
        acceleration_rpm_per_s: float = 300.0,
    ) -> None:
        delta_x = target_x_steps - self._x_steps
        delta_y = target_y_steps - self._y_steps
        # Every limit switch is watched, like the firmware's checkLimit=true:
        # a chord can approach any switch, not just the one guarding one axis.
        stopped = self._move_corexy_steps(
            gpio, pins, delta_x + delta_y, delta_x - delta_y, speed_rpm,
            stop_limit_pins=pins.limit_pins(),
            steps_per_rotation=self._steps_per_rotation,
            trapezoidal=trapezoidal, acceleration_rpm_per_s=acceleration_rpm_per_s,
        )
        self._x_steps += (self._last_a_steps + self._last_b_steps) // 2
        self._y_steps += (self._last_a_steps - self._last_b_steps) // 2
        steps_per_cm = self._effective_steps_per_cm()
        self._x_cm = max(0.0, self._x_steps / steps_per_cm - self._limit_buffer_cm)
        self._y_cm = max(0.0, self._y_steps / steps_per_cm - self._limit_buffer_cm)
        if stopped:
            self._save_state()
            tripped = [name for name, pin in pins.named_limit_pins() if self._limit_active(gpio, pin)]
            tripped_label = ", ".join(tripped) if tripped else "unknown"
            raise RuntimeError(f"Limit switch tripped during circle move; aborting: {tripped_label}")

    def _circle_result(
        self,
        context: dict,
        request: GantryCircleXYRequest,
        pins: _GPIOPinPlan,
        execution: _GPIOExecution,
    ) -> dict:
        return {
            "port": None,
            "baud_rate": 0,
            "speed_profile": request.speed_profile,
            "speed_rpm": request.speed_rpm,
            "trapezoidal_speed": request.trapezoidal_speed,
            "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
            "center": {"x_cm": request.center_x_cm, "y_cm": request.center_y_cm},
            "radius_cm": request.radius_cm,
            "repeat_count": request.repeat_count,
            "pin_command_sent": "GPIO CoreXY circle",
            "pin_reply": execution.message,
            "pins_applied": True,
            "limit_command_sent": "GPIO CoreXY circle",
            "limit_reply": execution.message,
            "limits_applied": True,
            "move_command_sent": "GPIO CoreXY circle",
            "move_reply": execution.message,
            "move_applied": True,
            "configured_pins": {
                "x_step_pin": pins.a_step_pin,
                "x_dir_pin": pins.a_dir_pin,
                "y_step_pin": pins.b_step_pin,
                "y_dir_pin": pins.b_dir_pin,
            },
            "configured_limits": {
                "limit_switch_mode": request.limit_switch_mode,
                "x_min_limit_pin": pins.x_min_limit_pin,
                "x_max_limit_pin": pins.x_max_limit_pin,
                "y_min_limit_pin": pins.y_min_limit_pin,
                "y_max_limit_pin": pins.y_max_limit_pin,
            },
            "mode": context.get("mode"),
            "controller": RASPBERRY_BOARD_ID,
            "simulated": execution.simulated,
        }

    def test_repeatability(self, context: dict, request: GantryRepeatabilityTestRequest) -> dict:
        """Measure step-skipping by touring X-min/Y-min -> X-mid/Y-max ->
        X-max/Y-min -> X-mid/Y-max repeatedly at each test speed.

        X-min, X-max, and Y-min are real limit switches: every arrival there
        is a genuine probe, comparing the calibrated distance that should
        have been needed ("expected") against how many pulses it actually
        took to trip the switch ("actual") - a real physical ground truth,
        never an assumed position. X-mid and Y-max have no switch (this
        machine only homes Y against Y-min), so those legs are ordinary
        calibrated moves with nothing to compare against. A healthy motor
        reproduces close to the same step count on every switch arrival; a
        motor skipping steps shows growing or erratic deviation, especially
        at higher speeds. Read-only - position is tracked as it moves, but
        calibration itself is never touched.
        """
        self._raise_if_stopped()
        if not self._calibrated:
            raise RuntimeError("Gantry is not calibrated. Run Calibrate Gantry XY before testing repeatability.")

        pins = self._pins_from_request(request, context)
        execution = self._execution_mode()
        speeds = request.speeds_rpm()
        if not speeds:
            raise RuntimeError("At least one test speed (speed_1_rpm) must be greater than 0.")

        limit_results_by_name = {
            name: GantryRepeatabilityLimitResult(limit=name) for name in ("x_min", "x_max", "y_min")
        }

        if execution.simulated:
            for name, result in limit_results_by_name.items():
                visits_per_cycle = 2 if name == "y_min" else 1
                for speed in speeds:
                    for cycle in range(request.repeat_count):
                        for visit in range(visits_per_cycle):
                            result.trials.append(GantryRepeatabilityTrial(
                                speed_rpm=speed, trial=cycle * visits_per_cycle + visit + 1,
                                expected_steps=0, actual_steps=0, deviation_steps=0,
                            ))
            return self._repeatability_result(context, request, execution, list(limit_results_by_name.values()))

        gpio, _ = self._gpio_module()
        if gpio is None:
            raise RuntimeError("Compatible Raspberry Pi GPIO backend became unavailable during repeatability test.")
        with self._lock:
            try:
                self._setup_gpio(gpio, pins)
            except Exception as exc:
                execution = self._gpio_unavailable_execution(str(exc))
                return self._repeatability_result(context, request, execution, list(limit_results_by_name.values()))
            try:
                steps_per_cm = self._effective_steps_per_cm()
                steps_per_rotation = self._steps_per_rotation or 800
                x_max_steps = round(self._x_track_length_cm * steps_per_cm)
                x_mid_cm = max(0.0, (self._x_track_length_cm - 2.0 * self._limit_buffer_cm) / 2.0)
                x_mid_steps = round((x_mid_cm + self._limit_buffer_cm) * steps_per_cm)
                y_max_cm = max(0.0, self._y_track_length_cm - 2.0 * self._limit_buffer_cm)
                y_max_steps = round((y_max_cm + self._limit_buffer_cm) * steps_per_cm)

                # (x target steps, x limit pin or None, x limit name or None,
                #  y target steps, y limit pin or None, y limit name or None)
                waypoints = [
                    (0, pins.x_min_limit_pin, "x_min", 0, pins.y_min_limit_pin, "y_min"),
                    (x_mid_steps, None, None, y_max_steps, None, None),
                    (x_max_steps, pins.x_max_limit_pin, "x_max", 0, pins.y_min_limit_pin, "y_min"),
                    (x_mid_steps, None, None, y_max_steps, None, None),
                ]

                for speed in speeds:
                    for _ in range(request.repeat_count):
                        for x_target, x_pin, x_name, y_target, y_pin, y_name in waypoints:
                            self._raise_if_stopped()
                            x_probe = self._move_axis_to(
                                gpio, pins, "x", x_target, speed, request.trapezoidal_speed,
                                request.acceleration_rpm_per_s, steps_per_rotation, x_pin,
                            )
                            if x_probe is not None:
                                self._record_repeatability_trial(limit_results_by_name, x_name, speed, x_probe)

                            y_probe = self._move_axis_to(
                                gpio, pins, "y", y_target, speed, request.trapezoidal_speed,
                                request.acceleration_rpm_per_s, steps_per_rotation, y_pin,
                            )
                            if y_probe is not None:
                                self._record_repeatability_trial(limit_results_by_name, y_name, speed, y_probe)
                self._save_state()
            finally:
                self._cleanup_gpio(gpio, pins)

        return self._repeatability_result(context, request, execution, list(limit_results_by_name.values()))

    def _move_axis_to(
        self,
        gpio: Any,
        pins: _GPIOPinPlan,
        axis: str,
        target_steps: int,
        rpm: float,
        trapezoidal: bool,
        acceleration_rpm_per_s: float,
        steps_per_rotation: int,
        probe_pin: int | None,
    ) -> tuple[int, int, bool] | None:
        """Move one axis from the tracked position to target_steps.

        With probe_pin, stops on that limit and returns (actual_steps,
        expected_steps, tripped) - actual_steps is measured directly from
        the pulses issued, never assumed. Without probe_pin, makes an
        ordinary calibrated move (no limit checking) and returns None.
        Position bookkeeping happens here so callers never touch it.
        """
        current = self._x_steps if axis == "x" else self._y_steps
        delta = target_steps - current
        expected = abs(delta)
        direction = 1 if delta >= 0 else -1

        def axis_delta() -> int:
            if axis == "x":
                return (self._last_a_steps + self._last_b_steps) // 2
            return (self._last_a_steps - self._last_b_steps) // 2

        def pulse(steps: int, stop_pin: int | None) -> bool:
            a, b = (steps, steps) if axis == "x" else (steps, -steps)
            return self._move_corexy_steps(
                gpio, pins, a, b, rpm, stop_limit_pin=stop_pin,
                steps_per_rotation=steps_per_rotation, trapezoidal=trapezoidal,
                acceleration_rpm_per_s=acceleration_rpm_per_s,
            )

        if probe_pin is None:
            pulse(delta, None)
            actual = abs(axis_delta())
            self._apply_axis_delta(axis, direction * actual)
            return None

        if expected == 0:
            tripped = self._limit_active(gpio, probe_pin)
            return (0, 0, tripped)

        margin_steps = max(2 * steps_per_rotation, expected)
        travel_budget = direction * (expected + margin_steps)
        tripped = pulse(travel_budget, probe_pin)
        actual = abs(axis_delta())
        self._apply_axis_delta(axis, direction * actual)
        return (actual, expected, tripped)

    def _apply_axis_delta(self, axis: str, signed_steps: int) -> None:
        if axis == "x":
            self._x_steps += signed_steps
        else:
            self._y_steps += signed_steps

    def _record_repeatability_trial(
        self,
        limit_results_by_name: dict[str, GantryRepeatabilityLimitResult],
        limit_name: str,
        speed: int,
        probe: tuple[int, int, bool],
    ) -> None:
        actual, expected, tripped = probe
        if not tripped:
            raise RuntimeError(
                f"{limit_name} limit switch was not hit within the safety margin during the repeatability test "
                f"at {speed} RPM - deviation exceeds what the test allows for."
            )
        result = limit_results_by_name[limit_name]
        deviation = actual - expected
        result.trials.append(GantryRepeatabilityTrial(
            speed_rpm=speed, trial=len(result.trials) + 1,
            expected_steps=expected, actual_steps=actual, deviation_steps=deviation,
        ))
        result.max_abs_deviation_steps = max((abs(t.deviation_steps) for t in result.trials), default=0)
        result.mean_abs_deviation_steps = (
            sum(abs(t.deviation_steps) for t in result.trials) / len(result.trials)
        )

    def _repeatability_result(
        self,
        context: dict,
        request: GantryRepeatabilityTestRequest,
        execution: _GPIOExecution,
        limit_results: list[GantryRepeatabilityLimitResult],
    ) -> dict:
        overall_max = max((r.max_abs_deviation_steps for r in limit_results), default=0)
        return {
            "status": execution.status,
            "message": execution.message,
            "repeat_count": request.repeat_count,
            "speeds_rpm": request.speeds_rpm(),
            "steps_per_cm": self._effective_steps_per_cm(),
            "results": [result.model_dump() for result in limit_results],
            "max_abs_deviation_steps": overall_max,
            "mode": context.get("mode"),
            "simulated": execution.simulated,
        }

    def _assert_target_within_calibrated_workspace(self, request: GantryXYMoveRequest) -> None:
        if not self._calibrated:
            return
        # The usable range is inset from each switch by the calibrated buffer, so
        # the highest reachable coordinate is the track length minus two buffers,
        # exactly as the firmware enforces.
        usable_x_max = self._x_track_length_cm - 2.0 * self._limit_buffer_cm
        usable_y_max = self._y_track_length_cm - 2.0 * self._limit_buffer_cm
        if not 0.0 <= request.x_cm <= usable_x_max:
            raise RuntimeError(f"x_cm must be between 0 and the usable X maximum of {usable_x_max:g} cm.")
        if not 0.0 <= request.y_cm <= usable_y_max:
            raise RuntimeError(f"y_cm must be between 0 and the usable Y maximum of {usable_y_max:g} cm.")

    def _execution_mode(self) -> _GPIOExecution:
        gpio, unavailable_reason = self._gpio_module()
        if gpio is not None and not _bool_env("ROBOT_GPIO_SIMULATE", False):
            return _GPIOExecution(
                status="gpio_executed",
                message="XY gantry motion was executed directly through Raspberry Pi GPIO step and direction pins.",
                simulated=False,
            )

        return self._gpio_unavailable_execution(unavailable_reason)

    def _gpio_unavailable_execution(self, unavailable_reason: str | None) -> _GPIOExecution:
        reason = f" {unavailable_reason}" if unavailable_reason else ""
        if _bool_env("ROBOT_GPIO_REQUIRE_HARDWARE", False):
            raise RuntimeError(
                "Raspberry Pi GPIO execution was required, but a compatible GPIO backend is not available."
                f"{reason} On the Pi, reinstall backend dependencies (pip install -r requirements.txt "
                "pulls in rpi-lgpio, which supports the Pi 5) — uninstall any manually added RPi.GPIO "
                "package from the venv first, or unset ROBOT_GPIO_REQUIRE_HARDWARE for simulation."
            )

        return _GPIOExecution(
            status="gpio_simulated",
            message=(
                "XY gantry is mapped to Raspberry Pi GPIO, but a compatible GPIO backend is not available in this environment."
                f"{reason} "
                "The backend simulated the command and did not move physical hardware."
            ),
            simulated=True,
            unavailable_reason=unavailable_reason,
        )

    def _gpio_module(self) -> tuple[Any | None, str | None]:
        if _bool_env("ROBOT_GPIO_SIMULATE", False):
            return None, "ROBOT_GPIO_SIMULATE is enabled."
        return load_gpio_backend()

    def _pins_from_request(
        self,
        request: GantryXYMoveRequest | GantryXYCalibrationRequest | GantryRepeatabilityTestRequest,
        context: dict | None = None,
    ) -> _GPIOPinPlan:
        # Only guard the Y-max end when that switch actually exists in the
        # Hardware Map; otherwise its pin is unwired and would read as noise.
        y_max_limit_pin = getattr(request, "y_max_limit_pin", None)
        if context is not None:
            devices_by_id = {
                device.get("id"): device
                for device in _hardware_map_devices(context)
                if isinstance(device, dict)
            }
            if not _device_is_on_raspberry_pi(devices_by_id.get("y-max-limit-switch")):
                y_max_limit_pin = None

        return _GPIOPinPlan(
            a_step_pin=request.x_step_pin,
            a_dir_pin=request.x_dir_pin,
            b_step_pin=request.y_step_pin,
            b_dir_pin=request.y_dir_pin,
            x_min_limit_pin=request.x_min_limit_pin,
            x_max_limit_pin=request.x_max_limit_pin,
            y_min_limit_pin=request.y_min_limit_pin,
            y_max_limit_pin=y_max_limit_pin,
            # The request wins if it names a pin (a deliberate override);
            # otherwise take whatever the Hardware Map says is wired.
            enable_pin=(
                requested
                if (requested := getattr(request, "gantry_enable_pin", -1)) >= 0
                else _enable_pin_from_hardware_map(context)
            ),
        )

    def _setup_gpio(self, gpio: Any, pins: _GPIOPinPlan) -> None:
        gpio.setwarnings(False)
        gpio.setmode(gpio.BCM)
        for pin in [pins.a_step_pin, pins.a_dir_pin, pins.b_step_pin, pins.b_dir_pin]:
            gpio.setup(pin, gpio.OUT, initial=gpio.LOW)

        if pins.enable_pin is not None:
            # Claim it in whichever state means "disabled" for these drivers, so
            # nothing is energised until a move actually asks for it.
            self._register_power_domain(gpio, pins.enable_pin)
            # Claim it disabled only when it is not already held. Setup runs at
            # the start of every move, and re-initialising a line that is
            # mid-hold drops the drivers just as the next move begins - the
            # second and later moves of a sequence then run unpowered.
            if not motor_power_service.is_powered(GANTRY_XY_DOMAIN):
                disabled_level = (
                    gpio.HIGH if _bool_env("ROBOT_GPIO_GANTRY_ENABLE_ACTIVE_LOW", True) else gpio.LOW
                )
                gpio.setup(pins.enable_pin, gpio.OUT, initial=disabled_level)
            # Setup and cleanup bracket every GPIO operation this service does,
            # in matching try/finally pairs, so holding power across that span
            # covers each move without threading it through five call sites.
            # Cost is one settle delay per sequence: the release only starts a
            # linger timer, so the next block finds the drivers already live.
            motor_power_service.acquire(GANTRY_XY_DOMAIN)

        pull = gpio.PUD_UP if _bool_env("ROBOT_GPIO_LIMIT_ACTIVE_LOW", True) else gpio.PUD_DOWN
        for pin in pins.limit_pins():
            gpio.setup(pin, gpio.IN, pull_up_down=pull)

    def _register_power_domain(self, gpio: Any, enable_pin: int) -> None:
        """Teach the power service how to switch the CoreXY drivers.

        Registered here rather than at import because the pin comes from the
        Hardware Map and is only known once a move resolves its inputs.

        Driven LOW to enable, which is the standard TB6600 behaviour: ENA is an
        opto that *disables* the driver when energised, so a de-energised ENA
        is what makes one run. Confirmed on this machine by releasing the pin -
        it falls to the internal pull-down, the opto goes dark, and the motors
        energise.

        This was briefly flipped to active-high on the strength of an E-Stop
        appearing to switch the motors on. That reading was an artefact of two
        bugs below this line, not polarity: the enable pin was being released
        at the end of every move, so the power-down threw instead of driving
        anything and the pin simply sat at its pull-down - enabled. Do not
        re-flip this without driving the pin directly and watching the motors,
        with no move in progress.

        Wiring: ENA- to GND with PUL-/DIR-, ENA+ to this pin on both drivers.
        ENA is an opto LED, not a logic input, so it wants current rather than
        a voltage level - a weak (10k) pull-up does nothing here, unlike on the
        Z board's MS1 line. The pin idles low at boot, which on these boards
        means the drivers come up DISABLED, which is the safe direction.
        """
        active_low = _bool_env("ROBOT_GPIO_GANTRY_ENABLE_ACTIVE_LOW", True)

        def apply(on: bool) -> None:
            energised = (not on) if active_low else on
            level = gpio.HIGH if energised else gpio.LOW
            # Claim the pin here rather than assuming a move already did. The
            # power service outlives any single move - it holds the line for
            # minutes afterwards - so by the time a linger timer fires, or the
            # next move starts, nothing guarantees the channel is still set up
            # in this session. Writing to an unclaimed channel raises, which
            # previously surfaced as a calibration failing with "the GPIO
            # channel has not been set up as an OUTPUT". setup() is idempotent
            # and takes the level with it, so there is no glitch.
            gpio.setup(enable_pin, gpio.OUT, initial=level)
            gpio.output(enable_pin, level)

        # Five minutes, not the three seconds the Z/pump board uses. A CoreXY
        # head is held in place by belt tension and nothing else - drop the
        # current and it can be pushed, or pulled by a drag chain, and the
        # tracked position quietly stops matching reality. The Z screws are
        # self-locking so they can afford to power down promptly; this cannot.
        #
        # Long enough to cover the gaps between blocks and between runs, short
        # enough that a machine left alone eventually goes cold.
        linger_seconds = _float_env("ROBOT_GPIO_GANTRY_LINGER_SECONDS", GANTRY_IDLE_HOLD_SECONDS)

        motor_power_service.register(
            GANTRY_XY_DOMAIN,
            f"CoreXY A and B drivers (Pi GPIO {enable_pin}, "
            f"{'active low' if active_low else 'active high'}, "
            f"holds {linger_seconds:g}s after a move)",
            apply,
            active_low=active_low,
            linger_seconds=linger_seconds,
        )

    def _cleanup_gpio(self, gpio: Any, pins: _GPIOPinPlan) -> None:
        if pins.enable_pin is not None:
            motor_power_service.release(GANTRY_XY_DOMAIN)
        gpio.cleanup(
            [
                pins.a_step_pin,
                pins.a_dir_pin,
                pins.b_step_pin,
                pins.b_dir_pin,
                *pins.limit_pins(),
            ]
        )
        # The enable pin is deliberately NOT released here. The power service
        # owns it across moves - that is what lets power linger between blocks
        # instead of cycling. Releasing it reverted the pin to an input, so the
        # linger timer's power-down then threw "channel has not been set up as
        # an OUTPUT", and the domain was left believing it was still powered.

    def _steps_per_cm(self) -> float:
        return float(os.getenv("ROBOT_GPIO_XY_STEPS_PER_CM", DEFAULT_STEPS_PER_CM))

    def _step_interval_seconds(self, speed_rpm: float, steps_per_rotation: int | None = None) -> float:
        configured_steps_per_rotation = steps_per_rotation or int(os.getenv("ROBOT_GPIO_STEPS_PER_ROTATION", "200"))
        rpm = max(float(speed_rpm), 0.1)
        return max(60.0 / (rpm * configured_steps_per_rotation), DEFAULT_STEP_PULSE_SECONDS * 2.0)

    def _ramp_steps(
        self,
        total_steps: int,
        target_rpm: float,
        acceleration_rpm_per_s: float,
        steps_per_rotation: int,
    ) -> int:
        """Steps needed to reach the target speed at constant acceleration
        (v^2 / 2a), clamped to half the move so short moves peak at the midpoint.
        Mirrors rampIterationsForMotion in the ESP32 firmware."""
        if total_steps <= 2 or target_rpm <= 0 or acceleration_rpm_per_s <= 0:
            return 0
        accel_steps_per_s2 = acceleration_rpm_per_s * steps_per_rotation / 60.0
        target_steps_per_s = target_rpm * steps_per_rotation / 60.0
        ramp = int(target_steps_per_s * target_steps_per_s / (2.0 * accel_steps_per_s2))
        return min(max(ramp, 1), total_steps // 2)

    def _trapezoid_rpm(
        self,
        iteration: int,
        total_steps: int,
        target_rpm: float,
        ramp_steps: int,
        acceleration_rpm_per_s: float,
        steps_per_rotation: int,
    ) -> float:
        """Speed for one iteration of a trapezoidal move: accelerate over the
        first ramp_steps, cruise, decelerate over the last ramp_steps. Mirrors
        rpmForTrapezoidIteration in the ESP32 firmware, including its 10 RPM
        floor. For a limit probe the move stops on contact long before the
        deceleration phase, so it effectively just accelerates."""
        remaining = total_steps - iteration - 1
        ramp_position = min(iteration + 1, remaining + 1, ramp_steps)
        accel_steps_per_s2 = acceleration_rpm_per_s * steps_per_rotation / 60.0
        steps_per_s = math.sqrt(2.0 * accel_steps_per_s2 * ramp_position)
        rpm = steps_per_s * 60.0 / steps_per_rotation
        return max(MIN_RAMP_RPM, min(float(target_rpm), rpm))

    def _limit_active(self, gpio: Any, pin: int) -> bool:
        active_low = _bool_env("ROBOT_GPIO_LIMIT_ACTIVE_LOW", True)
        value = gpio.input(pin)
        return value == gpio.LOW if active_low else value == gpio.HIGH

    def _set_direction(self, gpio: Any, dir_pin: int, positive: bool, env_name: str) -> None:
        level = positive
        if _bool_env(env_name, False):
            level = not level
        gpio.output(dir_pin, gpio.HIGH if level else gpio.LOW)

    def _move_cm(
        self,
        gpio: Any,
        pins: _GPIOPinPlan,
        dx_cm: float,
        dy_cm: float,
        speed_rpm: float,
        request: GantryXYMoveRequest | None = None,
        stop_limit_pin: int | None = None,
        steps_per_rotation: int | None = None,
    ) -> bool:
        steps_per_cm = self._steps_per_cm()
        a_steps = int(round((dx_cm + dy_cm) * steps_per_cm))
        b_steps = int(round((dx_cm - dy_cm) * steps_per_cm))
        return self._move_corexy_steps(
            gpio,
            pins,
            a_steps,
            b_steps,
            speed_rpm,
            request,
            stop_limit_pin,
            steps_per_rotation,
        )

    def _move_corexy_steps(
        self,
        gpio: Any,
        pins: _GPIOPinPlan,
        a_steps: int,
        b_steps: int,
        speed_rpm: float,
        request: GantryXYMoveRequest | None = None,
        stop_limit_pin: int | None = None,
        stop_limit_pins: list[int] | None = None,
        steps_per_rotation: int | None = None,
        trapezoidal: bool = True,
        acceleration_rpm_per_s: float = 300.0,
    ) -> bool:
        # Reset the issued-pulse counters before anything can fail, so a caller
        # recovering from an aborted move never adopts counts from an earlier one.
        self._last_a_steps = 0
        self._last_b_steps = 0

        a_total = abs(a_steps)
        b_total = abs(b_steps)
        total = max(a_total, b_total)
        if total == 0:
            return False

        self._set_direction(gpio, pins.a_dir_pin, a_steps >= 0, "ROBOT_GPIO_A_DIR_INVERT")
        self._set_direction(gpio, pins.b_dir_pin, b_steps >= 0, "ROBOT_GPIO_B_DIR_INVERT")
        self._wait_until(time.perf_counter() + DIR_SETTLE_SECONDS)

        resolved_steps_per_rotation = steps_per_rotation or int(os.getenv("ROBOT_GPIO_STEPS_PER_ROTATION", "200"))
        base_interval = self._step_interval_seconds(speed_rpm, resolved_steps_per_rotation)
        min_interval = DEFAULT_STEP_PULSE_SECONDS * 2.0
        # Starting a stepper from standstill at full speed stalls it, and a
        # stall on one CoreXY motor bends the commanded straight line into a
        # diagonal. Ramp exactly like the firmware instead of jumping to speed.
        ramp_steps = (
            self._ramp_steps(total, speed_rpm, acceleration_rpm_per_s, resolved_steps_per_rotation)
            if trapezoidal
            else 0
        )

        a_error = 0
        b_error = 0
        a_sign = 1 if a_steps >= 0 else -1
        b_sign = 1 if b_steps >= 0 else -1
        try:
            for iteration in range(total):
                # Checked every step so an emergency stop aborts within one step
                # period instead of after the whole move.
                self._raise_if_stopped()

                if stop_limit_pin is not None and self._limit_active(gpio, stop_limit_pin):
                    return True

                # Driving one motor alone travels diagonally, so it can reach any
                # switch rather than only the one guarding a single axis.
                if stop_limit_pins and any(
                    self._limit_active(gpio, candidate) for candidate in stop_limit_pins
                ):
                    return True

                if request is not None:
                    self._assert_limits_clear(gpio, pins, request)

                pulse_a = False
                pulse_b = False
                a_error += a_total
                b_error += b_total
                if a_error >= total:
                    pulse_a = True
                    a_error -= total
                if b_error >= total:
                    pulse_b = True
                    b_error -= total

                if ramp_steps:
                    active_rpm = self._trapezoid_rpm(
                        iteration, total, speed_rpm, ramp_steps,
                        acceleration_rpm_per_s, resolved_steps_per_rotation,
                    )
                    interval = max(60.0 / (active_rpm * resolved_steps_per_rotation), min_interval)
                else:
                    interval = base_interval
                pulse = min(DEFAULT_STEP_PULSE_SECONDS, interval / 2.0)

                # Time the step from a single start point so the pulse and the
                # gap add up to the requested interval instead of drifting.
                # Count a pulse the moment its rising edge is written: drivers
                # step on that edge, so if an emergency stop lands during the
                # pulse the count still matches what the motor actually did.
                step_started = time.perf_counter()
                if pulse_a:
                    gpio.output(pins.a_step_pin, gpio.HIGH)
                    self._last_a_steps += a_sign
                if pulse_b:
                    gpio.output(pins.b_step_pin, gpio.HIGH)
                    self._last_b_steps += b_sign
                self._wait_until(step_started + pulse)
                if pulse_a:
                    gpio.output(pins.a_step_pin, gpio.LOW)
                if pulse_b:
                    gpio.output(pins.b_step_pin, gpio.LOW)
                self._wait_until(step_started + interval)
        except GantryStoppedError:
            # Leave the drivers in a safe idle state on the way out.
            gpio.output(pins.a_step_pin, gpio.LOW)
            gpio.output(pins.b_step_pin, gpio.LOW)
            raise

        return stop_limit_pin is not None and self._limit_active(gpio, stop_limit_pin)

    def rehome_x(self, context: dict, request: Any) -> dict:
        """Re-touch the X min switch and correct the tracked X position.

        For machines that lose the odd step. X = 0 is defined by the X min slow
        touch during calibration, so touching it again re-establishes exactly
        that reference without re-measuring the track or disturbing Y - which
        matters, because a full calibration would throw away a good Y home and
        cost a workspace traverse.

        CoreXY moves both motors for an X move, but with A and B stepping
        together the net Y displacement is zero, so Y is left where it was.

        Returns how far the position was out, which is the number worth
        watching: it is the accumulated step loss since the last home.
        """
        self._raise_if_stopped()
        pins = self._pins_from_request(request, context)
        execution = self._execution_mode()
        steps_per_cm = self._effective_steps_per_cm()

        if execution.simulated:
            return {
                "status": execution.status,
                "message": "X re-home simulated; no GPIO backend available.",
                "drift_steps": 0,
                "drift_cm": 0.0,
                "simulated": True,
            }

        if not self._calibrated:
            raise RuntimeError(
                "The gantry has not been calibrated, so there is no X reference to re-check. "
                "Run Calibrate Gantry XY first."
            )

        gpio, _ = self._gpio_module()
        if gpio is None:
            raise RuntimeError("Compatible Raspberry Pi GPIO backend became unavailable during X re-home.")

        steps_per_rotation = int(getattr(request, "steps_per_rotation", 0)) or self._steps_per_rotation
        rpm = float(getattr(request, "speed_rpm", 0) or 0) or 60.0
        trapezoidal = bool(getattr(request, "trapezoidal_speed", True))
        acceleration = float(getattr(request, "acceleration_rpm_per_s", 0) or 0) or 300.0

        with self._lock:
            self._setup_gpio(gpio, pins)
            try:
                expected_steps = self._x_steps
                # Budget the probe on where X is believed to be plus a generous
                # margin for accumulated loss. Bounded rather than the whole
                # track: if the switch is not found within a few cm of where it
                # should be, something is wrong and failing says so.
                max_probe_steps = max(
                    2 * steps_per_rotation,
                    expected_steps + round(_X_REHOME_MARGIN_CM * steps_per_cm),
                )
                travelled = abs(
                    self._probe_axis(
                        gpio, pins, "x", -1, max_probe_steps, steps_per_rotation, rpm,
                        trapezoidal, acceleration,
                    )
                )
                # The slow touch leaves the carriage resting on the switch,
                # which is physical zero. Walk back off until the switch
                # actually releases - a buffer's worth is the intent, but a
                # microswitch does not open the instant you leave it, and
                # stopping while it is still closed means the next waypoint
                # refuses to move at all. Keep nudging, bounded, and record
                # where it truly ended up rather than where it was aimed.
                step = max(1, round(self._limit_buffer_cm * steps_per_cm))
                backoff_steps = 0
                limit = max(1, math.ceil(_X_REHOME_RELEASE_CM / max(self._limit_buffer_cm, 0.01)))
                for _ in range(limit):
                    self._move_corexy_steps(
                        gpio, pins, step, step, rpm,
                        steps_per_rotation=steps_per_rotation,
                        trapezoidal=trapezoidal, acceleration_rpm_per_s=acceleration,
                    )
                    backoff_steps += step
                    if not self._limit_active(gpio, pins.x_min_limit_pin):
                        break
                else:
                    raise RuntimeError(
                        f"The X min switch is still closed {backoff_steps / steps_per_cm:.2f} cm after "
                        "backing off it. It may be stuck, mis-wired, or the carriage is jammed against it."
                    )
                self._x_steps = backoff_steps
                self._x_cm = 0.0
                # How far the belief was out: the probe had to travel this much
                # further (or less) than the tracked position said it would.
                drift_steps = travelled - expected_steps
                self._save_state()
            finally:
                self._cleanup_gpio(gpio, pins)

        return {
            "status": execution.status,
            "message": (
                f"X re-homed. Position was out by {drift_steps} steps "
                f"({drift_steps / steps_per_cm:+.3f} cm)."
            ),
            "expected_steps": expected_steps,
            "travelled_steps": travelled,
            "drift_steps": drift_steps,
            "drift_cm": round(drift_steps / steps_per_cm, 4),
            "simulated": False,
        }

    def _probe_axis(
        self,
        gpio: Any,
        pins: _GPIOPinPlan,
        axis: str,
        direction: int,
        max_probe_steps: int,
        steps_per_rotation: int,
        fast_rpm: float,
        trapezoidal: bool = True,
        acceleration_rpm_per_s: float = 300.0,
    ) -> int:
        """Three-pass homing matching homeXAgainstSwitch in the ESP32 firmware:
        fast touch, back off one full rotation, then a slow re-touch at
        XY_SLOW_HOMING_RPM capped at two rotations. Leaves the carriage resting
        on the switch and returns the net travel along the probed axis in steps,
        so the caller can measure steps-per-cm between two homes.
        """
        limit_pin = self._axis_limit_pin(pins, axis, direction)

        def axis_delta() -> int:
            if axis == "x":
                return (self._last_a_steps + self._last_b_steps) // 2
            return (self._last_a_steps - self._last_b_steps) // 2

        net_axis_steps = 0
        cartesian_steps = direction * max(1, int(max_probe_steps))
        a_steps = cartesian_steps
        b_steps = cartesian_steps if axis == "x" else -cartesian_steps

        hit_fast = self._move_corexy_steps(
            gpio,
            pins,
            a_steps,
            b_steps,
            fast_rpm,
            stop_limit_pin=limit_pin,
            steps_per_rotation=steps_per_rotation,
            trapezoidal=trapezoidal,
            acceleration_rpm_per_s=acceleration_rpm_per_s,
        )
        net_axis_steps += axis_delta()
        if not hit_fast:
            raise RuntimeError(f"{axis.upper()} {'max' if direction > 0 else 'min'} limit switch was not hit during fast calibration probe.")

        backoff_steps = -direction * max(1, steps_per_rotation)
        self._move_corexy_steps(
            gpio,
            pins,
            backoff_steps,
            backoff_steps if axis == "x" else -backoff_steps,
            fast_rpm,
            steps_per_rotation=steps_per_rotation,
            trapezoidal=trapezoidal,
            acceleration_rpm_per_s=acceleration_rpm_per_s,
        )
        net_axis_steps += axis_delta()

        slow_probe_steps = direction * max(1, steps_per_rotation * 2)
        hit_slow = self._move_corexy_steps(
            gpio,
            pins,
            slow_probe_steps,
            slow_probe_steps if axis == "x" else -slow_probe_steps,
            XY_SLOW_HOMING_RPM,
            stop_limit_pin=limit_pin,
            steps_per_rotation=steps_per_rotation,
            trapezoidal=trapezoidal,
            acceleration_rpm_per_s=acceleration_rpm_per_s,
        )
        net_axis_steps += axis_delta()
        if not hit_slow:
            raise RuntimeError(f"{axis.upper()} {'max' if direction > 0 else 'min'} limit switch was not hit during slow calibration probe.")

        return net_axis_steps

    def _nudge_away_from_pressed_limits(
        self,
        gpio: Any,
        pins: _GPIOPinPlan,
        rpm: float,
        steps_per_rotation: int,
        trapezoidal: bool = True,
        acceleration_rpm_per_s: float = 300.0,
    ) -> None:
        """Free any limit switch that is already pressed before calibrating.

        Backs off one motor rotation at a time, re-reading the switch between
        each, so the carriage travels no further than it takes to free the
        switch. A switch that stays pressed after four rotations is stuck or
        miswired, and calibrating from it would measure garbage.
        """
        candidates = [
            ("X_MIN", pins.x_min_limit_pin, 1, 1),
            ("X_MAX", pins.x_max_limit_pin, -1, -1),
            ("Y_MIN", pins.y_min_limit_pin, 1, -1),
            ("Y_MAX", pins.y_max_limit_pin, -1, 1),
        ]
        for name, pin, a_sign, b_sign in candidates:
            if pin is None or not self._limit_active(gpio, pin):
                continue
            rotations = 0
            while rotations < 4 and self._limit_active(gpio, pin):
                self._move_corexy_steps(
                    gpio,
                    pins,
                    a_sign * steps_per_rotation,
                    b_sign * steps_per_rotation,
                    rpm,
                    steps_per_rotation=steps_per_rotation,
                    trapezoidal=trapezoidal,
                    acceleration_rpm_per_s=acceleration_rpm_per_s,
                )
                rotations += 1
            if self._limit_active(gpio, pin):
                raise RuntimeError(
                    f"{name} limit switch is still pressed after nudging {rotations} rotations away "
                    "from it; the switch is stuck or miswired. Check the switch and its wiring."
                )

    def _axis_limit_pin(self, pins: _GPIOPinPlan, axis: str, direction: int) -> int:
        if axis == "x":
            return pins.x_max_limit_pin if direction > 0 else pins.x_min_limit_pin
        if axis == "y":
            if direction > 0:
                if pins.y_max_limit_pin is None:
                    raise RuntimeError(
                        "Cannot probe toward Y max: this machine has no Y-max limit switch mapped."
                    )
                return pins.y_max_limit_pin
            return pins.y_min_limit_pin
        raise ValueError(f"Unsupported calibration axis: {axis}")

    def _assert_limits_clear(
        self, gpio: Any, pins: _GPIOPinPlan, request: GantryXYMoveRequest | None
    ) -> None:
        """Refuse a move that would drive further into a switch already closed.

        Deliberately not "refuse every move while any switch is closed". A
        machine that cannot back off a tripped limit is stuck: every move is
        rejected, including the one that would free it, and there is nothing an
        operator can do from the UI to recover. Driving *away* from a closed
        switch is the recovery action, so it is always allowed.
        """
        active_limits = []
        if self._limit_active(gpio, pins.x_min_limit_pin):
            active_limits.append("x_min")
        if self._limit_active(gpio, pins.x_max_limit_pin):
            active_limits.append("x_max")
        if self._limit_active(gpio, pins.y_min_limit_pin):
            active_limits.append("y_min")
        if pins.y_max_limit_pin is not None and self._limit_active(gpio, pins.y_max_limit_pin):
            active_limits.append("y_max")

        if request is not None and (math.isnan(request.x_cm) or math.isnan(request.y_cm)):
            raise RuntimeError("Invalid gantry move target.")

        if not active_limits:
            return

        deltas: dict[str, float | None] = {"x": None, "y": None}
        if request is not None:
            deltas["x"] = request.x_cm - self._x_cm
            deltas["y"] = request.y_cm - self._y_cm

        blocking = []
        for name in active_limits:
            axis, end = name.split("_")
            delta = deltas[axis]
            if delta is None:
                # No target to reason about (a circle, a raw probe): stay
                # conservative and refuse, as before.
                blocking.append(name)
            elif end == "min" and delta < 0:
                blocking.append(name)
            elif end == "max" and delta > 0:
                blocking.append(name)

        if blocking:
            raise RuntimeError(
                "This move would drive further into a limit switch that is already pressed ("
                + ", ".join(blocking)
                + "). Move away from that end first - a move in the opposite direction is allowed "
                "even while the switch is closed. If nothing is touching the switch, it is stuck "
                "or mis-wired."
            )

    def _calibration_result(
        self,
        context: dict,
        request: GantryXYCalibrationRequest,
        pins: _GPIOPinPlan,
        execution: _GPIOExecution,
    ) -> dict:
        return {
            "calibrated": True,
            "status": execution.status,
            "message": execution.message,
            "tool_port": None,
            "workspace": {
                "x_track_length_cm": request.x_track_length_cm,
            },
            "calibration_speed_profile": request.calibration_speed_profile,
            "speed_rpm": request.speed_rpm,
            "trapezoidal_speed": request.trapezoidal_speed,
            "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
            "steps_per_rotation": request.steps_per_rotation,
            "max_probe_rotations": request.max_probe_rotations,
            "pin_command_sent": None,
            "pin_reply": None,
            "pins_applied": True,
            "limit_command_sent": None,
            "limit_reply": None,
            "limits_applied": True,
            "calibration_command_sent": "GPIO CoreXY calibration",
            "calibration_reply": execution.message,
            "configured_pins": {
                "x_step_pin": pins.a_step_pin,
                "x_dir_pin": pins.a_dir_pin,
                "y_step_pin": pins.b_step_pin,
                "y_dir_pin": pins.b_dir_pin,
            },
            "configured_limits": {
                "limit_switch_mode": "4",
                "x_min_limit_pin": pins.x_min_limit_pin,
                "x_max_limit_pin": pins.x_max_limit_pin,
                "y_min_limit_pin": pins.y_min_limit_pin,
                "y_max_limit_pin": pins.y_max_limit_pin,
                "speed_rpm": request.speed_rpm,
                "trapezoidal_speed": request.trapezoidal_speed,
                "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
                "steps_per_rotation": request.steps_per_rotation,
                "max_probe_rotations": request.max_probe_rotations,
            },
            "mode": context.get("mode"),
            "controller": RASPBERRY_BOARD_ID,
            "simulated": execution.simulated,
        }

    def _move_result(
        self,
        context: dict,
        request: GantryXYMoveRequest,
        pins: _GPIOPinPlan,
        execution: _GPIOExecution,
        applied: bool,
    ) -> dict:
        return {
            "accepted": applied,
            "status": execution.status,
            "message": execution.message,
            "tool_port": None,
            "target": {"x_cm": request.x_cm, "y_cm": request.y_cm, "z_cm": request.z_cm},
            "speed_profile": request.speed_profile,
            "speed_rpm": request.speed_rpm,
            "trapezoidal_speed": request.trapezoidal_speed,
            "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
            "on_the_fly_calibration": request.on_the_fly_calibration,
            "calibration_max_diff_steps": request.calibration_max_diff_steps,
            "pin_command_sent": None,
            "pin_reply": None,
            "pins_applied": True,
            "limit_command_sent": None,
            "limit_reply": None,
            "limits_applied": True,
            "move_command_sent": "GPIO CoreXY move",
            "move_reply": execution.message,
            "move_applied": applied,
            "configured_pins": {
                "x_step_pin": pins.a_step_pin,
                "x_dir_pin": pins.a_dir_pin,
                "y_step_pin": pins.b_step_pin,
                "y_dir_pin": pins.b_dir_pin,
            },
            "configured_limits": {
                "limit_switch_mode": request.limit_switch_mode,
                "x_min_limit_pin": pins.x_min_limit_pin,
                "x_max_limit_pin": pins.x_max_limit_pin,
                "y_min_limit_pin": pins.y_min_limit_pin,
                "y_max_limit_pin": pins.y_max_limit_pin,
                "speed_rpm": request.speed_rpm,
                "trapezoidal_speed": request.trapezoidal_speed,
                "acceleration_rpm_per_s": request.acceleration_rpm_per_s,
                "on_the_fly_calibration": request.on_the_fly_calibration,
                "calibration_max_diff_steps": request.calibration_max_diff_steps,
            },
            "mode": context.get("mode"),
            "controller": RASPBERRY_BOARD_ID,
            "simulated": execution.simulated,
            "calibrated": self._calibrated,
        }


raspberry_gantry_gpio_service = RaspberryGantryGPIOService()

# Stopped first: this only sets the shared flag, so it returns instantly and
# never delays the serial actors behind it.
safety_controller.register_actor(
    CallableActor("raspberry-pi-gantry", raspberry_gantry_gpio_service.emergency_stop),
    priority=PRIORITY_FLAG,
    description="Raspberry Pi GPIO gantry (CoreXY stepping loop)",
)


def planned_calibrate_xy_result(context: dict, request: GantryXYCalibrationRequest) -> dict:
    return raspberry_gantry_gpio_service.calibrate_xy(context, request)


def planned_move_xy_result(context: dict, request: GantryXYMoveRequest) -> dict:
    return raspberry_gantry_gpio_service.move_xy(context, request)


def planned_circle_xy_result(context: dict, request: GantryCircleXYRequest) -> dict:
    return raspberry_gantry_gpio_service.circle_xy(context, request)


def planned_test_motor_result(context: dict, request) -> dict:
    return raspberry_gantry_gpio_service.test_motor(context, request)


def planned_test_repeatability_result(context: dict, request: GantryRepeatabilityTestRequest) -> dict:
    return raspberry_gantry_gpio_service.test_repeatability(context, request)


def emergency_stop_raspberry_gantry() -> dict[str, object]:
    return raspberry_gantry_gpio_service.emergency_stop()


def rearm_raspberry_gantry() -> None:
    """Deprecated. Rearming goes through `safety_controller.rearm()`, which
    refuses while any physical fact is still unconfirmed."""
    raspberry_gantry_gpio_service.rearm()
