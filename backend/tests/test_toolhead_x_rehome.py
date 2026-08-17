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

    def rehome_x(self, context, request):
        self.events.append(("rehome_x",))
        return {"drift_steps": 12, "drift_cm": 0.03, "message": "X re-homed."}

    def rehome_y(self, context, request):
        self.events.append(("rehome_y",))
        return {"drift_steps": 4, "drift_cm": 0.01, "message": "Y re-homed."}


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
        self._real_rehome_y = toolhead_module.raspberry_gantry_gpio_service.rehome_y
        toolhead_module.raspberry_gantry_gpio_service.rehome_x = self.recorder.rehome_x
        toolhead_module.raspberry_gantry_gpio_service.rehome_y = self.recorder.rehome_y
        toolhead_module.xy_hardware_is_on_raspberry_pi = lambda context: True

    def tearDown(self) -> None:
        toolhead_module.raspberry_gantry_gpio_service.rehome_x = self._real_rehome
        toolhead_module.raspberry_gantry_gpio_service.rehome_y = self._real_rehome_y
        toolhead_module.xy_hardware_is_on_raspberry_pi = self._real_on_pi

    def _run(self, waypoints, verify=True):
        return self.service.run_sequence(
            {}, waypoints, approach_speed_rpm=400, context={"hardware_map": {}}, verify_x_home=verify
        )

    def test_y_is_homed_first_at_the_near_end_of_the_rack(self) -> None:
        # Y has to be corrected before the sequence aims at the tool's Y -
        # fixing it afterwards would be too late. Done at the clearance X so
        # the head stays clear of the hooks, and near the rack's low end so the
        # probe is short rather than traversing past every slot.
        self._run([(2.0, 30.0), (0.0, 30.0), (0.0, 28.3)])
        self.assertEqual(self.recorder.events[0], ("move", 2.0, 2.7))
        self.assertEqual(self.recorder.events[1], ("rehome_y",))

    def test_x_is_homed_at_the_clearance_offset_after_y(self) -> None:
        self._run([(2.0, 30.0), (0.0, 30.0), (0.0, 28.3)])
        kinds = [event[0] for event in self.recorder.events]
        self.assertLess(kinds.index("rehome_y"), kinds.index("rehome_x"))
        self.assertEqual(self.recorder.events[2], ("move", 2.0, 30.0))
        self.assertEqual(self.recorder.events[3], ("rehome_x",))

    def test_both_homes_happen_before_anything_engages(self) -> None:
        # Probing with the tool part way onto its hooks would drag it.
        self._run([(2.0, 30.0), (0.0, 30.0), (0.0, 28.3)])
        kinds = [event[0] for event in self.recorder.events]
        first_engage = [i for i, k in enumerate(kinds) if k == "move"][2]
        self.assertLess(kinds.index("rehome_x"), first_engage)
        self.assertLess(kinds.index("rehome_y"), first_engage)

    def test_it_happens_exactly_once(self) -> None:
        self._run([(2.0, 30.0), (0.0, 30.0), (0.0, 28.3), (0.0, 28.35), (2.0, 28.35)])
        self.assertEqual([e[0] for e in self.recorder.events].count("rehome_x"), 1)

    def test_every_waypoint_still_runs(self) -> None:
        waypoints = [(2.0, 30.0), (0.0, 30.0), (0.0, 28.3), (0.0, 28.35), (2.0, 28.35)]
        self._run(waypoints)
        moved = [(x, y) for kind, x, y in (e for e in self.recorder.events if e[0] == "move")]
        # The Y-home hop is prepended; every original waypoint still follows.
        self.assertEqual(moved, [(2.0, 2.7), *waypoints])

    def test_turning_it_off_skips_both_probes_and_the_extra_hop(self) -> None:
        self._run([(2.0, 30.0), (0.0, 30.0)], verify=False)
        kinds = [e[0] for e in self.recorder.events]
        self.assertNotIn("rehome_x", kinds)
        self.assertNotIn("rehome_y", kinds)
        self.assertEqual(self.recorder.events[0], ("move", 2.0, 30.0))

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
        kinds = [e[0] for e in self.recorder.events]
        self.assertNotIn("rehome_x", kinds)
        self.assertNotIn("rehome_y", kinds)


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


