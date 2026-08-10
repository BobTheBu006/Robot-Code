"""GPIO backend loader that works on every Raspberry Pi generation.

The gantry service is written against the RPi.GPIO API, but that library
cannot drive the Raspberry Pi 5: its GPIO lives on the new RP1 chip, and
RPi.GPIO fails there with "Cannot determine SOC peripheral base address".
Previously that failure was swallowed and the gantry silently fell back to
simulation, so workflows reported success while no motors moved.

load_gpio_backend() returns an object exposing the RPi.GPIO API subset the
gantry service uses, sourced from whichever backend actually works here:

1. RPi.GPIO itself — Raspberry Pi 4 and earlier, or any Pi where the
   drop-in rpi-lgpio shim is installed (it registers as RPi.GPIO).
2. LgpioBackend — a small adapter over the lgpio library, which supports
   the Pi 5's RP1 chip natively.
"""

import importlib
import os
from typing import Any


class LgpioBackend:
    """Minimal RPi.GPIO-compatible facade over the lgpio library.

    Only the API subset used by RaspberryGantryGPIOService is implemented:
    setwarnings/setmode (no-ops — lgpio always uses BCM numbering), setup,
    output, input, and cleanup.
    """

    BCM = "BCM"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0
    PUD_UP = "PUD_UP"
    PUD_DOWN = "PUD_DOWN"

    def __init__(self, lgpio: Any, handle: Any, chip: int) -> None:
        self._lgpio = lgpio
        self._handle = handle
        self.chip = chip
        self._claimed: set[int] = set()

    def setwarnings(self, _enabled: bool) -> None:
        return None

    def setmode(self, _mode: str) -> None:
        return None

    def setup(
        self,
        pin: int,
        direction: str,
        initial: int | None = None,
        pull_up_down: str | None = None,
    ) -> None:
        self._free_pin(pin)
        if direction == self.OUT:
            level = self.HIGH if initial == self.HIGH else self.LOW
            self._lgpio.gpio_claim_output(self._handle, pin, level)
        else:
            flags = 0
            if pull_up_down == self.PUD_UP:
                flags = self._lgpio.SET_PULL_UP
            elif pull_up_down == self.PUD_DOWN:
                flags = self._lgpio.SET_PULL_DOWN
            self._lgpio.gpio_claim_input(self._handle, pin, flags)
        self._claimed.add(pin)

    def output(self, pin: int, level: int) -> None:
        self._lgpio.gpio_write(self._handle, pin, 1 if level == self.HIGH else 0)

    def input(self, pin: int) -> int:
        return self.HIGH if self._lgpio.gpio_read(self._handle, pin) else self.LOW

    def cleanup(self, pins: list[int] | tuple[int, ...] | int | None = None) -> None:
        if pins is None:
            targets = list(self._claimed)
        elif isinstance(pins, int):
            targets = [pins]
        else:
            targets = list(pins)

        for pin in targets:
            self._free_pin(pin)

    def _free_pin(self, pin: int) -> None:
        if pin not in self._claimed:
            return
        try:
            self._lgpio.gpio_free(self._handle, pin)
        except Exception:
            pass
        self._claimed.discard(pin)


_lgpio_backend: LgpioBackend | None = None


def reset_gpio_backend_cache() -> None:
    global _lgpio_backend
    _lgpio_backend = None


def _load_rpi_gpio() -> tuple[Any | None, str | None]:
    try:
        gpio = importlib.import_module("RPi.GPIO")
    except Exception as exc:
        # Not just ImportError: the rpi-lgpio shim executes real code at import
        # time against whatever `lgpio` it finds, so a version skew between the
        # two raises AttributeError (e.g. missing `lgpio.SET_PULL_NONE`) rather
        # than failing to import. Letting that escape defeats the entire point
        # of this loader, which is to fall back to a backend that does work -
        # a pip upgrade on the Pi would take the gantry down instead of
        # quietly switching to the lgpio adapter below.
        return None, f"{type(exc).__name__}: {exc}"

    try:
        gpio.setwarnings(False)
        gpio.setmode(gpio.BCM)
        # Reading a pin's mode forces RPi.GPIO's deferred SoC detection, which
        # is what actually fails on a Raspberry Pi 5 ("Cannot determine SOC
        # peripheral base address") — probe it here instead of mid-move.
        gpio_function = getattr(gpio, "gpio_function", None)
        if callable(gpio_function):
            gpio_function(2)
        gpio.cleanup()
    except Exception as exc:
        return None, str(exc)

    return gpio, None


def _load_lgpio_backend() -> tuple[LgpioBackend | None, str | None]:
    global _lgpio_backend
    if _lgpio_backend is not None:
        return _lgpio_backend, None

    try:
        lgpio = importlib.import_module("lgpio")
    except ImportError as exc:
        return None, str(exc)

    chip_override = os.getenv("ROBOT_GPIO_LGPIO_CHIP")
    candidate_chips = [int(chip_override)] if chip_override else list(range(9))

    fallback: tuple[Any, int] | None = None
    for chip in candidate_chips:
        try:
            handle = lgpio.gpiochip_open(chip)
        except Exception:
            continue

        label = ""
        try:
            label = str(lgpio.gpio_get_chip_info(handle)[2])
        except Exception:
            pass

        # The 40-pin header lives on the pinctrl chip: pinctrl-rp1 on the
        # Pi 5, pinctrl-bcm2711/bcm2835 on earlier boards. On older Pi 5
        # kernels it is gpiochip4 while gpiochip0-3 are brcmstb chips, so
        # the label matters more than the number.
        if chip_override is not None or label.startswith("pinctrl-"):
            if fallback is not None:
                try:
                    lgpio.gpiochip_close(fallback[0])
                except Exception:
                    pass
            _lgpio_backend = LgpioBackend(lgpio, handle, chip)
            return _lgpio_backend, None

        if fallback is None:
            fallback = (handle, chip)
        else:
            try:
                lgpio.gpiochip_close(handle)
            except Exception:
                pass

    if fallback is not None:
        _lgpio_backend = LgpioBackend(lgpio, fallback[0], fallback[1])
        return _lgpio_backend, None

    return None, "lgpio is installed but no GPIO chip could be opened."


def load_gpio_backend() -> tuple[Any | None, str | None]:
    gpio, rpi_gpio_reason = _load_rpi_gpio()
    if gpio is not None:
        return gpio, None

    lgpio_backend, lgpio_reason = _load_lgpio_backend()
    if lgpio_backend is not None:
        return lgpio_backend, None

    return None, (
        f"RPi.GPIO is unavailable ({rpi_gpio_reason}) "
        f"and the lgpio fallback is unavailable ({lgpio_reason})."
    )
