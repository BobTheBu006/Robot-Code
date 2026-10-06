"""The gripper: two mirrored servos that must never snap.

A servo cannot report its position, so the first pulse has to be the position
the gripper is parked in (closed), every move after that is ramped, and a drop
closes the claws and stops driving them before the tool goes back in the rack.
"""

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.function_manifest import FunctionManifest
from app.services.gripper import GripperService, ServoSettings, SimulatedServos
from app.services.hardware_map import HardwareMapError, HardwareMapService

LEFT = ServoSettings(gpio=3, open_deg=30.0, closed_deg=-90.0)
RIGHT = ServoSettings(gpio=2, open_deg=-30.0, closed_deg=90.0)


def _service():
    driver = SimulatedServos()
    return GripperService(driver=driver, sleep=lambda _s: None), driver


class PulseTests(unittest.TestCase):
    def test_the_standard_range_maps_angles_onto_pulses(self) -> None:
        self.assertEqual(LEFT.pulse_us(-90), 500)
        self.assertEqual(LEFT.pulse_us(0), 1500)
        self.assertEqual(LEFT.pulse_us(90), 2500)
        self.assertEqual(LEFT.pulse_us(200), 2500, "clamped to the servo's travel")


class MoveTests(unittest.TestCase):
    def test_the_first_pulse_is_the_parked_closed_position(self) -> None:
        service, driver = _service()
        service.move([LEFT, RIGHT], "open", 180.0)
        self.assertEqual(driver.pulses[3][0], 500, "left starts at closed, -90")
        self.assertEqual(driver.pulses[2][0], 2500, "right starts at closed, +90")

    def test_closing_a_parked_gripper_does_not_move_it(self) -> None:
        service, driver = _service()
        service.move([LEFT, RIGHT], "close", 180.0)
        self.assertEqual(set(driver.pulses[3]), {500})
        self.assertEqual(set(driver.pulses[2]), {2500})

    def test_moves_are_ramped_not_snapped(self) -> None:
        service, driver = _service()
        service.move([LEFT, RIGHT], "open", 180.0)
        left = driver.pulses[3]
        self.assertGreater(len(left), 10, "many small steps")
        biggest_jump = max(abs(b - a) for a, b in zip(left, left[1:]))
        self.assertLess(biggest_jump, 50, "no step larger than ~4 deg")
        self.assertEqual(left[-1], LEFT.pulse_us(30))

    def test_the_servos_move_mirrored(self) -> None:
        service, driver = _service()
        service.move([LEFT, RIGHT], "open", 180.0)
        for left_us, right_us in zip(driver.pulses[3], driver.pulses[2]):
            self.assertEqual(left_us - 1500, 1500 - right_us)

    def test_the_next_move_starts_where_the_last_ended(self) -> None:
        service, driver = _service()
        service.move([LEFT, RIGHT], "open", 180.0)
        after_open = len(driver.pulses[3])
        service.move([LEFT, RIGHT], "close", 180.0)
        first_close_step = driver.pulses[3][after_open]
        self.assertLess(abs(first_close_step - LEFT.pulse_us(30)), 50, "continues from open, no jump back")
        self.assertEqual(driver.pulses[3][-1], 500)

    def test_the_servos_keep_holding_after_a_move(self) -> None:
        service, driver = _service()
        service.move([LEFT, RIGHT], "open", 180.0)
        self.assertFalse(driver.stopped)

    def test_an_unknown_action_is_refused(self) -> None:
        service, _ = _service()
        with self.assertRaises(ValueError):
            service.move([LEFT, RIGHT], "wiggle", 180.0)


class ParkTests(unittest.TestCase):
    def test_parking_closes_stops_and_forgets(self) -> None:
        service, driver = _service()
        service.move([LEFT, RIGHT], "open", 180.0)
        self.assertTrue(service.park())
        self.assertEqual(driver.pulses[3][-1], 500, "closed for the rack")
        self.assertTrue(driver.stopped)
        driver.pulses.clear()
        service.move([LEFT, RIGHT], "close", 180.0)
        self.assertEqual(set(driver.pulses[3]), {500}, "next pick-up starts from parked closed again")

    def test_parking_an_unused_gripper_does_nothing(self) -> None:
        service, driver = _service()
        self.assertFalse(service.park())
        self.assertEqual(driver.pulses, {})


class BlockTests(unittest.TestCase):
    """Through the block's entry point, as a workflow runs it."""

    def _execute(self, inputs):
        module = importlib.import_module("app.functions.gripper.handler")
        service, driver = _service()
        with mock.patch.object(module, "gripper_service", service):
            return module.execute({"mode": "test"}, inputs), driver

    def _inputs(self, **overrides):
        manifest = FunctionManifest.model_validate_json(
            (Path(__file__).resolve().parents[1] / "app/functions/gripper/manifest.json").read_text()
        )
        inputs = {i.key: i.default for i in [*manifest.inputs, *manifest.advanced_inputs]}
        inputs.update(overrides)
        return inputs

    def test_open_with_the_manifest_defaults(self) -> None:
        result, driver = self._execute(self._inputs(action="open"))
        self.assertEqual((result["left_deg"], result["right_deg"]), (30.0, -30.0))
        self.assertEqual(driver.pulses[3][-1], 1833)
        self.assertEqual(driver.pulses[2][-1], 1167)

    def test_close_is_the_rack_position(self) -> None:
        result, _ = self._execute(self._inputs(action="close"))
        self.assertEqual((result["left_deg"], result["right_deg"]), (-90.0, 90.0))

    def test_both_servos_on_one_pin_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "same GPIO"):
            self._execute(self._inputs(left_servo_pin=2, right_servo_pin=2))


class HardwareMapTests(unittest.TestCase):
    def _manifest(self):
        return FunctionManifest.model_validate_json(
            (Path(__file__).resolve().parents[1] / "app/functions/gripper/manifest.json").read_text()
        )

    def _service(self, active):
        live = Path(__file__).resolve().parents[2] / "hardware-map.json"
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        copy = Path(directory.name) / "hardware-map.json"
        copy.write_text(live.read_text())
        return HardwareMapService(copy, active_connector_groups=lambda: active)

    def test_the_servo_pins_resolve_to_the_pogo_gpios(self) -> None:
        inputs = self._service({"gripper-tool"}).apply_function_defaults(self._manifest(), {})
        self.assertEqual((inputs["left_servo_pin"], inputs["right_servo_pin"]), ("3", "2"))

    def test_the_block_is_refused_while_the_gripper_is_not_connected(self) -> None:
        with self.assertRaisesRegex(HardwareMapError, "not connected"):
            self._service(set()).apply_function_defaults(self._manifest(), {})


if __name__ == "__main__":
    unittest.main()
