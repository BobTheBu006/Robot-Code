import importlib
import math
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.models.gantry import GANTRY_WORKSPACE_X_CM, GANTRY_WORKSPACE_Y_CM, GantryXYCalibrationRequest, GantryXYMoveRequest

RASPBERRY_BOARD_ID = "raspberry-pi"
XY_DEVICE_IDS = {
    "x-axis-motor",
    "y-axis-motor",
    "x-min-limit-switch",
    "x-max-limit-switch",
    "y-min-limit-switch",
    "y-max-limit-switch",
}

DEFAULT_STEPS_PER_CM = 100.0
DEFAULT_STEP_PULSE_SECONDS = 0.0005
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
    y_max_limit_pin: int


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


def xy_hardware_is_on_raspberry_pi(context: dict) -> bool:
    devices_by_id = {
        device.get("id"): device
        for device in _hardware_map_devices(context)
        if isinstance(device, dict)
    }

    for device_id in XY_DEVICE_IDS:
        device = devices_by_id.get(device_id)
        if not device or device.get("board_id") != RASPBERRY_BOARD_ID or device.get("enabled") is False:
            return False

    return True


def _bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


class RaspberryGantryGPIOService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._x_cm = 0.0
        self._y_cm = 0.0
        self._x_track_length_cm = GANTRY_WORKSPACE_X_CM
        self._y_track_length_cm = GANTRY_WORKSPACE_Y_CM
        self._calibrated = False

    def calibrate_xy(self, context: dict, request: GantryXYCalibrationRequest) -> dict:
        pins = self._pins_from_request(request)
        execution = self._execution_mode()

        if execution.simulated:
            self._x_cm = 0.0
            self._y_cm = 0.0
            self._x_track_length_cm = request.x_track_length_cm
            self._y_track_length_cm = request.y_track_length_cm
            self._calibrated = True
            return self._calibration_result(context, request, pins, execution)

        gpio, _ = self._gpio_module()
        if gpio is None:
            raise RuntimeError("Compatible Raspberry Pi GPIO backend became unavailable during calibration.")
        with self._lock:
            try:
                self._setup_gpio(gpio, pins)
            except Exception as exc:
                execution = self._gpio_unavailable_execution(str(exc))
                self._x_cm = 0.0
                self._y_cm = 0.0
                self._x_track_length_cm = request.x_track_length_cm
                self._y_track_length_cm = request.y_track_length_cm
                self._calibrated = True
                return self._calibration_result(context, request, pins, execution)
            try:
                fast_rpm = request.speed_rpm
                slow_rpm = max(1.0, request.speed_rpm / 3.0)

                max_probe_steps = request.steps_per_rotation * request.max_probe_rotations

                self._probe_axis(gpio, pins, "x", -1, max_probe_steps, request.steps_per_rotation, fast_rpm, slow_rpm)
                self._x_cm = 0.0
                self._probe_axis(gpio, pins, "x", 1, max_probe_steps, request.steps_per_rotation, fast_rpm, slow_rpm)
                self._x_cm = request.x_track_length_cm

                self._move_cm(
                    gpio,
                    pins,
                    -request.x_track_length_cm * 1.25,
                    0.0,
                    request.speed_rpm,
                    stop_limit_pin=pins.x_min_limit_pin,
                )
                self._x_cm = 0.0

                self._probe_axis(gpio, pins, "y", -1, max_probe_steps, request.steps_per_rotation, fast_rpm, slow_rpm)
                self._y_cm = 0.0
                self._probe_axis(gpio, pins, "y", 1, max_probe_steps, request.steps_per_rotation, fast_rpm, slow_rpm)
                self._y_cm = request.y_track_length_cm
                self._x_track_length_cm = request.x_track_length_cm
                self._y_track_length_cm = request.y_track_length_cm

                self._calibrated = True
            finally:
                self._cleanup_gpio(gpio, pins)

        return self._calibration_result(context, request, pins, execution)

    def move_xy(self, context: dict, request: GantryXYMoveRequest) -> dict:
        pins = self._pins_from_request(request)
        execution = self._execution_mode()
        self._assert_target_within_calibrated_workspace(request)

        if execution.simulated:
            self._x_cm = request.x_cm
            self._y_cm = request.y_cm
            return self._move_result(context, request, pins, execution, applied=True)

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
                dx_cm = request.x_cm - self._x_cm
                dy_cm = request.y_cm - self._y_cm
                self._move_cm(gpio, pins, dx_cm, dy_cm, request.speed_rpm, request)
                self._x_cm = request.x_cm
                self._y_cm = request.y_cm
            finally:
                self._cleanup_gpio(gpio, pins)

        return self._move_result(context, request, pins, execution, applied=True)

    def _assert_target_within_calibrated_workspace(self, request: GantryXYMoveRequest) -> None:
        if not self._calibrated:
            return
        if not 0.0 <= request.x_cm <= self._x_track_length_cm:
            raise RuntimeError(f"x_cm must be between 0 and calibrated X length {self._x_track_length_cm} cm.")
        if not 0.0 <= request.y_cm <= self._y_track_length_cm:
            raise RuntimeError(f"y_cm must be between 0 and calibrated Y length {self._y_track_length_cm} cm.")

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
                f"{reason} Install a Pi-compatible GPIO package such as rpi-lgpio/python3-rpi-lgpio, "
                "or unset ROBOT_GPIO_REQUIRE_HARDWARE for simulation."
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
        try:
            gpio = importlib.import_module("RPi.GPIO")
        except ImportError as exc:
            return None, str(exc)

        try:
            gpio.setwarnings(False)
            gpio.setmode(gpio.BCM)
            gpio.cleanup()
        except Exception as exc:
            return None, str(exc)

        return gpio, None

    def _pins_from_request(self, request: GantryXYMoveRequest | GantryXYCalibrationRequest) -> _GPIOPinPlan:
        return _GPIOPinPlan(
            a_step_pin=request.x_step_pin,
            a_dir_pin=request.x_dir_pin,
            b_step_pin=request.y_step_pin,
            b_dir_pin=request.y_dir_pin,
            x_min_limit_pin=request.x_min_limit_pin,
            x_max_limit_pin=request.x_max_limit_pin,
            y_min_limit_pin=request.y_min_limit_pin,
            y_max_limit_pin=request.y_max_limit_pin,
        )

    def _setup_gpio(self, gpio: Any, pins: _GPIOPinPlan) -> None:
        gpio.setwarnings(False)
        gpio.setmode(gpio.BCM)
        for pin in [pins.a_step_pin, pins.a_dir_pin, pins.b_step_pin, pins.b_dir_pin]:
            gpio.setup(pin, gpio.OUT, initial=gpio.LOW)

        pull = gpio.PUD_UP if _bool_env("ROBOT_GPIO_LIMIT_ACTIVE_LOW", True) else gpio.PUD_DOWN
        for pin in [
            pins.x_min_limit_pin,
            pins.x_max_limit_pin,
            pins.y_min_limit_pin,
            pins.y_max_limit_pin,
        ]:
            gpio.setup(pin, gpio.IN, pull_up_down=pull)

    def _cleanup_gpio(self, gpio: Any, pins: _GPIOPinPlan) -> None:
        gpio.cleanup(
            [
                pins.a_step_pin,
                pins.a_dir_pin,
                pins.b_step_pin,
                pins.b_dir_pin,
                pins.x_min_limit_pin,
                pins.x_max_limit_pin,
                pins.y_min_limit_pin,
                pins.y_max_limit_pin,
            ]
        )

    def _steps_per_cm(self) -> float:
        return float(os.getenv("ROBOT_GPIO_XY_STEPS_PER_CM", DEFAULT_STEPS_PER_CM))

    def _step_interval_seconds(self, speed_rpm: float, steps_per_rotation: int | None = None) -> float:
        configured_steps_per_rotation = steps_per_rotation or int(os.getenv("ROBOT_GPIO_STEPS_PER_ROTATION", "200"))
        rpm = max(float(speed_rpm), 0.1)
        return max(60.0 / (rpm * configured_steps_per_rotation), DEFAULT_STEP_PULSE_SECONDS * 2.0)

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
        steps_per_rotation: int | None = None,
    ) -> bool:
        a_total = abs(a_steps)
        b_total = abs(b_steps)
        total = max(a_total, b_total)
        if total == 0:
            return False

        self._set_direction(gpio, pins.a_dir_pin, a_steps >= 0, "ROBOT_GPIO_A_DIR_INVERT")
        self._set_direction(gpio, pins.b_dir_pin, b_steps >= 0, "ROBOT_GPIO_B_DIR_INVERT")

        interval = self._step_interval_seconds(speed_rpm, steps_per_rotation)
        pulse = min(DEFAULT_STEP_PULSE_SECONDS, interval / 2.0)

        a_error = 0
        b_error = 0
        for _ in range(total):
            if stop_limit_pin is not None and self._limit_active(gpio, stop_limit_pin):
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

            if pulse_a:
                gpio.output(pins.a_step_pin, gpio.HIGH)
            if pulse_b:
                gpio.output(pins.b_step_pin, gpio.HIGH)
            time.sleep(pulse)
            if pulse_a:
                gpio.output(pins.a_step_pin, gpio.LOW)
            if pulse_b:
                gpio.output(pins.b_step_pin, gpio.LOW)
            time.sleep(max(0.0, interval - pulse))

        return stop_limit_pin is not None and self._limit_active(gpio, stop_limit_pin)

    def _probe_axis(
        self,
        gpio: Any,
        pins: _GPIOPinPlan,
        axis: str,
        direction: int,
        max_probe_steps: int,
        steps_per_rotation: int,
        fast_rpm: float,
        slow_rpm: float,
    ) -> None:
        limit_pin = self._axis_limit_pin(pins, axis, direction)
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
        )
        if not hit_fast:
            raise RuntimeError(f"{axis.upper()} {'max' if direction > 0 else 'min'} limit switch was not hit during fast calibration probe.")

        backoff_steps = -direction * max(1, steps_per_rotation // 4)
        self._move_corexy_steps(
            gpio,
            pins,
            backoff_steps,
            backoff_steps if axis == "x" else -backoff_steps,
            slow_rpm,
            steps_per_rotation=steps_per_rotation,
        )

        slow_probe_steps = direction * max(1, steps_per_rotation // 2)
        hit_slow = self._move_corexy_steps(
            gpio,
            pins,
            slow_probe_steps,
            slow_probe_steps if axis == "x" else -slow_probe_steps,
            slow_rpm,
            stop_limit_pin=limit_pin,
            steps_per_rotation=steps_per_rotation,
        )
        if not hit_slow:
            raise RuntimeError(f"{axis.upper()} {'max' if direction > 0 else 'min'} limit switch was not hit during slow calibration probe.")

    def _axis_limit_pin(self, pins: _GPIOPinPlan, axis: str, direction: int) -> int:
        if axis == "x":
            return pins.x_max_limit_pin if direction > 0 else pins.x_min_limit_pin
        if axis == "y":
            return pins.y_max_limit_pin if direction > 0 else pins.y_min_limit_pin
        raise ValueError(f"Unsupported calibration axis: {axis}")

    def _assert_limits_clear(self, gpio: Any, pins: _GPIOPinPlan, request: GantryXYMoveRequest) -> None:
        active_limits = []
        if self._limit_active(gpio, pins.x_min_limit_pin):
            active_limits.append("x_min")
        if self._limit_active(gpio, pins.x_max_limit_pin):
            active_limits.append("x_max")
        if self._limit_active(gpio, pins.y_min_limit_pin):
            active_limits.append("y_min")
        if self._limit_active(gpio, pins.y_max_limit_pin):
            active_limits.append("y_max")

        if active_limits:
            raise RuntimeError(
                "Limit switch active during gantry move; emergency stop required: "
                + ", ".join(active_limits)
            )

        if math.isnan(request.x_cm) or math.isnan(request.y_cm):
            raise RuntimeError("Invalid gantry move target.")

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
                "y_track_length_cm": request.y_track_length_cm,
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


def planned_calibrate_xy_result(context: dict, request: GantryXYCalibrationRequest) -> dict:
    return raspberry_gantry_gpio_service.calibrate_xy(context, request)


def planned_move_xy_result(context: dict, request: GantryXYMoveRequest) -> dict:
    return raspberry_gantry_gpio_service.move_xy(context, request)
