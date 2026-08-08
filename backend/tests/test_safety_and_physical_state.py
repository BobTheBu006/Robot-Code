"""Regression tests for the two defects that made E-Stop unpredictable.

1. Five services each owned a private stop flag and `/rearm` cleared two, so
   whether the machine was blocked depended on which one you asked.
2. The held toolhead was written only after a pick-up finished, and the E-Stop
   route then forced it to None - so a stop mid-change reported an empty head
   while a tool was physically on the gantry, and the next pick-up skipped its
   automatic drop.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.safety import (
    PRIORITY_FLAG,
    PRIORITY_SERIAL,
    CallableActor,
    SafetyController,
    SafetyState,
)
from app.services.physical_state import KNOWN, UNCERTAIN, PhysicalStateError, PhysicalStateStore

_MODULE_STATE_DIR: tempfile.TemporaryDirectory | None = None


def setUpModule() -> None:
    """Keep the shared store off the real machine state file.

    Reading any fact bootstraps and persists it, so without this a test run
    would create physical-state.json in the operator's checkout.
    """
    global _MODULE_STATE_DIR
    import os

    _MODULE_STATE_DIR = tempfile.TemporaryDirectory()
    os.environ["ROBOT_PHYSICAL_STATE_FILE"] = str(Path(_MODULE_STATE_DIR.name) / "physical-state.json")

    from app.services import physical_state as physical_state_module

    physical_state_module.physical_state_store._state_path = Path(
        os.environ["ROBOT_PHYSICAL_STATE_FILE"]
    )


def tearDownModule() -> None:
    import os

    os.environ.pop("ROBOT_PHYSICAL_STATE_FILE", None)
    if _MODULE_STATE_DIR is not None:
        _MODULE_STATE_DIR.cleanup()


class _RecordingActor:
    def __init__(self, actor_id: str, log: list[str], ok: bool = True) -> None:
        self.actor_id = actor_id
        self._log = log
        self._ok = ok

    def stop(self) -> dict[str, object]:
        self._log.append(self.actor_id)
        return {"ok": self._ok, "message": f"{self.actor_id} stopped."}


class _ExplodingActor:
    actor_id = "exploding"

    def stop(self) -> dict[str, object]:
        raise RuntimeError("serial port went away")


class SafetyControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.safety = SafetyController()

    def test_stop_sets_the_shared_flag_before_any_actor_runs(self) -> None:
        observed: list[bool] = []

        class FlagObserver:
            actor_id = "observer"

            def stop(_self) -> dict[str, object]:
                # A driver mid-move only ever sees the flag; it must already be
                # set by the time the fan-out starts, otherwise a slow serial
                # actor ahead of it would delay the abort.
                observed.append(self.safety.is_blocked())
                return {"ok": True, "message": "ok"}

        self.safety.register_actor(FlagObserver())
        self.safety.stop(reason="test", source="test")

        self.assertEqual(observed, [True])
        self.assertTrue(self.safety.is_blocked())
        self.assertEqual(self.safety.state, SafetyState.LATCHED)

    def test_actors_are_stopped_in_priority_order(self) -> None:
        log: list[str] = []
        self.safety.register_actor(_RecordingActor("serial", log), priority=PRIORITY_SERIAL)
        self.safety.register_actor(_RecordingActor("flag", log), priority=PRIORITY_FLAG)

        self.safety.stop(reason="test", source="test")

        # Flag-only actors return instantly, so they must not sit behind a
        # serial write that can block on a busy port.
        self.assertEqual(log, ["flag", "serial"])

    def test_one_failing_actor_does_not_prevent_the_others_stopping(self) -> None:
        log: list[str] = []
        self.safety.register_actor(_ExplodingActor(), priority=PRIORITY_FLAG)
        self.safety.register_actor(_RecordingActor("gantry", log), priority=PRIORITY_SERIAL)

        record = self.safety.stop(reason="test", source="test")

        self.assertEqual(log, ["gantry"])
        self.assertFalse(record.ok)
        failed = [report for report in record.reports if report.actor_id == "exploding"]
        self.assertIn("serial port went away", failed[0].message)

    def test_raise_if_blocked_guards_motion_entry_points(self) -> None:
        self.safety.stop(reason="test", source="test")
        with self.assertRaises(Exception) as caught:
            self.safety.raise_if_blocked("Gantry move")
        self.assertIn("Gantry move", str(caught.exception))

    def test_rearm_is_refused_while_a_fact_is_unconfirmed(self) -> None:
        from app.core.safety import UncertainFact

        self.safety.register_uncertainty_source(
            "test",
            lambda: [
                UncertainFact(
                    fact_id="toolhead.held",
                    label="Tool held by the gantry",
                    reason="Stopped during pick-up.",
                    suggested_question="What is on the head?",
                )
            ],
        )
        self.safety.stop(reason="test", source="test")

        result = self.safety.rearm()

        self.assertFalse(result["ok"])
        self.assertTrue(self.safety.is_blocked())
        self.assertEqual(self.safety.state, SafetyState.RECOVERING)
        self.assertEqual(result["requires_confirmation"][0]["fact_id"], "toolhead.held")

    def test_rearm_clears_the_latch_and_bumps_the_generation(self) -> None:
        before = self.safety.generation
        self.safety.stop(reason="test", source="test")

        result = self.safety.rearm(operator="bogdan")

        self.assertTrue(result["ok"])
        self.assertFalse(self.safety.is_blocked())
        self.assertEqual(self.safety.state, SafetyState.ARMED)
        # A run captures the generation at start; a change means "my run was
        # stopped out from under me" and must not silently resume.
        self.assertEqual(self.safety.generation, before + 1)

    def test_callable_actor_folds_a_list_of_session_results(self) -> None:
        actor = CallableActor(
            "gantry-serial",
            lambda: [
                {"ok": True, "message": "STOP sent.", "tool_port": "/dev/ttyUSB0"},
                {"ok": False, "message": "port busy", "tool_port": "/dev/ttyUSB1"},
            ],
        )
        result = actor.stop()

        self.assertFalse(result["ok"])
        self.assertEqual(len(result["sessions"]), 2)


class PhysicalStateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        root = Path(self._temp_dir.name)
        self.state_path = root / "physical-state.json"
        self.legacy_path = root / "toolhead-state.json"
        self.store = PhysicalStateStore(self.state_path, self.legacy_path)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_fresh_machine_bootstraps_an_empty_head_as_known(self) -> None:
        fact = self.store.require_known("toolhead.held")

        # Nothing has moved yet, so there is no interrupted change to be
        # uncertain about - refusing here would just be noise on a new install.
        self.assertIsNone(fact.value)
        self.assertEqual(fact.certainty, KNOWN)

    def test_stop_while_idle_leaves_a_settled_tool_known(self) -> None:
        self.store.set_known("toolhead.held", 3)

        self.store.on_stop(_stop_record("operator pressed e-stop"))

        fact = self.store.require_known("toolhead.held")
        self.assertEqual(fact.value, 3)
        self.assertEqual(fact.certainty, KNOWN)

    def test_stop_during_pickup_leaves_the_tool_uncertain_not_empty(self) -> None:
        self.store.set_known("toolhead.held", None)
        self.store.begin_transition("toolhead.held", provisional_value=2, phase="picking up toolhead 2")

        self.store.on_stop(_stop_record("operator pressed e-stop"))

        fact = self.store.get("toolhead.held")
        self.assertEqual(fact.certainty, UNCERTAIN)
        # The conservative belief: it may already be carrying tool 2. Reporting
        # None here is precisely what drove a loaded head into the rack.
        self.assertEqual(fact.value, 2)
        self.assertIn("picking up toolhead 2", fact.reason)

        with self.assertRaises(PhysicalStateError):
            self.store.require_known("toolhead.held")

    def test_stop_during_drop_keeps_the_tool_index(self) -> None:
        self.store.set_known("toolhead.held", 5)
        self.store.begin_transition("toolhead.held", provisional_value=5, phase="dropping toolhead 5")

        self.store.on_stop(_stop_record("limit switch tripped"))

        fact = self.store.get("toolhead.held")
        self.assertEqual(fact.certainty, UNCERTAIN)
        self.assertEqual(fact.value, 5)

    def test_completed_transition_is_known(self) -> None:
        self.store.begin_transition("toolhead.held", provisional_value=4, phase="picking up toolhead 4")
        self.store.commit_transition("toolhead.held", 4)

        self.store.on_stop(_stop_record("later, unrelated stop"))

        fact = self.store.require_known("toolhead.held")
        self.assertEqual(fact.value, 4)

    def test_operator_confirmation_restores_certainty(self) -> None:
        self.store.begin_transition("toolhead.held", provisional_value=2, phase="picking up toolhead 2")
        self.store.on_stop(_stop_record("e-stop"))

        self.store.confirm("toolhead.held", None, operator="bogdan")

        fact = self.store.require_known("toolhead.held")
        self.assertIsNone(fact.value)
        self.assertIn("bogdan", fact.reason)
        self.assertEqual(self.store.uncertain_facts(), [])

    def test_legacy_toolhead_file_is_imported_as_uncertain(self) -> None:
        self.legacy_path.write_text(json.dumps({"held_index": 6}), encoding="utf-8")

        fact = self.store.get("toolhead.held")

        # The old file was written by code that could not tell "dropped
        # cleanly" from "stopped mid-drop", so it has not earned being trusted.
        self.assertEqual(fact.value, 6)
        self.assertEqual(fact.certainty, UNCERTAIN)

    def test_unreadable_state_file_does_not_claim_the_machine_is_empty(self) -> None:
        self.state_path.write_text("{ this is not json", encoding="utf-8")

        facts = self.store.all_facts()

        self.assertTrue(all(not fact.is_known for fact in facts.values()))

    def test_uncertain_facts_are_reported_for_the_safety_latch(self) -> None:
        self.store.begin_transition("toolhead.held", provisional_value=1, phase="picking up toolhead 1")
        self.store.on_stop(_stop_record("e-stop"))

        outstanding = self.store.uncertain_facts()

        self.assertEqual([fact.fact_id for fact in outstanding], ["toolhead.held"])
        self.assertIn("toolhead", outstanding[0].suggested_question.lower())


class SafetyWiringTests(unittest.TestCase):
    def test_every_motion_service_registers_itself_as_a_stoppable_actor(self) -> None:
        # Importing the route is what pulls the driver modules in. Before this,
        # the route held a hand-written list of five services and /rearm knew
        # about two of them.
        import app.api.routes.safety  # noqa: F401
        from app.core.safety import safety_controller

        registered = {actor["actor_id"] for actor in safety_controller.snapshot()["registered_actors"]}

        self.assertEqual(
            registered,
            {
                "raspberry-pi-gantry",
                "hybrid-z-axis",
                "esp32-flash",
                "gantry-serial",
                "syringe-serial",
            },
        )

    def test_motion_drivers_share_one_latch(self) -> None:
        from app.core.safety import safety_controller
        from app.services.hybrid_z_axis import hybrid_z_axis_service
        from app.services.raspberry_gantry import raspberry_gantry_gpio_service

        # Same object, not merely equal: the drivers poll it inside their
        # stepping loops, so this is what makes one stop halt everything.
        self.assertIs(raspberry_gantry_gpio_service._stop_requested, safety_controller.motion_blocked)
        self.assertIs(hybrid_z_axis_service._stop_requested, safety_controller.motion_blocked)


class EndToEndEStopDuringToolChangeTests(unittest.TestCase):
    """The accident this whole layer exists to prevent, through the real objects.

    Sequence: a pick-up starts, the operator hits E-Stop mid-engage, and the
    machine must refuse to pretend the head came back empty.
    """

    def setUp(self) -> None:
        import os

        from app.services import physical_state as physical_state_module

        self._temp_dir = tempfile.TemporaryDirectory()
        state_path = Path(self._temp_dir.name) / "physical-state.json"
        os.environ["ROBOT_PHYSICAL_STATE_FILE"] = str(state_path)

        # Point the shared store at the isolated file for the duration of the
        # test, so this never touches the operator's real machine state.
        self._store = physical_state_module.PhysicalStateStore(
            state_path, Path(self._temp_dir.name) / "toolhead-state.json"
        )
        self._original_store = physical_state_module.physical_state_store
        physical_state_module.physical_state_store = self._store

        from app.services import toolhead as toolhead_module

        self._original_toolhead_store_source = toolhead_module.physical_state_store
        toolhead_module.physical_state_store = self._store

        from app.core.safety import SafetyController

        self.safety = SafetyController()
        self.safety.register_uncertainty_source("physical_state", self._store.uncertain_facts)
        self.safety.register_stop_observer(self._store.on_stop)

    def tearDown(self) -> None:
        import os

        from app.services import physical_state as physical_state_module
        from app.services import toolhead as toolhead_module

        physical_state_module.physical_state_store = self._original_store
        toolhead_module.physical_state_store = self._original_toolhead_store_source
        os.environ.pop("ROBOT_PHYSICAL_STATE_FILE", None)
        self._temp_dir.cleanup()

    def test_estop_mid_pickup_blocks_the_next_tool_change_until_confirmed(self) -> None:
        from app.services.toolhead import ToolheadStateStore

        toolhead = ToolheadStateStore()

        # Starts empty and trustworthy.
        self.assertIsNone(toolhead.held_index())

        # A pick-up of tool 2 begins: intent is recorded before the gantry moves.
        toolhead.begin_change(2, "picking up toolhead 2")

        # Operator hits E-Stop part way through the engage.
        self.safety.stop(reason="Operator pressed emergency stop.", source="operator")

        # The old code answered "nothing held" here and the next pick-up drove a
        # loaded head into the rack. Now the question refuses to be answered.
        with self.assertRaises(PhysicalStateError) as caught:
            toolhead.held_index()
        self.assertIn("uncertain", str(caught.exception).lower())

        value, uncertain = toolhead.held_index_or_uncertain()
        self.assertEqual(value, 2)
        self.assertTrue(uncertain)

        # And the latch will not clear while that is outstanding.
        refusal = self.safety.rearm()
        self.assertFalse(refusal["ok"])
        self.assertEqual(refusal["requires_confirmation"][0]["fact_id"], "toolhead.held")
        self.assertTrue(self.safety.is_blocked())

        # The operator looks at the machine and says the tool did engage.
        self._store.confirm("toolhead.held", 2, operator="bogdan")

        cleared = self.safety.rearm(operator="bogdan")
        self.assertTrue(cleared["ok"])
        self.assertFalse(self.safety.is_blocked())
        self.assertEqual(toolhead.held_index(), 2)


def _stop_record(reason: str):
    from app.core.safety import StopRecord

    return StopRecord(reason=reason, source="test", at=0.0, reports=())


if __name__ == "__main__":
    unittest.main()