class RehomeParkingTests(unittest.TestCase):
    """Where the carriage is left after a re-home.

    Both of these were shipped broken. The probe leaves the carriage resting on
    the X min switch, and the next move in the tool-change sequence then
    aborted with "limit switch active during gantry move". User X 0 is also one
    buffer off that switch, not on it, so recording zero physical steps put the
    tracked position out by a buffer as well.
    """

    def setUp(self) -> None:
        from app.services.raspberry_gantry import RaspberryGantryGPIOService

        self.service = RaspberryGantryGPIOService()
        self.service._calibrated = True
        self.service._limit_buffer_cm = 0.1
        self.moves: list[tuple] = []

        # Stand in for the hardware. The approach toward the switch closes it
        # after 450 steps; nudging back in +X frees it again.
        self.switch_closed = False
        self.probe_travel = -450

        def move(gpio, pins, a, b, rpm, **kwargs):
            self.moves.append((a, b))
            if a < 0:                    # the slow approach toward X min
                self.service._last_a_steps = self.probe_travel
                self.service._last_b_steps = self.probe_travel
                self.switch_closed = True
                return kwargs.get("stop_limit_pin") is not None
            self.switch_closed = False   # backing off releases it
            return False

        self.service._move_corexy_steps = move
        self.service._limit_active = lambda gpio, pin: self.switch_closed
        self.service._setup_gpio = lambda gpio, pins: None
        self.service._cleanup_gpio = lambda gpio, pins: None
        self.service._save_state = lambda: None
        self.service._gpio_module = lambda: (object(), None)
        self.service._execution_mode = lambda: _Executed()
        self.service._pins_from_request = lambda request, context=None: _Pins()

    def _rehome(self):
        return self.service.rehome_x({}, _Request())

    def test_the_switch_is_approached_once_not_three_times(self) -> None:
        # Calibration needs a fast sweep plus a slow re-touch because it starts
        # from an unknown position. Here the carriage is already parked a couple
        # of centimetres away, so the extra passes only cost the operator time.
        self._rehome()
        approaches = [a for a, _ in self.moves if a < 0]
        self.assertEqual(len(approaches), 1)

    def test_the_carriage_is_walked_off_the_switch(self) -> None:
        self._rehome()
        self.assertTrue(self.moves, "a back-off move must follow the probe")
        a_steps, b_steps = self.moves[-1]
        self.assertGreater(a_steps, 0, "moves in +X, away from the min switch")
        self.assertEqual(a_steps, b_steps, "CoreXY: equal A and B is pure X, so Y does not move")

    def test_it_backs_off_by_one_buffer_when_that_frees_the_switch(self) -> None:
        self._rehome()
        expected = round(0.1 * self.service._effective_steps_per_cm())
        self.assertEqual(self.moves[-1][0], expected)

    def test_it_keeps_nudging_until_the_switch_actually_releases(self) -> None:
        # A microswitch does not open the instant you leave it. Stopping while
        # it is still closed is what made the next waypoint refuse to move.
        original = self.service._move_corexy_steps
        nudges = {"count": 0}

        def stubborn(gpio, pins, a, b, rpm, **kwargs):
            hit = original(gpio, pins, a, b, rpm, **kwargs)
            if a > 0:
                nudges["count"] += 1
                self.switch_closed = nudges["count"] < 3
            return hit

        self.service._move_corexy_steps = stubborn
        self._rehome()
        self.assertEqual(nudges["count"], 3)

    def test_a_switch_that_never_releases_is_reported(self) -> None:
        original = self.service._move_corexy_steps

        def stuck(gpio, pins, a, b, rpm, **kwargs):
            hit = original(gpio, pins, a, b, rpm, **kwargs)
            self.switch_closed = True
            return hit

        self.service._move_corexy_steps = stuck
        with self.assertRaises(RuntimeError) as caught:
            self._rehome()
        self.assertIn("still closed", str(caught.exception))

    def test_never_reaching_the_switch_is_reported(self) -> None:
        self.service._move_corexy_steps = lambda gpio, pins, a, b, rpm, **k: False
        with self.assertRaises(RuntimeError) as caught:
            self._rehome()
        self.assertIn("not reached", str(caught.exception))

    def test_the_tracked_position_matches_where_it_parked(self) -> None:
        # Whatever it took to free the switch is where the carriage now is, and
        # the step count has to say so rather than where it was aimed.
        self._rehome()
        backed_off = sum(a for a, _ in self.moves if a > 0)
        self.assertEqual(self.service._x_steps, backed_off)

    def test_extra_nudges_are_reflected_in_the_recorded_cm(self) -> None:
        # Pinning x_cm to 0 however far it actually nudged would bake that
        # travel into every position afterwards.
        original = self.service._move_corexy_steps

        def stubborn(gpio, pins, a, b, rpm, **kwargs):
            hit = original(gpio, pins, a, b, rpm, **kwargs)
            if a > 0:
                self.switch_closed = sum(1 for s, _ in self.moves if s > 0) < 4
            return hit

        self.service._move_corexy_steps = stubborn
        self._rehome()
        expected = self.service._x_steps / self.service._effective_steps_per_cm() - 0.1
        self.assertAlmostEqual(self.service._x_cm, max(0.0, expected), places=4)

    def test_the_drift_is_the_difference_from_what_was_expected(self) -> None:
        self.service._x_steps = 400          # believed 400 steps from the switch
        result = self._rehome()              # probe actually travelled 450
        self.assertEqual(result["drift_steps"], 50)

    def test_an_uncalibrated_gantry_refuses(self) -> None:
        self.service._calibrated = False
        with self.assertRaises(RuntimeError):
            self._rehome()


