import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.functions.calibrate_xy.handler import execute as execute_calibrate_xy
from app.functions.move_gantry.handler import execute as execute_move_xy


def _raspberry_xy_context() -> dict:
    return {
        "mode": "test",
        "hardware_map": {
            "version": 1,
            "boards": [
                {
                    "id": "ttyUSB1",
                    "label": "Disabled Gantry ESP32",
                    "usb_port": "/dev/ttyUSB1",
                    "enabled": False,
                }
            ],
            "devices": [
                {"id": "x-axis-motor", "board_id": "raspberry-pi", "enabled": True},
                {"id": "y-axis-motor", "board_id": "raspberry-pi", "enabled": True},
                {"id": "x-min-limit-switch", "board_id": "raspberry-pi", "enabled": True},
                {"id": "x-max-limit-switch", "board_id": "raspberry-pi", "enabled": True},
                {"id": "y-min-limit-switch", "board_id": "raspberry-pi", "enabled": True},
                {"id": "y-max-limit-switch", "board_id": "raspberry-pi", "enabled": True},
            ],
        },
    }


class RaspberryGantryHandlerTests(unittest.TestCase):
    def test_calibrate_xy_uses_raspberry_gpio_branch_when_xy_devices_are_on_pi(self) -> None:
        result = execute_calibrate_xy(
            _raspberry_xy_context(),
            {
                "x_step_pin": 17,
                "x_dir_pin": 27,
                "y_step_pin": 23,
                "y_dir_pin": 24,
                "x_min_limit_pin": 5,
                "x_max_limit_pin": 6,
                "y_min_limit_pin": 12,
                "y_max_limit_pin": 13,
            },
        )

        self.assertEqual(result["controller"], "raspberry-pi")
        self.assertEqual(result["status"], "gpio_direct_execution_pending")
        self.assertIsNone(result["tool_port"])

    def test_move_xy_uses_raspberry_gpio_branch_when_xy_devices_are_on_pi(self) -> None:
        result = execute_move_xy(
            _raspberry_xy_context(),
            {
                "x_cm": 10,
                "y_cm": 10,
                "z_cm": 10,
                "x_step_pin": 17,
                "x_dir_pin": 27,
                "y_step_pin": 23,
                "y_dir_pin": 24,
                "x_min_limit_pin": 5,
                "x_max_limit_pin": 6,
                "y_min_limit_pin": 12,
                "y_max_limit_pin": 13,
            },
        )

        self.assertEqual(result["controller"], "raspberry-pi")
        self.assertEqual(result["status"], "gpio_direct_execution_pending")
        self.assertFalse(result["move_applied"])


if __name__ == "__main__":
    unittest.main()
