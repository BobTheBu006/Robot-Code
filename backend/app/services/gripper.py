"""Two hobby servos that open and close the gripper tool.

A hobby servo cannot report where it is: its first pulse makes it jump to the
commanded angle at full speed. So the service assumes the gripper starts where
it is parked in the rack - closed - sends that first, and ramps every later
move in small steps from the last angle it commanded. As long as the claws
really are closed when the tool is picked up, nothing ever snaps.

Pulses keep running after a move so the claws hold what they grip; a servo
without pulses goes limp. `release()` stops them, which is what a drop wants.

Pulses come from the Pi 5's PIO block through the `pwm-pio` overlay: hardware
timed, so the width does not wobble with CPU load. Software-timed pulses from
lgpio made the servos jitter visibly while holding; the PIO pulses did not
(measured on the gripper, 2026-10-27). lgpio stays as the fallback when the
overlay cannot be set up, and the result says which one ran.

GPIO 2/3 are the Pi's I2C1 pins, and with I2C enabled the kernel owns them,
so the PIO driver cannot claim them. Setting up detaches the I2C controller
from its pins; tearing down (on park, i.e. drop) removes the overlays and
reattaches I2C so the pogo pins are ordinary again for the next tool.
"""

from __future__ import annotations

import os
import subprocess
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


PWM_SYSFS = "/sys/class/pwm"
# The Pi 5's I2C1 controller (pins GPIO 2/3) and its platform driver.
I2C1_DEVICE = "1f00074000.i2c"
I2C1_DRIVER = "/sys/bus/platform/drivers/i2c_designware"


def _sudo(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "-n", *args], capture_output=True, text=True, timeout=10)


class PioPwmServos:
    """Hardware-timed servo pulses via one `pwm-pio` overlay per GPIO."""

    def __init__(self, run=_sudo, sysfs: str = PWM_SYSFS, i2c_driver: str = I2C1_DRIVER,
                 i2c_device: str = I2C1_DEVICE) -> None:
        self._run = run
        self._sysfs = sysfs
        self._i2c_driver = i2c_driver
        self._i2c_device = i2c_device
        self._channels: dict[int, str] = {}
        self._i2c_detached = False

    def _chip_for(self, gpio: int) -> str | None:
        if not os.path.isdir(self._sysfs):
            return None
        for name in sorted(os.listdir(self._sysfs)):
            device = os.path.realpath(os.path.join(self._sysfs, name, "device"))
            if device.endswith(f"pwm_pio@{gpio}"):
                return os.path.join(self._sysfs, name)
        return None

    def _check(self, result: subprocess.CompletedProcess, what: str) -> None:
        if result.returncode != 0:
            raise RuntimeError(f"{what} failed: {(result.stderr or result.stdout).strip()}")

    def _setup(self, gpio: int) -> str:
        chip = self._chip_for(gpio)
        if chip is None:
            if gpio in (2, 3) and os.path.exists(os.path.join(self._i2c_driver, self._i2c_device)):
                # The I2C driver holds the pins; the overlay would load and
                # then fail to claim them, leaving no PWM channel behind.
                self._check(self._run("sh", "-c", f"echo {self._i2c_device} > {self._i2c_driver}/unbind"),
                            "Detaching I2C from GPIO 2/3")
                self._i2c_detached = True
            self._check(self._run("dtoverlay", "pwm-pio", f"gpio={gpio}"), f"Loading pwm-pio on GPIO {gpio}")
            for _ in range(20):
                chip = self._chip_for(gpio)
                if chip:
                    break
                time.sleep(0.05)
            if chip is None:
                raise RuntimeError(f"pwm-pio did not create a PWM channel for GPIO {gpio}.")
        channel = os.path.join(chip, "pwm0")
        if not os.path.isdir(channel):
            self._check(self._run("sh", "-c", f"echo 0 > {chip}/export"), f"Exporting PWM for GPIO {gpio}")
            for _ in range(20):
                if os.path.isdir(channel):
                    break
                time.sleep(0.05)
        # One sudo for the permissions, so every later write - a ramp is tens
        # of them - is a plain file write instead of a process per step.
        self._check(self._run("chmod", "a+w", f"{channel}/period", f"{channel}/duty_cycle", f"{channel}/enable"),
                    f"Opening PWM controls for GPIO {gpio}")
        self._write(channel, "period", 1_000_000_000 // SERVO_FRAME_HZ)
        return channel

    @staticmethod
    def _write(channel: str, name: str, value: int) -> None:
        with open(os.path.join(channel, name), "w", encoding="ascii") as handle:
            handle.write(str(value))

    def pulse(self, gpio: int, width_us: int) -> None:
        channel = self._channels.get(gpio)
        if channel is None:
            channel = self._setup(gpio)
            self._channels[gpio] = channel
            self._write(channel, "duty_cycle", width_us * 1000)
            self._write(channel, "enable", 1)
            return
        self._write(channel, "duty_cycle", width_us * 1000)
        self._write(channel, "enable", 1)

    def stop(self) -> None:
        for channel in self._channels.values():
            try:
                self._write(channel, "enable", 0)
            except OSError:
                pass

    def teardown(self) -> None:
        """Stop, remove the overlays and give GPIO 2/3 back to I2C."""
        self.stop()
        listing = self._run("dtoverlay", "-l").stdout
        indexes = [line.split(":")[0].strip() for line in listing.splitlines() if "pwm-pio" in line]
        for index in reversed(indexes):
            self._run("dtoverlay", "-r", index)
        self._channels.clear()
        if self._i2c_detached:
            self._run("sh", "-c", f"echo {self._i2c_device} > {self._i2c_driver}/bind")
            self._i2c_detached = False


class _FallbackServos:
    """Hardware PWM when it can be set up, software pulses when it cannot."""

    def __init__(self) -> None:
        self.kind = "pio"
        self._driver = PioPwmServos()

    def pulse(self, gpio: int, width_us: int) -> None:
        try:
            self._driver.pulse(gpio, width_us)
        except (RuntimeError, OSError, subprocess.SubprocessError):
            if self.kind == "lgpio":
                raise
            # Loud in the result, not silent: the servos will jitter again.
            self._driver.teardown()
            self._driver = _LgpioServos()
            self.kind = "lgpio"
            self._driver.pulse(gpio, width_us)

    def stop(self) -> None:
        self._driver.stop()

    def teardown(self) -> None:
        if hasattr(self._driver, "teardown"):
            self._driver.teardown()
        else:
            self._driver.stop()


@dataclass
class SimulatedServos:
    pulses: dict[int, list[int]] = field(default_factory=dict)
    stopped: bool = False

    def pulse(self, gpio: int, width_us: int) -> None:
        self.stopped = False
        self.pulses.setdefault(gpio, []).append(width_us)

    def stop(self) -> None:
        self.stopped = True

    def teardown(self) -> None:
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
            self._driver = SimulatedServos() if _simulating() else _FallbackServos()
        return self._driver

    @property
    def pulse_source(self) -> str:
        """Which pulse generator is driving the servos: pio, lgpio or simulated."""
        return getattr(self._driver, "kind", "simulated" if isinstance(self._driver, SimulatedServos) else "unknown")

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
                # Also reassert a stationary target: release/cancel can have
                # stopped PWM since the last command at this same angle.
                driver.pulse(servo.gpio, servo.pulse_us(goals[servo.gpio]))
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
        with self._lock:
            if self._driver is not None and hasattr(self._driver, "teardown"):
                self._driver.teardown()
            elif self._driver is not None:
                self._driver.stop()
        self.forget_position()
        return True

    def forget_position(self) -> None:
        """After a drop the next pick-up starts again from 'parked closed'."""
        with self._lock:
            self._angles.clear()
            self._last = None


    def detach(self) -> None:
        """The tool is leaving the connector: stop driving the servos, hand
        GPIO 2/3 back, and start from 'parked closed' next time. No move."""
        with self._lock:
            if self._driver is not None:
                if hasattr(self._driver, "teardown"):
                    self._driver.teardown()
                else:
                    self._driver.stop()
            self._angles.clear()
            self._last = None


gripper_service = GripperService()

GRIPPER_SERVO_IDS = {"left": "gripper-left-servo", "right": "gripper-right-servo"}


def _block_defaults() -> dict:
    import json
    from pathlib import Path

    manifest = json.loads((Path(__file__).resolve().parents[1] / "functions/gripper/manifest.json").read_text())
    return {item["key"]: item.get("default") for item in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]}


