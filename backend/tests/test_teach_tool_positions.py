"""Teaching the tool rack by hand: push the carriage, Save, Next.

The motors are off while the carriage is pushed, the encoders say where it
went, and the gantry adopts that position at the end so its calibration
survives. These pin the backend half and, by reading the source, the
firmware's guard that nothing can energise the motors mid-teach.
"""

import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.gantry import GantryGotoXYRequest
from app.services.gantry_controller import GantryControllerError, GantryControllerService

FIRMWARE = Path(__file__).resolve().parents[2] / "functions/esp 32 code/esp32 xy-closed-loop/firmware/main.ino"


def _request():
    return GantryGotoXYRequest(
        x_step_pin=25, x_dir_pin=26, y_step_pin=27, y_dir_pin=14,
        x_min_limit_pin=32, x_max_limit_pin=33, y_min_limit_pin=4, tool_port="/dev/ttyFAKE0",
    )


class _Recording(GantryControllerService):
    def __init__(self, reply: str, encoders=True) -> None:
        super().__init__()
        self.reply = reply
        self.encoders = encoders
        self.calls: list[dict] = []

    def _encoder_setup_commands(self, request):
        return [("SET ENCODER PINS 21 22 19 18", ("OK ENCODER PINS",))] if self.encoders else []

    def _send_config_and_action(self, **kwargs):
        self.calls.append(kwargs)
        return "OK XY PINS", "OK XY LIMITS", self.reply


class TeachControllerTests(unittest.TestCase):
    def test_start_sets_up_the_encoders_and_reports_the_position(self) -> None:
        service = _Recording("OK TEACH START 40.000 10.000 1")
        result = service.teach(_request(), "start")
        self.assertEqual(service.calls[0]["action_command"], "TEACH START")
        self.assertTrue(service.calls[0]["extra_commands"], "encoder setup sent with start")
        self.assertEqual((result["x_cm"], result["y_cm"], result["encoders_ok"]), (40.0, 10.0, True))

    def test_position_does_not_reconfigure_the_encoders(self) -> None:
        # Re-priming the encoder buses mid-teach would lose any push in the gap.
        service = _Recording("OK TEACH POS 12.345 30.500 1")
        result = service.teach(_request(), "position")
        self.assertIsNone(service.calls[0]["extra_commands"])
        self.assertEqual((result["x_cm"], result["y_cm"]), (12.345, 30.5))

    def test_end_adopts_and_reports_the_final_position(self) -> None:
        service = _Recording("OK TEACH END 0.250 2.700 1")
        result = service.teach(_request(), "end")
        self.assertEqual(service.calls[0]["action_command"], "TEACH END")
        self.assertEqual((result["x_cm"], result["y_cm"]), (0.25, 2.7))

    def test_teaching_needs_the_encoders(self) -> None:
        with self.assertRaisesRegex(GantryControllerError, "needs the XY encoders"):
            _Recording("", encoders=False).teach(_request(), "start")

    def test_an_unknown_action_is_refused(self) -> None:
        with self.assertRaises(GantryControllerError):
            _Recording("").teach(_request(), "wiggle")


class TeachBlockTests(unittest.TestCase):
    def _execute(self, positions):
        module = importlib.import_module("app.functions.teach_tool_positions.handler")
        defaults = mock.Mock()
        defaults.apply_toolhead_defaults.return_value = ["tool_1_x_cm"]
        with mock.patch.object(module, "workspace_defaults_service", defaults):
            result = module.execute({"mode": "test"}, {"positions": positions})
        return result, defaults

    def test_saved_slots_become_the_toolhead_defaults(self) -> None:
        result, defaults = self._execute(json.dumps({"1": {"x_cm": 0.25, "y_cm": 2.7}, "4": {"x_cm": 0.1, "y_cm": 32.5}}))
        defaults.apply_toolhead_defaults.assert_called_once_with(
            {"tool_1_x_cm": 0.25, "tool_1_y_cm": 2.7, "tool_4_x_cm": 0.1, "tool_4_y_cm": 32.5}
        )
        self.assertEqual(sorted(result["saved"]), ["1", "4"])

    def test_nothing_saved_writes_nothing(self) -> None:
        result, defaults = self._execute("")
        defaults.apply_toolhead_defaults.assert_not_called()
        self.assertEqual(result["saved"], {})

    def test_a_slot_outside_the_rack_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "Slot 7"):
            self._execute({"7": {"x_cm": 0, "y_cm": 0}})

    def test_a_position_outside_the_machine_is_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the machine"):
            self._execute({"2": {"x_cm": -50, "y_cm": 12}})


class TeachFirmwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = FIRMWARE.read_text()

    def test_motors_cannot_be_energised_while_teaching(self) -> None:
        start = self.source.index("void setXYMotorsEnabled(bool enabled) {")
        self.assertIn("if (enabled && teachMode)", self.source[start:start + 200])

    def test_moving_commands_are_refused_while_teaching(self) -> None:
        self.assertIn('if (teachMode && !allowedDuringTeach(cmd))', self.source)
        guard = self.source[self.source.index("bool allowedDuringTeach("):]
        guard = guard[:guard.index("\n}\n")]
        for moving in ("GOTOXY", "MOVE", "CALIBRATE", "TEST MOTOR"):
            self.assertNotIn(f'"{moving}', guard, f"{moving} must not be allowed mid-teach")

    def test_end_adopts_the_encoder_position_and_saves_it(self) -> None:
        end = self.source[self.source.index('if (cmd == "TEACH END")'):]
        end = end[:end.index("return true;\n  }\n  return false;")]
        self.assertIn("currentXSteps = teachBaseX + (deltaA + deltaB) / 2;", end)
        self.assertIn("saveXCalibrationState();", end)
        self.assertIn("invalidateXCalibrationState();", end, "an unreadable end drops calibration, not guesses")


if __name__ == "__main__":
    unittest.main()
