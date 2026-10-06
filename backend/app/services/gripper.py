"""Two hobby servos that open and close the gripper tool.

A hobby servo cannot report where it is: its first pulse makes it jump to the
commanded angle at full speed. So the service assumes the gripper starts where
it is parked in the rack - closed - sends that first, and ramps every later
move in small steps from the last angle it commanded. As long as the claws
really are closed when the tool is picked up, nothing ever snaps.

Pulses keep running after a move so the claws hold what they grip; a servo
without pulses goes limp. `release()` stops them, which is what a drop wants.

Pulses come from lgpio, which times them in software on any GPIO. The PIO
based `pwm-pio` overlay would give hardware-timed pulses on the same pins;
switching is contained to `_LgpioServos`.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field

SERVO_FRAME_HZ = 50
RAMP_STEP_SECONDS = 0.02


@dataclass(frozen=True)
class ServoSettings:
    gpio: int
    open_deg: float
    closed_deg: float
    pulse_min_us: float = 500.0
    pulse_max_us: float = 2500.0

    def pulse_us(self, angle_deg: float) -> int:
        """-90..+90 deg mapped onto the pulse range, centre at its middle."""
        clamped = max(-90.0, min(90.0, angle_deg))
        span = self.pulse_max_us - self.pulse_min_us
        return round(self.pulse_min_us + (clamped + 90.0) / 180.0 * span)


class _LgpioServos:
    def __init__(self) -> None:
        import lgpio  # imported lazily: absent on development machines

        self._lgpio = lgpio
        self._handle = lgpio.gpiochip_open(0)
        self._claimed: set[int] = set()

    def pulse(self, gpio: int, width_us: int) -> None:
        if gpio not in self._claimed:
            self._lgpio.gpio_claim_output(self._handle, gpio, 0)
            self._claimed.add(gpio)
        self._lgpio.tx_servo(self._handle, gpio, width_us, SERVO_FRAME_HZ)

    def stop(self) -> None:
        for gpio in list(self._claimed):
            self._lgpio.tx_servo(self._handle, gpio, 0)
            self._lgpio.gpio_free(self._handle, gpio)
        self._claimed.clear()


@dataclass
class SimulatedServos:
    pulses: dict[int, list[int]] = field(default_factory=dict)
    stopped: bool = False

    def pulse(self, gpio: int, width_us: int) -> None:
        self.stopped = False
        self.pulses.setdefault(gpio, []).append(width_us)

    def stop(self) -> None:
        self.stopped = True


def _simulating() -> bool:
    return os.getenv("ROBOT_GPIO_SIMULATE", "").strip().lower() in {"1", "true", "yes", "on"}


class GripperService:
    def __init__(self, driver=None, sleep=time.sleep) -> None:
        self._driver = driver
        self._sleep = sleep
        self._lock = threading.Lock()
        # Last commanded angle per GPIO. Empty means "assume parked closed".
        self._angles: dict[int, float] = {}
        # What the last move used, so a drop can close the same servos.
        self._last: tuple[list[ServoSettings], float] | None = None

    def _servos(self):
        if self._driver is None:
            self._driver = SimulatedServos() if _simulating() else _LgpioServos()
        return self._driver

    def move(self, servos: list[ServoSettings], target: str, ramp_deg_per_s: float) -> dict[int, float]:
        """Ramp every servo to its open or closed angle together."""
        if target not in {"open", "close"}:
            raise ValueError(f"Unknown gripper action '{target}'; use open or close.")
        with self._lock:
            driver = self._servos()
            starts = {}
            for servo in servos:
                if servo.gpio not in self._angles:
                    # First pulse since start-up: the parked position, so a
                    # gripper that really is closed does not move.
                    self._angles[servo.gpio] = servo.closed_deg
                    driver.pulse(servo.gpio, servo.pulse_us(servo.closed_deg))
                starts[servo.gpio] = self._angles[servo.gpio]

            goals = {s.gpio: (s.open_deg if target == "open" else s.closed_deg) for s in servos}
            travel = max((abs(goals[g] - starts[g]) for g in goals), default=0.0)
            steps = max(1, round(travel / max(ramp_deg_per_s, 1.0) / RAMP_STEP_SECONDS)) if travel else 0
            for step in range(1, steps + 1):
                for servo in servos:
                    angle = starts[servo.gpio] + (goals[servo.gpio] - starts[servo.gpio]) * step / steps
                    driver.pulse(servo.gpio, servo.pulse_us(angle))
                self._sleep(RAMP_STEP_SECONDS)
            for servo in servos:
                self._angles[servo.gpio] = goals[servo.gpio]
            self._last = (list(servos), ramp_deg_per_s)
            return dict(self._angles)

    def release(self) -> None:
        """Stop the pulses; the servos go limp where they are."""
        with self._lock:
            if self._driver is not None:
                self._driver.stop()

    def park(self) -> bool:
        """Before the tool goes back in the rack: close, stop the pulses, and
        start from 'parked closed' again next time. A no-op when the gripper
        has not been used since start-up. Returns whether it did anything."""
        last = self._last
        if last is None:
            return False
        servos, ramp = last
        self.move(servos, "close", ramp)
        self.release()
        self.forget_position()
        return True

    def forget_position(self) -> None:
        """After a drop the next pick-up starts again from 'parked closed'."""
        with self._lock:
            self._angles.clear()
            self._last = None


gripper_service = GripperService()
