"""Checking pogo contact during a pick-up, before the tool is hooked.

The sequence on the machine: clearance (x + clearance) -> tool position ->
wait -> check TXD-RXD. A miss backs out to the clearance position and slides in
again, up to the retry count. Only after a confirmed contact does the head dip
and hook the tool.
"""

import importlib
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.hardware_map import HardwareGroupMapping, HardwareMap
from app.services import toolhead as toolhead_module
from app.services.hardware_map import default_pogo_connector
from app.services.pogo_connector import ConnectorStateStore, PogoConnectorService, SimulatedPinDriver
from app.services.toolhead import ToolheadContactError, ToolheadPosition, ToolheadService

CLEARANCE = (2.0, 42.7)
TOOL = (0.0, 42.7)
WAYPOINTS = [CLEARANCE, TOOL, (0.0, 41.2), (0.0, 42.0), (2.0, 42.0)]


class _Checks:
    """A contact check that answers from a script, and records when it ran."""

    def __init__(self, answers, events) -> None:
        self.answers = list(answers)
        self.events = events

    def __call__(self):
        ok = self.answers.pop(0)
        self.events.append(("check", ok))
        return ok, "contact ok" if ok else "no TXD-RXD loopback"


class _Safety:
    def __init__(self, blocked: bool = False) -> None:
        self.motion_blocked = threading.Event()
        if blocked:
            self.motion_blocked.set()
        self.waits: list[float] = []

    def raise_if_blocked(self, action: str = "Motion") -> None:
        if self.motion_blocked.is_set():
            raise RuntimeError(f"{action} blocked: E-Stop")


class SequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[tuple] = []
        self.service = ToolheadService()
        self.service._goto = lambda base, x, y, rpm, context=None: (
            self.events.append(("move", x, y)) or {"x_cm": x, "y_cm": y}
        )
        self.safety = _Safety()
        patcher = mock.patch.object(toolhead_module, "safety_controller", self.safety)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, answers, retries):
        return self.service.run_sequence(
            {}, WAYPOINTS, approach_speed_rpm=400,
            contact_check=_Checks(answers, self.events), contact_retries=retries, contact_settle_seconds=0.0,
        )

    def test_a_confirmed_contact_carries_on_to_hook_the_tool(self) -> None:
        self._run([True], retries=2)
        self.assertEqual(self.events, [
            ("move", *CLEARANCE), ("move", *TOOL), ("check", True),
            ("move", 0.0, 41.2), ("move", 0.0, 42.0), ("move", 2.0, 42.0),
        ])

    def test_a_miss_backs_out_and_slides_in_again(self) -> None:
        self._run([False, True], retries=2)
        self.assertEqual(self.events[:6], [
            ("move", *CLEARANCE), ("move", *TOOL), ("check", False),
            ("move", *CLEARANCE), ("move", *TOOL), ("check", True),
        ])
        self.assertEqual(self.events[6], ("move", 0.0, 41.2), "then the dip")

    def test_exhausted_retries_end_backed_out_without_dipping(self) -> None:
        with self.assertRaisesRegex(ToolheadContactError, "after 3 attempts"):
            self._run([False, False, False], retries=2)
        self.assertEqual([e for e in self.events if e[0] == "check"], [("check", False)] * 3)
        self.assertEqual(self.events[-1], ("move", *CLEARANCE), "left at the clearance position")
        self.assertNotIn(("move", 0.0, 41.2), self.events, "never dipped into the hooks")

    def test_zero_retries_fails_on_the_first_miss(self) -> None:
        with self.assertRaisesRegex(ToolheadContactError, "after 1 attempt:"):
            self._run([False], retries=0)

    def test_the_move_record_includes_each_check(self) -> None:
        moves = self._run([False, True], retries=1)
        checks = [m for m in moves if m.get("action") == "check_tool_contact"]
        self.assertEqual([(c["attempt"], c["ok"]) for c in checks], [(1, False), (2, True)])

    def test_an_estop_during_the_wait_stops_before_the_check(self) -> None:
        self.safety.motion_blocked.set()
        with self.assertRaisesRegex(RuntimeError, "E-Stop"):
            self._run([True], retries=2)
        self.assertNotIn(("check", True), self.events)

    def test_no_check_means_the_old_sequence(self) -> None:
        self.service.run_sequence({}, WAYPOINTS, approach_speed_rpm=400)
        self.assertEqual([e[1:] for e in self.events], WAYPOINTS)


class _HeldState:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def begin_change(self, provisional, phase):
        self.calls.append(("begin", provisional))

    def commit_change(self, index):
        self.calls.append(("commit", index))


