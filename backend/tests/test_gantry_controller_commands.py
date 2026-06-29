import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.gantry import GantryXYCalibrationRequest
from app.services.gantry_controller import GantryControllerService


class GantryControllerCommandTests(unittest.TestCase):
    def test_xy_pin_command_uses_corexy_motor_pins(self) -> None:
        service = GantryControllerService()
        request = GantryXYCalibrationRequest(
            x_step_pin=32,
            x_dir_pin=33,
            y_step_pin=25,
            y_dir_pin=26,
            x_min_limit_pin=27,
            x_max_limit_pin=14,
            y_min_limit_pin=34,
            y_max_limit_pin=35,
        )

        self.assertEqual(
            service._build_xy_pin_command(request),
            "SET XY PINS 32 33 25 26",
        )

    def test_xy_calibration_command_sends_steps_and_probe_cap(self) -> None:
        service = GantryControllerService()
        request = GantryXYCalibrationRequest(
            x_track_length_cm=111,
            y_track_length_cm=56,
            speed_rpm=500,
            trapezoidal_speed=True,
            acceleration_rpm_per_s=2000,
            steps_per_rotation=800,
            max_probe_rotations=90,
        )

        self.assertEqual(
            service._build_calibrate_xy_command(request),
            "CALIBRATE XY 111.000 56.000 500 1 2000 800 90",
        )


if __name__ == "__main__":
    unittest.main()