class _Pins:
    x_min_limit_pin = 26
    x_max_limit_pin = 20
    y_min_limit_pin = 21
    y_max_limit_pin = None


class _Executed:
    simulated = False
    status = "gpio_executed"
    message = ""


class _Request:
    speed_rpm = 100
    trapezoidal_speed = True
    acceleration_rpm_per_s = 300
    steps_per_rotation = 800


class LimitEscapeTests(unittest.TestCase):
    """A pressed limit must not trap the machine.

    Refusing every move while a switch is closed rejects the one move that
    would free it, so the operator has nothing to press and no way out. Driving
    away from a closed switch is the recovery, so it is always allowed.
    """

    def setUp(self) -> None:
        from app.services.raspberry_gantry import RaspberryGantryGPIOService

        self.service = RaspberryGantryGPIOService()
        self.service._x_cm = 0.0
        self.service._y_cm = 10.0
        self.pressed = {26}          # x_min
        self.service._limit_active = lambda gpio, pin: pin in self.pressed

    def _check(self, x_cm, y_cm):
        self.service._assert_limits_clear(None, _Pins(), _Move(x_cm, y_cm))

    def test_moving_away_from_a_pressed_switch_is_allowed(self) -> None:
        self._check(5.0, 10.0)

    def test_moving_further_into_it_is_refused(self) -> None:
        self.service._x_cm = 5.0
        with self.assertRaises(RuntimeError) as caught:
            self._check(1.0, 10.0)
        self.assertIn("x_min", str(caught.exception))

    def test_the_message_says_how_to_recover(self) -> None:
        self.service._x_cm = 5.0
        with self.assertRaises(RuntimeError) as caught:
            self._check(1.0, 10.0)
        message = str(caught.exception)
        self.assertIn("opposite direction", message)
        self.assertIn("stuck", message, "and names the other explanation")

    def test_another_axis_is_unaffected_by_a_pressed_x_switch(self) -> None:
        self._check(0.0, 20.0)

    def test_a_pressed_max_switch_blocks_only_the_increasing_direction(self) -> None:
        self.pressed = {20}          # x_max
        self.service._x_cm = 100.0
        self._check(90.0, 10.0)      # away: allowed
        with self.assertRaises(RuntimeError):
            self._check(105.0, 10.0)

    def test_with_no_target_to_reason_about_it_stays_conservative(self) -> None:
        with self.assertRaises(RuntimeError):
            self.service._assert_limits_clear(None, _Pins(), None)

    def test_nothing_pressed_is_always_fine(self) -> None:
        self.pressed = set()
        self._check(0.0, 10.0)