class PickupStateTests(unittest.TestCase):
    def test_a_failed_contact_records_the_head_as_empty(self) -> None:
        # Every attempt backed out before the dip, so the tool stayed in the
        # rack; "uncertain" would make the operator confirm something known.
        service = ToolheadService()
        service._goto = lambda *a, **k: {}
        state = _HeldState()
        with mock.patch.object(toolhead_module, "toolhead_state_store", state), \
                mock.patch.object(toolhead_module, "safety_controller", _Safety()):
            with self.assertRaises(ToolheadContactError):
                service.pickup(
                    {}, ToolheadPosition(index=5, x_cm=0.0, y_cm=42.7), 400, 1.5, 0.8, 2.0,
                    contact_check=lambda: (False, "no loopback"), contact_retries=0, contact_settle_seconds=0.0,
                )
        self.assertEqual(state.calls, [("begin", 5), ("commit", None)])


def _connector_rig(groups, shorted=True):
    directory = tempfile.TemporaryDirectory()
    hardware_map = HardwareMap(groups=groups, connectors=[default_pogo_connector()])
    pins = SimulatedPinDriver(shorted={frozenset({"14", "15"})} if shorted else set())
    service = PogoConnectorService(
        state_store=ConnectorStateStore(Path(directory.name) / "state.json"),
        pin_driver=pins, load_map=lambda: hardware_map, usb_settle_seconds=0.0,
    )
    return directory, service, pins


class ConnectorContactTests(unittest.TestCase):
    def test_a_short_is_reported_as_contact(self) -> None:
        directory, service, pins = _connector_rig([])
        self.addCleanup(directory.cleanup)
        ok, _ = service.check_contact()
        self.assertTrue(ok)
        self.assertEqual(pins.state["14"], ("input", "none"), "TXD not left driven")

    def test_no_short_is_a_miss_not_an_exception(self) -> None:
        directory, service, _ = _connector_rig([], shorted=False)
        self.addCleanup(directory.cleanup)
        ok, message = service.check_contact()
        self.assertFalse(ok)
        self.assertIn("loopback", message)

    def test_a_slot_whose_tool_uses_tx_rx_cannot_be_contact_checked(self) -> None:
        group = HardwareGroupMapping(id="uart-tool", name="UART Tool", connector_id="pogo-connector",
                                     pin_modes={"TXD": "uart"}, toolhead_index=3)
        directory, service, _ = _connector_rig([group])
        self.addCleanup(directory.cleanup)
        self.assertIn("would always fail", service.contact_check_blocker(3))
        self.assertIsNone(service.contact_check_blocker(4), "a slot with no tool group is checkable")


class _FakeToolhead:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.pickup_kwargs: dict = {}

    def pickup(self, *, position, **kwargs):
        self.calls.append(f"pickup {position.index}")
        self.pickup_kwargs = kwargs
        return []

    def drop(self, *, position, **_kwargs):
        self.calls.append(f"drop {position.index}")
        return []


class _Held:
    def __init__(self, held=None) -> None:
        self.held = held

    def held_index(self):
        return self.held


class _Defaults:
    def apply_toolhead_defaults(self, _values):
        return {}


class PickupBlockTests(unittest.TestCase):
    """Through the block's entry point, as the workflow calls it."""

    def _run(self, groups, inputs, held=None):
        directory, service, _ = _connector_rig(groups)
        self.addCleanup(directory.cleanup)
        module = importlib.import_module("app.functions.pickup_toolhead.handler")
        toolhead = _FakeToolhead()
        for name, value in {
            "pogo_connector_service": service,
            "toolhead_service": toolhead,
            "toolhead_state_store": _Held(held),
            "workspace_defaults_service": _Defaults(),
        }.items():
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        return module, toolhead, inputs

    def test_the_check_is_handed_to_the_sequence_when_enabled(self) -> None:
        module, toolhead, inputs = self._run([], {"toolhead_index": 4, "check_tool_contact": True, "contact_retries": 3})
        module.execute({}, inputs)
        self.assertIsNotNone(toolhead.pickup_kwargs["contact_check"])
        self.assertEqual(toolhead.pickup_kwargs["contact_retries"], 3)
        self.assertEqual(toolhead.pickup_kwargs["contact_settle_seconds"], 1.0)

    def test_the_check_is_off_by_default(self) -> None:
        module, toolhead, inputs = self._run([], {"toolhead_index": 4})
        module.execute({}, inputs)
        self.assertIsNone(toolhead.pickup_kwargs["contact_check"])

    def test_an_impossible_check_is_refused_before_anything_moves(self) -> None:
        group = HardwareGroupMapping(id="uart-tool", name="UART Tool", connector_id="pogo-connector",
                                     pin_modes={"TXD": "uart"}, toolhead_index=3)
        # A tool is held, so an accepted request would drop it first.
        module, toolhead, inputs = self._run([group], {"toolhead_index": 3, "check_tool_contact": True}, held=1)
        with self.assertRaisesRegex(ValueError, "would always fail"):
            module.execute({}, inputs)
        self.assertEqual(toolhead.calls, [], "not even the automatic drop ran")


if __name__ == "__main__":
    unittest.main()
