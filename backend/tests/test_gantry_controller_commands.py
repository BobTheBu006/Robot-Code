import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.gantry import GantryXYCalibrationRequest, GantryXYMoveRequest
from app.services.gantry_controller import GantryControllerService


class GantryControllerCommandTests(unittest.TestCase):
    def test_xy_pin_command_includes_motor_a_step_multiplier(self) -> None:
        service = GantryControllerService()
        request = GantryXYCalibrationRequest(
            x_step_pin=32,
            x_dir_pin=33,
            y_step_pin=25,
            y_dir_pin=26,
            motor_a_step_multiplier=2.0,
            x_min_limit_pin=27,
            x_max_limit_pin=14,
            y_min_limit_pin=34,
            y_max_limit_pin=35,
        )

        self.assertEqual(
            service._build_xy_pin_command(request),
            "SET XY PINS 32 33 25 26 2.000000",
        )

    def test_xy_move_request_accepts_multiplier_field(self) -> None:
        request = GantryXYMoveRequest.model_validate({
            "x_cm": 10,
            "y_cm": 0,
            "z_cm": 0,
            "motor_a_step_multiplier": 1.5,
            "x_step_pin": 32,
            "x_dir_pin": 33,
            "y_step_pin": 25,
            "y_dir_pin": 26,
            "x_min_limit_pin": 27,
            "x_max_limit_pin": 14,
            "y_min_limit_pin": 34,
            "y_max_limit_pin": 35,
        })

        self.assertEqual(request.motor_a_step_multiplier, 1.5)


if __name__ == "__main__":
    unittest.main()