class _Move:
    def __init__(self, x_cm: float, y_cm: float) -> None:
        self.x_cm = x_cm
        self.y_cm = y_cm


class FullSequenceTests(unittest.TestCase):
    """pickup() and drop() end to end, not just run_sequence().

    The reachability guard runs only from these entry points, so testing
    run_sequence alone let a NameError in that guard reach the machine: every
    test passed and the block failed with "TOOLHEAD_MIN_X_CM is not defined".
    """

    def setUp(self) -> None:
        self.recorder = _Recorder()
        self.service = ToolheadService()
        self.service._goto = self.recorder.goto

        self._real_on_pi = toolhead_module.xy_hardware_is_on_raspberry_pi
        self._real_rehome = toolhead_module.raspberry_gantry_gpio_service.rehome_x
        self._real_rehome_y = toolhead_module.raspberry_gantry_gpio_service.rehome_y
        toolhead_module.xy_hardware_is_on_raspberry_pi = lambda context: True
        toolhead_module.raspberry_gantry_gpio_service.rehome_x = self.recorder.rehome_x
        toolhead_module.raspberry_gantry_gpio_service.rehome_y = self.recorder.rehome_y
        toolhead_module.physical_state_store.confirm("toolhead.held", None)

    def tearDown(self) -> None:
        toolhead_module.xy_hardware_is_on_raspberry_pi = self._real_on_pi
        toolhead_module.raspberry_gantry_gpio_service.rehome_x = self._real_rehome
        toolhead_module.raspberry_gantry_gpio_service.rehome_y = self._real_rehome_y
        toolhead_module.physical_state_store.confirm("toolhead.held", None)

    def _position(self, x_cm: float):
        from app.services.toolhead import ToolheadPosition

        return ToolheadPosition(index=1, x_cm=x_cm, y_cm=30.0)

    def test_a_pickup_at_x_zero_runs(self) -> None:
        moves = self.service.pickup(
            base_inputs={}, position=self._position(0.0), approach_speed_rpm=400,
            dip_depth_cm=1.7, lift_cm=0.05, clearance_cm=2.0,
            context={"hardware_map": {}}, verify_x_home=True,
        )
        self.assertTrue(moves)

    def test_a_pickup_below_x_zero_is_allowed(self) -> None:
        # A rack at the very end of the rail needs the head to come in under
        # the homed reference.
        moves = self.service.pickup(
            base_inputs={}, position=self._position(-0.2), approach_speed_rpm=400,
            dip_depth_cm=1.7, lift_cm=0.05, clearance_cm=2.0,
            context={"hardware_map": {}}, verify_x_home=True,
        )
        self.assertTrue(moves)

    def test_a_pickup_far_below_the_minimum_is_refused(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            self.service.pickup(
                base_inputs={}, position=self._position(-5.0), approach_speed_rpm=400,
                dip_depth_cm=1.7, lift_cm=0.05, clearance_cm=2.0,
                context={"hardware_map": {}}, verify_x_home=True,
            )
        self.assertIn("minimum X", str(caught.exception))

    def test_a_drop_below_x_zero_is_allowed_too(self) -> None:
        moves = self.service.drop(
            base_inputs={}, position=self._position(-0.2), approach_speed_rpm=400,
            dip_depth_cm=1.7, lift_cm=0.05, release_cm=0.05, clearance_cm=2.0,
            context={"hardware_map": {}}, verify_x_home=True,
        )
        self.assertTrue(moves)


if __name__ == "__main__":
    unittest.main()
