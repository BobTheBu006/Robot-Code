import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.hardware_map import HardwareMap


class PumpHardwareMapTests(unittest.TestCase):
    def test_stepper_pump_calibration_is_preserved(self) -> None:
        hardware_map = HardwareMap.model_validate(
            {
                "version": 1,
                "boards": [
                    {
                        "id": "ttyUSB0",
                        "label": "Pump ESP32",
                        "usb_port": "/dev/ttyUSB0",
                    }
                ],
                "devices": [
                    {
                        "id": "beads-medium-pump",
                        "board_id": "ttyUSB0",
                        "name": "Beads Medium Pump",
                        "kind": "stepper_motor",
                        "calibration_ml_per_200_steps": 1.25,
                        "pins": [],
                    }
                ],
            }
        )

        self.assertEqual(hardware_map.devices[0].calibration_ml_per_200_steps, 1.25)

    def test_raspberry_pi_i2c_aht20_device_is_valid_hardware(self) -> None:
        hardware_map = HardwareMap.model_validate(
            {
                "version": 1,
                "boards": [],
                "devices": [
                    {
                        "id": "raspberry-aht20",
                        "board_id": "raspberry-pi",
                        "name": "Raspberry AHT20",
                        "kind": "sensor",
                        "sensor_kind": "aht20_temperature_humidity",
                        "pins": [
                            {
                                "id": "raspberry-aht20-scl",
                                "signal": "scl",
                                "gpio": "3",
                            },
                            {
                                "id": "raspberry-aht20-sda",
                                "signal": "sda",
                                "gpio": "2",
                            },
                        ],
                    }
                ],
            }
        )

        self.assertEqual(hardware_map.devices[0].board_id, "raspberry-pi")
        self.assertEqual(hardware_map.devices[0].sensor_kind, "aht20_temperature_humidity")


if __name__ == "__main__":
    unittest.main()
