"""Turn motor drivers on only while they are being used.

Idle steppers hold full current and get hot for no reason, so the drivers sit
disabled until something actually wants to move. Two rules make that practical:

**Enable early.** A driver is asserted and then left for a settle delay before
the first step, so the supply sees the current draw ramp rather than a step
change coincident with motion. Stepping into a driver that has just been
energised is how you get a stall on the first move.

**Do not power down between blocks.** Releasing does not cut power; it starts a
linger timer. A workflow that moves the gantry in five blocks in a row keeps it
enabled throughout and pays the settle delay once, at the start. Power only
drops once nothing has wanted the motors for the whole linger window.

Linger is used rather than looking ahead in the workflow on purpose: with
branches and loops, "the next block" is not known until conditions are
evaluated, and a lookahead that guesses wrong either cuts power mid-sequence or
holds it forever. A timer is right in both cases without needing to predict.

Domains, not individual motors: one GPIO enables every driver wired to it. On
this machine that is all seven drivers on the Z/pump ESP32 sharing one line, and
the two CoreXY drivers sharing another.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

# Long enough for the supply to settle and the driver to come out of standby,
# short enough not to be felt between blocks. Only paid on an off -> on edge.
DEFAULT_SETTLE_SECONDS = 1.0

# How long power stays on after the last release. Covers the gap between
# consecutive blocks - a block boundary is milliseconds, not seconds.
DEFAULT_LINGER_SECONDS = 3.0


@dataclass
class PowerDomain:
    """A set of drivers sharing one enable line."""

    domain_id: str
    description: str
    apply: Callable[[bool], None]
    settle_seconds: float = DEFAULT_SETTLE_SECONDS
    linger_seconds: float = DEFAULT_LINGER_SECONDS

    powered: bool = False
    holders: int = 0
    release_at: float | None = None
    last_error: str | None = None
    _timer: threading.Timer | None = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {
            "domain_id": self.domain_id,
            "description": self.description,
            "powered": self.powered,
            "holders": self.holders,
            "lingering": self.powered and self.holders == 0,
            "last_error": self.last_error,
        }


class MotorPowerService:
    def __init__(self) -> None:
        self._domains: dict[str, PowerDomain] = {}
        self._lock = threading.RLock()

    # ---- registration ----

    def register(
        self,
        domain_id: str,
        description: str,
        apply: Callable[[bool], None],
        *,
        settle_seconds: float = DEFAULT_SETTLE_SECONDS,
        linger_seconds: float = DEFAULT_LINGER_SECONDS,
    ) -> PowerDomain:
        """Declare an enable line and how to drive it.

        `apply(True)` energises, `apply(False)` cuts power. Re-registering
        replaces the callable but keeps the current power state, so reloading a
        driver does not silently drop a domain that is mid-move.
        """
        with self._lock:
            existing = self._domains.get(domain_id)
            if existing is not None:
                existing.apply = apply
                existing.description = description
                existing.settle_seconds = settle_seconds
                existing.linger_seconds = linger_seconds
                return existing

            domain = PowerDomain(
                domain_id=domain_id,
                description=description,
                apply=apply,
                settle_seconds=settle_seconds,
                linger_seconds=linger_seconds,
            )
            self._domains[domain_id] = domain
            return domain

    def is_registered(self, domain_id: str) -> bool:
        with self._lock:
            return domain_id in self._domains

    # ---- the pair callers use ----

    def acquire(self, domain_id: str, *, settle: bool = True) -> None:
        """Energise the drivers and wait for them to settle before stepping.

        The settle delay is only paid when power was actually off. Back-to-back
        blocks find it already on and start immediately.
        """
        with self._lock:
            domain = self._domains.get(domain_id)
            if domain is None:
                return

            self._cancel_timer(domain)
            domain.holders += 1
            domain.release_at = None

            if domain.powered:
                return

            try:
                domain.apply(True)
                domain.powered = True
                domain.last_error = None
            except Exception as exc:  # a driver that cannot be enabled must be loud
                domain.holders -= 1
                domain.last_error = f"{type(exc).__name__}: {exc}"
                raise

            wait = domain.settle_seconds

        # Deliberately outside the lock: a one second sleep holding the lock
        # would serialise every other domain behind this one.
        if settle and wait > 0:
            time.sleep(wait)

    def release(self, domain_id: str) -> None:
        """Done with the drivers - but leave them on for now.

        This is what stops a run power-cycling the motors between every block.
        """
        with self._lock:
            domain = self._domains.get(domain_id)
            if domain is None:
                return

            domain.holders = max(0, domain.holders - 1)
            if domain.holders > 0 or not domain.powered:
                return

            self._schedule_power_down(domain)

    def power_down_now(self, domain_id: str | None = None) -> None:
        """Cut power immediately, ignoring holders and the linger timer.

        For the end of a run and for E-Stop: when everything has stopped there
        is no reason to keep drivers hot waiting out a timer.
        """
        with self._lock:
            domains = (
                list(self._domains.values())
                if domain_id is None
                else [d for d in [self._domains.get(domain_id)] if d is not None]
            )
            for domain in domains:
                self._cancel_timer(domain)
                domain.holders = 0
                domain.release_at = None
                if not domain.powered:
                    continue
                try:
                    domain.apply(False)
                    domain.powered = False
                    domain.last_error = None
                except Exception as exc:
                    # Never raise out of a stop path; record it and move on so
                    # one stuck domain cannot block the rest from powering off.
                    domain.last_error = f"{type(exc).__name__}: {exc}"

    # ---- internals ----

    def _schedule_power_down(self, domain: PowerDomain) -> None:
        domain.release_at = time.monotonic() + domain.linger_seconds
        timer = threading.Timer(domain.linger_seconds, self._linger_expired, args=(domain.domain_id,))
        timer.daemon = True
        domain._timer = timer
        timer.start()

    def _linger_expired(self, domain_id: str) -> None:
        with self._lock:
            domain = self._domains.get(domain_id)
            # Something asked for the motors again while the timer was running.
            if domain is None or domain.holders > 0 or not domain.powered:
                return
            try:
                domain.apply(False)
                domain.powered = False
                domain.last_error = None
            except Exception as exc:
                domain.last_error = f"{type(exc).__name__}: {exc}"
            domain.release_at = None
            domain._timer = None

    def _cancel_timer(self, domain: PowerDomain) -> None:
        if domain._timer is not None:
            domain._timer.cancel()
            domain._timer = None

    # ---- reporting ----

    def snapshot(self) -> dict:
        with self._lock:
            return {"domains": [domain.as_dict() for domain in self._domains.values()]}


class powered_motors:  # noqa: N801 - used as a context manager, reads as one
    """`with powered_motors("pi.gantry"):` around anything that steps."""

    def __init__(self, domain_id: str, *, settle: bool = True) -> None:
        self.domain_id = domain_id
        self.settle = settle

    def __enter__(self) -> "powered_motors":
        motor_power_service.acquire(self.domain_id, settle=self.settle)
        return self

    def __exit__(self, *_exc) -> None:
        motor_power_service.release(self.domain_id)
        return None


motor_power_service = MotorPowerService()


def _power_down_after_stop(_record) -> None:
    """Drop motor power once an E-Stop has finished halting everything.

    Registered as a stop *observer* rather than a stoppable actor on purpose:
    observers run after every actor has aborted, so motion is already stopped
    and each driver has recorded how far it actually travelled. Cutting power
    as an actor would race that bookkeeping, and losing the travelled count is
    exactly the "E-Stop destroys the position" problem this machine already had
    once. Coming back from a stop costs up to one step of drift, which is
    accepted here - the lead screws hold Z, and CoreXY carries no gravity load.
    """
    motor_power_service.power_down_now()


def register_safety_hooks() -> None:
    """Wire power-down into the E-Stop path. Called once at startup."""
    from app.core.safety import safety_controller

    safety_controller.register_stop_observer(_power_down_after_stop)

# Domain ids, so callers are not passing strings around by hand.
GANTRY_XY_DOMAIN = "pi.gantry-xy"
Z_PUMP_DOMAIN = "esp32.controller-ykkl80"
