"""Physical facts about the machine, with an honest account of what is known.

The old toolhead store was two-valued: an index, or nothing. It was written
only *after* a pick-up sequence finished, so an emergency stop part way through
left it saying "nothing held" while a tool was physically hooked on the gantry.
The E-Stop route then forced it to ``None`` as well. The next pick-up trusted
that, skipped its automatic drop, and drove a loaded head into the rack.

A physical fact therefore has three states here, not two: known, uncertain, or
absent. Facts are written as *intent before motion* and confirmed after, so an
interrupted move leaves behind "I was engaging toolhead 3 and I do not know how
far it got" rather than a confident lie. Anything uncertain blocks rearming the
safety latch until an operator says what is actually there.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Any

from app.core.safety import StopRecord, UncertainFact, safety_controller

KNOWN = "known"
UNCERTAIN = "uncertain"

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _default_state_path() -> Path:
    # Overridable so tests never write into the operator's repository.
    override = os.getenv("ROBOT_PHYSICAL_STATE_FILE")
    return Path(override) if override else _REPO_ROOT / "physical-state.json"


_STATE_PATH = _default_state_path()
_LEGACY_TOOLHEAD_PATH = _REPO_ROOT / "toolhead-state.json"

STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FactAnswer:
    """One answer an operator can give, and the value it records."""

    label: str
    value: Any


@dataclass(frozen=True)
class FactDefinition:
    fact_id: str
    label: str
    question: str
    # The answers worth offering. Defined here rather than in the UI because
    # what "none" or "tool 3" means is machine knowledge, and an operator being
    # asked to type a value into a free-text box while a tool may be dangling
    # off the head is how the wrong answer gets recorded.
    answers: tuple[FactAnswer, ...] = ()
    # Value adopted the very first time a fact is read on a machine with no
    # recorded history. Only safe values belong here: with nothing having moved
    # yet there is no interrupted change to be uncertain about, and refusing to
    # run on a fresh install would just teach operators to ignore the guard.
    bootstrap_value: Any = None
    bootstrap_reason: str = "Initialised on first use; nothing had moved yet."


# Facts the machine tracks. Adding one here is all it takes for the safety
# latch to start gating on it.
FACT_DEFINITIONS: dict[str, FactDefinition] = {
    "toolhead.held": FactDefinition(
        fact_id="toolhead.held",
        label="Tool held by the gantry",
        question="Which toolhead is physically on the gantry right now?",
        answers=(
            FactAnswer(label="Nothing is on the head", value=None),
            *(FactAnswer(label=f"Tool {index} is on the head", value=index) for index in range(1, 7)),
        ),
        bootstrap_value=None,
        bootstrap_reason="No tool change has been performed since this machine's state was initialised.",
    ),
    "gantry.xy_calibrated": FactDefinition(
        fact_id="gantry.xy_calibrated",
        label="XY gantry calibration",
        question="Is the XY gantry still calibrated, or does it need re-homing before use?",
        answers=(
            FactAnswer(label="Still calibrated", value=True),
            FactAnswer(label="Needs re-homing", value=False),
        ),
        bootstrap_value=False,
        bootstrap_reason="The gantry has not been calibrated since this machine's state was initialised.",
    ),
    "z.position_known": FactDefinition(
        fact_id="z.position_known",
        label="Z axis position",
        question="Is the Z axis position still trustworthy, or does it need re-homing?",
        answers=(
            FactAnswer(label="Position is trustworthy", value=True),
            FactAnswer(label="Needs re-homing", value=False),
        ),
        bootstrap_value=False,
        bootstrap_reason="The Z axis has not been homed since this machine's state was initialised.",
    ),
}


@dataclass(frozen=True)
class Fact:
    fact_id: str
    value: Any
    certainty: str
    reason: str | None = None
    phase: str | None = None
    in_transition: bool = False
    updated_at: float = 0.0

    @property
    def is_known(self) -> bool:
        return self.certainty == KNOWN

    def to_json(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "certainty": self.certainty,
            "reason": self.reason,
            "phase": self.phase,
            "in_transition": self.in_transition,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, fact_id: str, payload: dict[str, Any]) -> "Fact":
        return cls(
            fact_id=fact_id,
            value=payload.get("value"),
            certainty=UNCERTAIN if payload.get("certainty") == UNCERTAIN else KNOWN,
            reason=payload.get("reason"),
            phase=payload.get("phase"),
            in_transition=bool(payload.get("in_transition", False)),
            updated_at=float(payload.get("updated_at") or 0.0),
        )


class PhysicalStateError(RuntimeError):
    pass


class PhysicalStateStore:
    """Durable, certainty-tracked physical facts.

    Persisted to disk rather than held in memory: a tool stays on the gantry
    across a backend restart, so losing the fact would recreate exactly the
    accident this module exists to prevent.
    """

    def __init__(
        self,
        state_path: Path | None = None,
        legacy_toolhead_path: Path = _LEGACY_TOOLHEAD_PATH,
    ) -> None:
        # Resolved per instance rather than captured at import, so a test that
        # sets ROBOT_PHYSICAL_STATE_FILE gets an isolated file.
        self._state_path = state_path if state_path is not None else _default_state_path()
        self._legacy_toolhead_path = legacy_toolhead_path
        self._lock = RLock()

    # ---- persistence -----------------------------------------------------

    def _read_all(self) -> dict[str, Fact]:
        if not self._state_path.exists():
            return self._migrate_legacy()

        try:
            with self._state_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            # An unreadable state file is not a reason to claim the machine is
            # empty; treat every tracked fact as uncertain instead.
            return {
                definition.fact_id: Fact(
                    fact_id=definition.fact_id,
                    value=None,
                    certainty=UNCERTAIN,
                    reason="The saved physical state file could not be read.",
                    updated_at=time.time(),
                )
                for definition in FACT_DEFINITIONS.values()
            }

        raw_facts = payload.get("facts") or {}
        return {
            fact_id: Fact.from_json(fact_id, fact_payload)
            for fact_id, fact_payload in raw_facts.items()
            if isinstance(fact_payload, dict)
        }

    def _migrate_legacy(self) -> dict[str, Fact]:
        """Adopt the old two-valued toolhead file on first run.

        The legacy value is imported as *uncertain*: it was written by code
        that could not distinguish "dropped cleanly" from "stopped mid-drop",
        so it has not earned being trusted.
        """
        if not self._legacy_toolhead_path.exists():
            return {}

        try:
            with self._legacy_toolhead_path.open("r", encoding="utf-8") as handle:
                legacy = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return {}

        held_index = legacy.get("held_index")
        return {
            "toolhead.held": Fact(
                fact_id="toolhead.held",
                value=held_index if isinstance(held_index, int) else None,
                certainty=UNCERTAIN,
                reason="Imported from the previous toolhead state file, which did not track certainty.",
                updated_at=time.time(),
            )
        }

    def _write_all(self, facts: dict[str, Fact]) -> None:
        payload = {
            "schema_version": STATE_SCHEMA_VERSION,
            "updated_at": time.time(),
            "facts": {fact_id: fact.to_json() for fact_id, fact in sorted(facts.items())},
        }
        temp_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        temp_path.replace(self._state_path)

    # ---- reading ---------------------------------------------------------

    def _bootstrap(self, fact_id: str) -> Fact | None:
        definition = FACT_DEFINITIONS.get(fact_id)
        if definition is None:
            return None
        return self.set_known(
            fact_id, definition.bootstrap_value, reason=definition.bootstrap_reason
        )

    def get(self, fact_id: str) -> Fact | None:
        with self._lock:
            fact = self._read_all().get(fact_id)
            if fact is not None:
                return fact
            return self._bootstrap(fact_id)

    def all_facts(self) -> dict[str, Fact]:
        with self._lock:
            facts = self._read_all()
            for fact_id in FACT_DEFINITIONS:
                if fact_id not in facts:
                    bootstrapped = self._bootstrap(fact_id)
                    if bootstrapped is not None:
                        facts[fact_id] = bootstrapped
            return facts

    def require_known(self, fact_id: str) -> Fact:
        """Read a fact that must be trustworthy before acting on it."""
        fact = self.get(fact_id)
        definition = FACT_DEFINITIONS.get(fact_id)
        label = definition.label if definition else fact_id

        if fact is None:
            raise PhysicalStateError(
                f"{label} has never been established. Confirm it before running this step."
            )
        if not fact.is_known:
            raise PhysicalStateError(
                f"{label} is uncertain ({fact.reason or 'a fault interrupted the last change'}). "
                "Confirm the physical state before running this step."
            )
        return fact

    # ---- writing ---------------------------------------------------------

    def set_known(self, fact_id: str, value: Any, *, reason: str | None = None) -> Fact:
        with self._lock:
            facts = self._read_all()
            fact = Fact(
                fact_id=fact_id,
                value=value,
                certainty=KNOWN,
                reason=reason,
                phase=None,
                in_transition=False,
                updated_at=time.time(),
            )
            facts[fact_id] = fact
            self._write_all(facts)
            return fact

    def mark_uncertain(self, fact_id: str, *, reason: str, value: Any = None) -> Fact:
        with self._lock:
            facts = self._read_all()
            previous = facts.get(fact_id)
            fact = Fact(
                fact_id=fact_id,
                # Keep whatever the last believed value was: "possibly holding
                # tool 3" is far more useful to an operator than "unknown".
                value=value if value is not None else (previous.value if previous else None),
                certainty=UNCERTAIN,
                reason=reason,
                phase=previous.phase if previous else None,
                in_transition=False,
                updated_at=time.time(),
            )
            facts[fact_id] = fact
            self._write_all(facts)
            return fact

    def begin_transition(self, fact_id: str, *, provisional_value: Any, phase: str) -> Fact:
        """Record what is about to happen, before the motion starts.

        This is the half that was missing. If the move is interrupted, the
        stop observer below turns this into an uncertain fact carrying the
        provisional value, so the machine knows it might be holding something.
        """
        with self._lock:
            facts = self._read_all()
            fact = Fact(
                fact_id=fact_id,
                value=provisional_value,
                certainty=UNCERTAIN,
                reason=f"Change in progress: {phase}.",
                phase=phase,
                in_transition=True,
                updated_at=time.time(),
            )
            facts[fact_id] = fact
            self._write_all(facts)
            return fact

    def commit_transition(self, fact_id: str, value: Any) -> Fact:
        """The motion finished cleanly; the intended value is now the truth."""
        return self.set_known(fact_id, value)

    def abort_transition(self, fact_id: str, *, reason: str) -> Fact:
        """The motion failed for a reason that does not make the fact unknowable."""
        with self._lock:
            facts = self._read_all()
            previous = facts.get(fact_id)
            if previous is None or not previous.in_transition:
                return previous or self.mark_uncertain(fact_id, reason=reason)
            return self.mark_uncertain(fact_id, reason=reason, value=previous.value)

    def confirm(self, fact_id: str, value: Any, *, operator: str = "operator") -> Fact:
        """An operator looked at the machine and said what is actually there."""
        if fact_id not in FACT_DEFINITIONS:
            raise PhysicalStateError(f"Unknown physical fact '{fact_id}'.")
        return self.set_known(fact_id, value, reason=f"Confirmed by {operator}.")

    # ---- safety integration ---------------------------------------------

    def uncertain_facts(self) -> list[UncertainFact]:
        facts = self.all_facts()
        outstanding: list[UncertainFact] = []
        for fact_id, fact in sorted(facts.items()):
            if fact.is_known:
                continue
            definition = FACT_DEFINITIONS.get(fact_id)
            outstanding.append(
                UncertainFact(
                    fact_id=fact_id,
                    label=definition.label if definition else fact_id,
                    reason=fact.reason or "A fault interrupted the last change to this value.",
                    suggested_question=(
                        definition.question if definition else f"What is the current value of {fact_id}?"
                    ),
                    answers=tuple(
                        {"label": answer.label, "value": answer.value}
                        for answer in (definition.answers if definition else ())
                    ),
                )
            )
        return outstanding

    def on_stop(self, record: StopRecord) -> None:
        """Everything that was mid-change when the stop landed is now unknown.

        Facts that were settled stay known: an E-Stop pressed while the machine
        is idle must not invalidate a toolhead that is sitting safely in its
        slot.
        """
        with self._lock:
            facts = self._read_all()
            changed = False
            for fact_id, fact in list(facts.items()):
                if not fact.in_transition:
                    continue
                facts[fact_id] = replace(
                    fact,
                    certainty=UNCERTAIN,
                    in_transition=False,
                    reason=(
                        f"Stopped during '{fact.phase or 'a change'}' ({record.reason}). "
                        "The move may have completed partially."
                    ),
                    updated_at=time.time(),
                )
                changed = True

            if changed:
                self._write_all(facts)


physical_state_store = PhysicalStateStore()

safety_controller.register_uncertainty_source("physical_state", physical_state_store.uncertain_facts)
safety_controller.register_stop_observer(physical_state_store.on_stop)
