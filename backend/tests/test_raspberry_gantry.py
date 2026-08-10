import os
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.gantry import GantryXYCalibrationRequest, GantryXYMoveRequest
from app.services.raspberry_gantry import planned_calibrate_xy_result, planned_move_xy_result


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
    """Routing tests: which controller a request is dispatched to.

    These must never reach real GPIO. They were written on a machine with no
    GPIO libraries, where the service quietly fell back to simulation; run on
    the Pi they actually drive the gantry's pins and then fail on whatever the
    real limit switches happen to read. Each test below therefore pins the
    execution mode explicitly rather than depending on the host.
    """

    def setUp(self) -> None:
        self._previous_simulate = os.environ.get("ROBOT_GPIO_SIMULATE")

    def tearDown(self) -> None:
        sys.modules.pop("RPi.GPIO", None)
        sys.modules.pop("RPi", None)
        sys.modules.pop("lgpio", None)
        if self._previous_simulate is None:
            os.environ.pop("ROBOT_GPIO_SIMULATE", None)
        else:
            os.environ["ROBOT_GPIO_SIMULATE"] = self._previous_simulate

    def test_calibrate_xy_uses_raspberry_gpio_branch_when_xy_devices_are_on_pi(self) -> None:
        os.environ["ROBOT_GPIO_SIMULATE"] = "1"
        result = planned_calibrate_xy_result(
            _raspberry_xy_context(),
            GantryXYCalibrationRequest(
                x_step_pin=17,
                x_dir_pin=27,
                y_step_pin=23,
                y_dir_pin=24,
                x_min_limit_pin=5,
                x_max_limit_pin=6,
                y_min_limit_pin=12,
                y_max_limit_pin=13,
            ),
        )

        self.assertEqual(result["controller"], "raspberry-pi")
        self.assertIn(result["status"], {"gpio_simulated", "gpio_executed"})
        self.assertTrue(result["calibrated"])
        self.assertIsNone(result["tool_port"])

    def test_move_xy_uses_raspberry_gpio_branch_when_xy_devices_are_on_pi(self) -> None:
        os.environ["ROBOT_GPIO_SIMULATE"] = "1"
        result = planned_move_xy_result(
            _raspberry_xy_context(),
            GantryXYMoveRequest(
                x_cm=10,
                y_cm=10,
                z_cm=10,
                x_step_pin=17,
                x_dir_pin=27,
                y_step_pin=23,
                y_dir_pin=24,
                x_min_limit_pin=5,
                x_max_limit_pin=6,
                y_min_limit_pin=12,
                y_max_limit_pin=13,
            ),
        )

        self.assertEqual(result["controller"], "raspberry-pi")
        self.assertIn(result["status"], {"gpio_simulated", "gpio_executed"})
        self.assertTrue(result["move_applied"])

    def test_incompatible_rpi_gpio_backend_falls_back_to_simulation(self) -> None:
        class IncompatibleGPIO(types.ModuleType):
            BCM = "BCM"

            def setwarnings(self, _enabled: bool) -> None:
                return None

            def setmode(self, _mode: str) -> None:
                raise RuntimeError("Cannot determine SOC peripheral base address")

            def cleanup(self) -> None:
                return None

        # The point of this test is "no usable backend -> simulation, and say
        # why". ROBOT_GPIO_SIMULATE would reach the same verdict for a different
        # reason and hide the message, so it is pinned off; the fake modules
        # below are what keep this away from the real gantry.
        os.environ.pop("ROBOT_GPIO_SIMULATE", None)

        gpio_module = IncompatibleGPIO("RPi.GPIO")
        rpi_module = types.ModuleType("RPi")
        rpi_module.GPIO = gpio_module
        sys.modules["RPi"] = rpi_module
        sys.modules["RPi.GPIO"] = gpio_module
        # Deny the lgpio fallback too: the point of this test is "no usable
        # backend -> simulation". On the Pi lgpio really is installed, so
        # without this the service would fall back to it and move the gantry.
        sys.modules["lgpio"] = None

        result = planned_calibrate_xy_result(
            _raspberry_xy_context(),
            GantryXYCalibrationRequest(
                x_step_pin=17,
                x_dir_pin=27,
                y_step_pin=23,
                y_dir_pin=24,
                x_min_limit_pin=5,
                x_max_limit_pin=6,
                y_min_limit_pin=12,
                y_max_limit_pin=13,
            ),
        )

        self.assertEqual(result["status"], "gpio_simulated")
        self.assertIn("Cannot determine SOC peripheral base address", result["message"])


if __name__ == "__main__":
    unittest.main()