def gripper_servos_for(group, hardware_map) -> list[ServoSettings] | None:
    """The two servo settings for a tool group, or None if it is not the gripper."""
    devices = {device.id: device for device in hardware_map.devices}
    if not all(device_id in group.member_ids and device_id in devices for device_id in GRIPPER_SERVO_IDS.values()):
        return None
    connector = next((c for c in hardware_map.connectors if c.id == group.connector_id), None)
    pin_gpio = {pin.name: pin.gpio for pin in connector.pins} if connector else {}
    defaults = _block_defaults()
    servos = []
    for side, device_id in GRIPPER_SERVO_IDS.items():
        signal = next((pin for pin in devices[device_id].pins if pin.signal == "signal"), None)
        if signal is None or signal.gpio == "-":
            return None
        gpio = pin_gpio.get(signal.gpio, signal.gpio)
        servos.append(ServoSettings(
            gpio=int(gpio),
            open_deg=float(defaults[f"{side}_open_deg"]),
            closed_deg=float(defaults[f"{side}_closed_deg"]),
            pulse_min_us=float(defaults[f"{side}_pulse_min_us"]),
            pulse_max_us=float(defaults[f"{side}_pulse_max_us"]),
        ))
    return servos


def _on_tool_connected(group, hardware_map) -> None:
    # A docked gripper sits closed in the rack: hold it there at once, so its
    # servos are never left without a defined pulse.
    servos = gripper_servos_for(group, hardware_map)
    if servos is None:
        return
    gripper_service.forget_position()
    gripper_service.move(servos, "close", float(_block_defaults()["ramp_deg_per_s"]))


def _on_tool_disconnected(group_id: str) -> None:
    gripper_service.detach()


def register_connector_hooks(connector_service=None) -> None:
    if connector_service is None:
        from app.services.pogo_connector import pogo_connector_service as connector_service
    connector_service.add_tool_hooks(_on_tool_connected, _on_tool_disconnected)
