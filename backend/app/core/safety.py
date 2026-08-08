"""The single authority over whether the machine is allowed to move.

Before this existed, five services each owned a private stop flag and the
E-Stop route fanned out to all of them by hand. ``/rearm`` cleared two of the
five. Whether motion was actually blocked depended on which service you asked,
and starting any new work implicitly cleared the latch - so E-Stop was
advisory, not a latch.

Here there is exactly one flag. ``motion_blocked`` is a ``threading.Event``
shared by every driver that steps a motor, so a hot stepping loop and an HTTP
request consult the same boolean. Actors register to be told to stop; the flag
is set *before* any of them are called, so a driver aborts on its next step
check even when a serial write to some other controller blocks for seconds.

This module deliberately imports nothing from ``app`` - every other layer may
depend on it, so it must never depend back.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Event, RLock
from typing import Callable, Protocol, runtime_checkable

# Actors are stopped lowest-priority-number first. Actors that only set an
# in-process flag return instantly and belong at the front; actors that talk
# over a serial port can block, so they go last and never delay the others.
PRIORITY_FLAG = 0
PRIORITY_PROCESS = 50
PRIORITY_SERIAL = 100


class SafetyState(str, Enum):
    ARMED = "armed"
    """Motion is allowed."""

    STOPPING = "stopping"
    """A stop is being fanned out to the registered actors right now."""

    LATCHED = "latched"
    """A stop completed. Motion stays blocked until an explicit rearm."""

    RECOVERING = "recovering"
    """Rearm was requested but some physical fact is still unconfirmed."""


class MotionBlockedError(RuntimeError):
    """Raised when motion is attempted while the safety latch is engaged."""


@runtime_checkable
class StoppableActor(Protocol):
    """Anything that can produce motion and therefore must be stoppable."""

    @property
    def actor_id(self) -> str: ...

    def stop(self) -> dict[str, object]:
        """Halt this actor now. Must not raise; report failure in the dict."""


@dataclass(frozen=True)
class ActorStopReport:
    actor_id: str
    ok: bool
    message: str
    duration_ms: float
    detail: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class StopRecord:
    """What happened the last time a stop fired."""

    reason: str
    source: str
    at: float
    reports: tuple[ActorStopReport, ...]

    @property
    def ok(self) -> bool:
        return all(report.ok for report in self.reports)


@dataclass(frozen=True)
class UncertainFact:
    """A physical fact a fault made unknowable.

    Reported by whoever owns the fact. Rearm is refused while any of these are
    outstanding, because guessing is what drove a held toolhead into the rack.
    """

    fact_id: str
    label: str
    reason: str
    suggested_question: str


# A source returns the facts it currently cannot vouch for.
UncertaintySource = Callable[[], list[UncertainFact]]

# Observers are notified after a stop has been fanned out, so they can record
# that whatever they were doing is no longer trustworthy.
StopObserver = Callable[[StopRecord], None]


@dataclass
class _RegisteredActor:
    actor: StoppableActor
    priority: int
    description: str


class SafetyController:
    def __init__(self) -> None:
        self._lock = RLock()
        # Set == motion forbidden. Shared by reference with every driver, so
        # there is one boolean rather than five.
        self._motion_blocked = Event()
        self._state = SafetyState.ARMED
        self._actors: dict[str, _RegisteredActor] = {}
        self._uncertainty_sources: dict[str, UncertaintySource] = {}
        self._stop_observers: list[StopObserver] = []
        self._last_stop: StopRecord | None = None
        # Bumped on every rearm. A run captures this at start and treats a
        # change as "my run was stopped out from under me", which is what makes
        # an interrupted run non-resumable by accident.
        self._generation = 0

    # ---- the shared flag -------------------------------------------------

    @property
    def motion_blocked(self) -> Event:
        """The one Event every motion driver checks.

        Handed out by reference on purpose: drivers store it once and poll it
        inside their stepping loops, so a stop takes effect within one step
        period without any cross-service call.
        """
        return self._motion_blocked

    def is_blocked(self) -> bool:
        return self._motion_blocked.is_set()

    def raise_if_blocked(self, action: str = "Motion") -> None:
        if self._motion_blocked.is_set():
            raise MotionBlockedError(
                f"{action} is blocked by an engaged emergency stop. "
                "Clear it from the operator UI once the machine is safe."
            )

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def state(self) -> SafetyState:
        with self._lock:
            return self._state

    # ---- registration ----------------------------------------------------

    def register_actor(
        self,
        actor: StoppableActor,
        *,
        priority: int = PRIORITY_SERIAL,
        description: str = "",
    ) -> None:
        with self._lock:
            self._actors[actor.actor_id] = _RegisteredActor(
                actor=actor,
                priority=priority,
                description=description or actor.actor_id,
            )

    def unregister_actor(self, actor_id: str) -> None:
        with self._lock:
            self._actors.pop(actor_id, None)

    def register_uncertainty_source(self, source_id: str, source: UncertaintySource) -> None:
        with self._lock:
            self._uncertainty_sources[source_id] = source

    def register_stop_observer(self, observer: StopObserver) -> None:
        with self._lock:
            self._stop_observers.append(observer)

    # ---- the stop itself -------------------------------------------------

    def stop(self, *, reason: str, source: str) -> StopRecord:
        """Engage the latch and halt every registered actor.

        The flag is set first and the state is published before any actor is
        called, so a driver mid-move aborts on its next step check even if the
        actor fan-out below blocks on a busy serial port.
        """
        with self._lock:
            self._motion_blocked.set()
            self._state = SafetyState.STOPPING
            registered = sorted(self._actors.values(), key=lambda item: (item.priority, item.actor.actor_id))
            observers = list(self._stop_observers)

        reports: list[ActorStopReport] = []
        for entry in registered:
            started = time.perf_counter()
            try:
                result = entry.actor.stop() or {}
                reports.append(
                    ActorStopReport(
                        actor_id=entry.actor.actor_id,
                        ok=bool(result.get("ok", True)),
                        message=str(result.get("message", "Stopped.")),
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                        detail={key: value for key, value in result.items() if key not in {"ok", "message"}},
                    )
                )
            except Exception as exc:
                # An actor that throws must not prevent the remaining actors
                # from being stopped - that is the whole point of the fan-out.
                reports.append(
                    ActorStopReport(
                        actor_id=entry.actor.actor_id,
                        ok=False,
                        message=f"Stop failed: {exc}",
                        duration_ms=(time.perf_counter() - started) * 1000.0,
                    )
                )

        record = StopRecord(reason=reason, source=source, at=time.time(), reports=tuple(reports))

        with self._lock:
            self._last_stop = record
            self._state = SafetyState.LATCHED

        for observer in observers:
            try:
                observer(record)
            except Exception:
                # Observers only record consequences; one failing must not
                # affect whether the machine actually stopped.
                pass

        return record

    # ---- recovery --------------------------------------------------------

    def unconfirmed_facts(self) -> list[UncertainFact]:
        with self._lock:
            sources = list(self._uncertainty_sources.values())

        facts: list[UncertainFact] = []
        for source in sources:
            try:
                facts.extend(source())
            except Exception:
                pass
        return facts

    def rearm(self, *, operator: str = "operator") -> dict[str, object]:
        """Clear the latch, but only once nothing is left unknowable.

        Refusing here is the point. After a stop mid tool-change nobody knows
        what is on the gantry, and the old code answered that question by
        guessing "nothing".
        """
        outstanding = self.unconfirmed_facts()
        if outstanding:
            with self._lock:
                self._state = SafetyState.RECOVERING
            return {
                "ok": False,
                "state": SafetyState.RECOVERING.value,
                "message": (
                    "Cannot clear the emergency stop yet: "
                    f"{len(outstanding)} physical fact(s) need confirming first."
                ),
                "requires_confirmation": [
                    {
                        "fact_id": fact.fact_id,
                        "label": fact.label,
                        "reason": fact.reason,
                        "question": fact.suggested_question,
                    }
                    for fact in outstanding
                ],
            }

        with self._lock:
            self._motion_blocked.clear()
            self._state = SafetyState.ARMED
            self._generation += 1
            generation = self._generation

        return {
            "ok": True,
            "state": SafetyState.ARMED.value,
            "generation": generation,
            "operator": operator,
            "message": "Emergency stop cleared. Motion is allowed again.",
            "requires_confirmation": [],
        }

    # ---- reporting -------------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            state = self._state
            generation = self._generation
            last_stop = self._last_stop
            actors = [
                {"actor_id": entry.actor.actor_id, "description": entry.description, "priority": entry.priority}
                for entry in sorted(self._actors.values(), key=lambda item: (item.priority, item.actor.actor_id))
            ]

        outstanding = self.unconfirmed_facts()
        return {
            "state": state.value,
            "motion_blocked": self._motion_blocked.is_set(),
            "generation": generation,
            "registered_actors": actors,
            "requires_confirmation": [
                {
                    "fact_id": fact.fact_id,
                    "label": fact.label,
                    "reason": fact.reason,
                    "question": fact.suggested_question,
                }
                for fact in outstanding
            ],
            "last_stop": (
                None
                if last_stop is None
                else {
                    "reason": last_stop.reason,
                    "source": last_stop.source,
                    "at": last_stop.at,
                    "ok": last_stop.ok,
                    "reports": [
                        {
                            "actor_id": report.actor_id,
                            "ok": report.ok,
                            "message": report.message,
                            "duration_ms": round(report.duration_ms, 3),
                            **report.detail,
                        }
                        for report in last_stop.reports
                    ],
                }
            ),
        }


safety_controller = SafetyController()


@dataclass
class CallableActor:
    """Adapter for services that already expose a stop-shaped method."""

    actor_id: str
    _stop: Callable[[], dict[str, object] | list[dict[str, object]] | None]

    def stop(self) -> dict[str, object]:
        result = self._stop()
        if result is None:
            return {"ok": True, "message": "Stopped."}
        if isinstance(result, list):
            # Services that own several sessions return one dict per session.
            return {
                "ok": all(bool(item.get("ok", True)) for item in result),
                "message": "; ".join(str(item.get("message", "")) for item in result) or "Stopped.",
                "sessions": result,
            }
        return result
