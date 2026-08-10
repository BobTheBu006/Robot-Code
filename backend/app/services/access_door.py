"""Access door interlock.

A limit switch on the robot's access door: the switch is closed while the door
is closed, so with an internal pull-up the pin reads LOW for a closed door and
HIGH for an open one.

The door gates *runs*, not all motion. Testing a single block with the door
open is how the machine gets brought up and diagnosed - that has to keep
working, and the operator is standing there by definition. Starting a whole
workflow is different: nobody is necessarily watching, so it needs the door
shut, or a deliberate override.

Deliberately separate from the E-Stop latch in `core.safety`. The latch is
about "someone stopped the machine and the physical state may be unknown"; the
door is a precondition checked before a run and watched during it. Folding the
two together would mean an open door left the machine in RECOVERING, demanding
a physical-state confirmation that has nothing to do with the door.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.services.gpio_backend import load_gpio_backend

DEFAULT_DOOR_PIN = 13
# Poll interval while a run is in progress. Fast enough that the door is caught
# within a fraction of a second, slow enough to be invisible on the CPU.
WATCH_INTERVAL_SECONDS = 0.2


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AccessDoorState:
    is_open: bool | None
    """True/False, or None when the door cannot be read at all."""

    pin: int
    detected: bool
    """False when no GPIO backend is available, so the reading is unknown."""

    override_active: bool
    reason: str

    @property
    def blocks_run(self) -> bool:
        # An unreadable door does not block: a machine with no GPIO backend
        # (or no switch fitted) must still be usable. It is reported as
        # undetected so the UI can say so rather than implying "closed".
        if self.override_active or self.is_open is None:
            return False
        return self.is_open

    def to_dict(self) -> dict[str, object]:
        return {
            "is_open": self.is_open,
            "pin": self.pin,
            "detected": self.detected,
            "override_active": self.override_active,
            "blocks_run": self.blocks_run,
            "reason": self.reason,
        }


class AccessDoorSensor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gpio: Any = None
        self._configured_pin: int | None = None
        self._override = False
        self._watch_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()

    # ---- configuration ----
    @property
    def pin(self) -> int:
        return int(os.getenv("ROBOT_ACCESS_DOOR_PIN", str(DEFAULT_DOOR_PIN)))

    def _door_closed_is_low(self) -> bool:
        """Switch closed pulls the pin to ground, so LOW means door closed."""
        return _bool_env("ROBOT_ACCESS_DOOR_CLOSED_ACTIVE_LOW", True)

    # ---- reading ----
    def _ensure_pin(self) -> Any:
        if self._gpio is not None and self._configured_pin == self.pin:
            return self._gpio

        gpio, _reason = load_gpio_backend()
        if gpio is None:
            return None

        try:
            gpio.setwarnings(False)
            gpio.setmode(gpio.BCM)
            gpio.setup(self.pin, gpio.IN, pull_up_down=gpio.PUD_UP)
        except Exception:
            return None

        self._gpio = gpio
        self._configured_pin = self.pin
        return gpio

    def read(self) -> AccessDoorState:
        with self._lock:
            gpio = self._ensure_pin()
            pin = self.pin
            override = self._override

        if gpio is None:
            return AccessDoorState(
                is_open=None,
                pin=pin,
                detected=False,
                override_active=override,
                reason=(
                    "No GPIO backend is available, so the access door cannot be read. "
                    "Runs are allowed; fit the switch or check the GPIO install to enforce it."
                ),
            )

        try:
            level = gpio.input(pin)
        except Exception as exc:
            return AccessDoorState(
                is_open=None,
                pin=pin,
                detected=False,
                override_active=override,
                reason=f"Could not read the access door on GPIO {pin}: {exc}",
            )

        closed = (level == gpio.LOW) if self._door_closed_is_low() else (level == gpio.HIGH)
        is_open = not closed

        if is_open and override:
            reason = (
                f"The access door is OPEN (GPIO {pin}), but the access interlock is "
                "overridden, so runs are allowed."
            )
        elif is_open:
            reason = (
                f"The access door is OPEN (GPIO {pin}). Close it to run a workflow, or "
                "override the interlock deliberately. Testing a single block is still allowed."
            )
        else:
            reason = f"The access door is closed (GPIO {pin})."

        return AccessDoorState(
            is_open=is_open,
            pin=pin,
            detected=True,
            override_active=override,
            reason=reason,
        )

    # ---- override ----
    def set_override(self, enabled: bool) -> AccessDoorState:
        """Allow runs with the door open.

        Not persisted: an override is a decision about the situation in front
        of the operator right now, and it must not silently survive a restart
        into a session where nobody chose it.
        """
        with self._lock:
            self._override = bool(enabled)
        return self.read()

    @property
    def override_active(self) -> bool:
        with self._lock:
            return self._override

    # ---- watching during a run ----
    def start_watching(self, on_open) -> None:
        """Watch the door for the duration of a run.

        The door is only an interlock while a workflow is running; polling it
        the rest of the time would stop the machine whenever someone reached
        in to work on it, which is exactly when block testing is wanted.
        """
        self.stop_watching()
        self._watch_stop.clear()

        def loop() -> None:
            while not self._watch_stop.wait(WATCH_INTERVAL_SECONDS):
                state = self.read()
                if state.blocks_run:
                    try:
                        on_open(state)
                    except Exception:
                        pass
                    return

        thread = threading.Thread(target=loop, name="access-door-watch", daemon=True)
        self._watch_thread = thread
        thread.start()

    def stop_watching(self) -> None:
        self._watch_stop.set()
        thread = self._watch_thread
        self._watch_thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)


access_door_sensor = AccessDoorSensor()
