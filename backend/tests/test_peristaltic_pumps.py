"""Dispensing through the peristaltic pumps.

The risky part is the volume-to-steps conversion: it decides how much liquid
actually moves, and a silent mistake there is a ruined experiment rather than an
error message.
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("ROBOT_GPIO_SIMULATE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.functions.run_pumps.handler import execute
from app.services.peristaltic_pumps import (
    PeristalticPumpError,
    PeristalticPumpService,
    PumpCommand,
    steps_for_volume,
)


def _context(**calibrations):
    """A hardware map with the five pumps, calibrated as given."""
    devices = []
    for index in range(1, 6):
        devices.append({
            "id": f"peristaltic-pump-{index}",
            "board_id": "controller-ykkl80",
            "calibration_ml_per_200_steps": calibrations.get(f"pump{index}", 1.0),
        })
    return {"hardware_map": {"devices": devices}}


def _inputs(**overrides):
    values = {"tool_port": "/dev/ttyUSB0", "motor_enable_pin": 17}
    for index, (d, s) in enumerate([(13, 14), (27, 26), (25, 33), (22, 23), (4, 16)], start=1):
        values[f"pump_{index}_dir_pin"] = d
        values[f"pump_{index}_step_pin"] = s
        values[f"pump_{index}_ml"] = 0
    values.update(overrides)
    return values


class VolumeConversionTests(unittest.TestCase):
    def test_a_pump_delivering_one_ml_per_200_steps(self) -> None:
        self.assertEqual(steps_for_volume(1.0, 1.0), 200)
        self.assertEqual(steps_for_volume(2.5, 1.0), 500)

    def test_a_pump_with_wider_tubing_needs_fewer_steps(self) -> None:
        self.assertEqual(steps_for_volume(1.0, 2.0), 100)

    def test_a_pump_with_narrow_tubing_needs_more(self) -> None:
        self.assertEqual(steps_for_volume(1.0, 0.25), 800)

    def test_a_negative_volume_draws_back(self) -> None:
        self.assertEqual(steps_for_volume(-0.5, 1.0), -100)

    def test_an_uncalibrated_pump_is_refused_rather_than_guessed(self) -> None:
        # Dividing by a missing calibration would either crash or run a
        # nonsense number of steps into the tubing.
        for bad in (0, 0.0, None):
            with self.assertRaises(PeristalticPumpError):
                steps_for_volume(5.0, bad)


class HandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ran = []
        self.service = PeristalticPumpService()

        import app.functions.run_pumps.handler as handler

        def fake_run(context, commands, **kwargs):
            self.ran.append((commands, kwargs))
            return {"ok": True, "status": "completed",
                    "steps_done": [abs(c.steps) for c in commands]}

        self._real = handler.peristaltic_pump_service.run
        handler.peristaltic_pump_service.run = fake_run
        self._handler = handler

    def tearDown(self) -> None:
        self._handler.peristaltic_pump_service.run = self._real

    def test_only_pumps_with_a_volume_are_asked_to_move(self) -> None:
        result = execute(_context(), _inputs(pump_3_ml=2.0))
        self.assertTrue(result["ok"])
        commands, _ = self.ran[0]
        self.assertEqual([c.index for c in commands], [2], "pump 3 is index 2")

    def test_several_pumps_run_together(self) -> None:
        execute(_context(), _inputs(pump_1_ml=1.0, pump_5_ml=0.5))
        commands, _ = self.ran[0]
        self.assertEqual(sorted(c.index for c in commands), [0, 4])

    def test_each_pump_uses_its_own_calibration(self) -> None:
        execute(_context(pump1=1.0, pump2=0.5), _inputs(pump_1_ml=1.0, pump_2_ml=1.0))
        commands, _ = self.ran[0]
        by_index = {c.index: c.steps for c in commands}
        self.assertEqual(by_index[0], 200)
        self.assertEqual(by_index[1], 400, "half the volume per step needs twice the steps")

    def test_per_pump_speed_is_carried_through(self) -> None:
        execute(_context(), _inputs(pump_2_ml=1.0, pump_2_speed_rpm=120))
        commands, _ = self.ran[0]
        self.assertEqual(commands[0].speed_rpm, 120)

    def test_nothing_set_runs_nothing_and_is_not_an_error(self) -> None:
        result = execute(_context(), _inputs())
        self.assertTrue(result["ok"])
        self.assertEqual(self.ran, [], "the controller was never contacted")

    def test_an_uncalibrated_pump_fails_the_block_by_name(self) -> None:
        result = execute(_context(pump4=0), _inputs(pump_4_ml=1.0))
        self.assertFalse(result["ok"])
        self.assertIn("Pump 4", result["error"])
        self.assertEqual(self.ran, [], "nothing was pumped")

    def test_the_enable_pin_reaches_the_service(self) -> None:
        execute(_context(), _inputs(pump_1_ml=1.0))
        _, kwargs = self.ran[0]
        self.assertEqual(kwargs["enable_pin"], 17)
        self.assertEqual(kwargs["dir_pins"], [13, 27, 25, 22, 4])
        self.assertEqual(kwargs["step_pins"], [14, 26, 33, 23, 16])


class ServiceGuardTests(unittest.TestCase):
    def test_a_wrong_number_of_pins_is_refused_before_talking_to_the_board(self) -> None:
        with self.assertRaises(PeristalticPumpError):
            PeristalticPumpService().run(
                {}, [PumpCommand(0, 200, 60)],
                dir_pins=[13], step_pins=[14], enable_pin=17,
            )

    def test_a_pump_index_outside_the_five_is_refused(self) -> None:
        with self.assertRaises(PeristalticPumpError):
            PeristalticPumpService().run(
                {}, [PumpCommand(9, 200, 60)],
                dir_pins=[13, 27, 25, 22, 4], step_pins=[14, 26, 33, 23, 16], enable_pin=17,
            )

    def test_the_reply_parser_reads_the_completed_step_counts(self) -> None:
        service = PeristalticPumpService()
        self.assertEqual(service._parse_done("OK PUMP RUN 200 0 0 50 0"), [200, 0, 0, 50, 0])
        self.assertEqual(service._parse_done("OK STOP PUMP RUN 12 0 0 0 0"), [12, 0, 0, 0, 0])

    def test_an_unreadable_reply_does_not_invent_step_counts(self) -> None:
        self.assertEqual(PeristalticPumpService()._parse_done("garbage"), [0, 0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
