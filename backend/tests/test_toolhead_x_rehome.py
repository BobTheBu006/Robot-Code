"""Re-touching X home in the middle of a tool change.

This machine loses the occasional step to worn bearings. Everywhere else that
is tolerable; at the tool rack it is not, because the head has to meet its
hooks. The sequence already drives X to the rack, so the switch is right there
- re-touching it costs one short probe and gives back every step X has lost.

What matters is *where* in the sequence it happens: after the clearance
approach, before anything engages.
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("ROBOT_GPIO_SIMULATE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import toolhead as toolhead_module
from app.services.toolhead import ToolheadService


class _Recorder:
    """Stands in for the gantry, recording the order things happened."""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def goto(self, base_inputs, x_cm, y_cm, speed_rpm, context=None):
        self.events.append(("move", x_cm, y_cm))
        return {"x_cm": x_cm, "y_cm": y_cm, "speed_rpm": speed_rpm, "move_reply": "ok"}

    def rehome(self, context, request):
        self.events.append(("rehome_x",))
        return {"drift_steps": 12, "drift_cm": 0.03, "message": "X re-homed."}


class _Position:
    index = 1
    x_cm = 0.0
    y_cm = 30.0


class SequenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recorder = _Recorder()
        self.service = ToolheadService()
        self.service._goto = self.recorder.goto

        self._real_rehome = toolhead_module.raspberry_gantry_gpio_service.rehome_x
        self._real_on_pi = toolhead_module.xy_hardware_is_on_raspberry_pi
        toolhead_module.raspberry_gantry_gpio_service.rehome_x = self.recorder.rehome
        toolhead_module.xy_hardware_is_on_raspberry_pi = lambda context: True

    def tearDown(self) -> None:
        toolhead_module.raspberry_gantry_gpio_service.rehome_x = self._real_rehome
        toolhead_module.xy_hardware_is_on_raspberry_pi = self._real_on_pi

    def _run(self, waypoints, verify=True):
        return self.service.run_sequence(
            {}, waypoints, approach_speed_rpm=400, context={"hardware_map": {}}, verify_x_home=verify
        )

    def test_the_rehome_happens_after_the_clearance_approach(self) -> None:
        # Not before: the carriage has to be at the clearance offset first.
        self._run([(2.0, 30.0), (0.0, 30.0), (0.0, 28.3)])
        self.assertEqual(self.recorder.events[0], ("move", 2.0, 30.0))
        self.assertEqual(self.recorder.events[1], ("rehome_x",))

    def test_the_rehome_happens_before_anything_engages(self) -> None:
        # Probing with the tool part way onto its hooks would drag it.
        self._run([(2.0, 30.0), (0.0, 30.0), (0.0, 28.3)])
        kinds = [event[0] for event in self.recorder.events]
        self.assertLess(kinds.index("rehome_x"), kinds.index("move", 1))

    def test_it_happens_exactly_once(self) -> None:
        self._run([(2.0, 30.0), (0.0, 30.0), (0.0, 28.3), (0.0, 28.35), (2.0, 28.35)])
        self.assertEqual([e[0] for e in self.recorder.events].count("rehome_x"), 1)

    def test_every_waypoint_still_runs(self) -> None:
        waypoints = [(2.0, 30.0), (0.0, 30.0), (0.0, 28.3), (0.0, 28.35), (2.0, 28.35)]
        self._run(waypoints)
        moved = [(x, y) for kind, x, y in (e for e in self.recorder.events if e[0] == "move")]
        self.assertEqual(moved, waypoints)

    def test_turning_it_off_skips_the_probe_entirely(self) -> None:
        self._run([(2.0, 30.0), (0.0, 30.0)], verify=False)
        self.assertNotIn("rehome_x", [e[0] for e in self.recorder.events])

    def test_the_drift_is_reported_in_the_moves(self) -> None:
        # Worth surfacing: it is the accumulated step loss since the last home.
        moves = self._run([(2.0, 30.0), (0.0, 30.0)])
        rehome = [m for m in moves if m.get("action") == "verify_x_home"]
        self.assertEqual(len(rehome), 1)
        self.assertEqual(rehome[0]["drift_steps"], 12)

    def test_the_esp32_gantry_is_skipped_rather_than_faked(self) -> None:
        # That path has no single-axis probe. A tool change that silently did
        # not verify would be worse than one that never claimed to.
        toolhead_module.xy_hardware_is_on_raspberry_pi = lambda context: False
        self._run([(2.0, 30.0), (0.0, 30.0)])
        self.assertNotIn("rehome_x", [e[0] for e in self.recorder.events])


class WaypointShapeTests(unittest.TestCase):
    """The re-home relies on the first waypoint being the clearance offset."""

    def setUp(self) -> None:
        self.service = ToolheadService()

    def test_pickup_starts_clear_of_the_rack(self) -> None:
        waypoints = self.service.pickup_waypoints(_Position(), dip_depth_cm=1.7, lift_cm=0.05, clearance_cm=2.0)
        self.assertEqual(waypoints[0], (2.0, 30.0))
        self.assertEqual(waypoints[1], (0.0, 30.0), "then into the slot at X 0")

    def test_drop_starts_clear_of_the_rack_too(self) -> None:
        waypoints = self.service.drop_waypoints(
            _Position(), dip_depth_cm=1.7, lift_cm=0.05, release_cm=0.05, clearance_cm=2.0
        )
        self.assertEqual(waypoints[0][0], 2.0)


if __name__ == "__main__":
    unittest.main()
