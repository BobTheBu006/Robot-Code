import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.functions.tool_change.handler import _sequence_for_request
from app.models.gantry import ToolChangeRequest
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


class ToolChangeRequestTests(unittest.TestCase):
    def test_slot_defaults_are_ten_cm_apart(self) -> None:
        request = ToolChangeRequest.model_validate({"slot": 2})

        self.assertEqual(request.slot_position(), {"x_cm": 2.0, "y_cm": 45.0, "z_cm": 60.0})

    def test_get_tool_sequence_matches_slot_one_geometry(self) -> None:
        request = ToolChangeRequest.model_validate({"action": "get_tool", "slot": 1})

        sequence = _sequence_for_request(request)

        self.assertEqual(
            sequence,
            [
                {"label": "approach_slot", "x_cm": 2.0, "y_cm": 55.0},
                {"label": "move_left_into_tool", "x_cm": 0.0, "y_cm": 55.0},
                {"label": "move_back_lock_tool", "x_cm": 0.0, "y_cm": 53.0},
                {"label": "move_right_clear_rack", "x_cm": 2.0, "y_cm": 53.0},
            ],
        )

    def test_drop_tool_sequence_is_reverse_geometry(self) -> None:
        request = ToolChangeRequest.model_validate({"action": "drop_tool", "slot": 1})

        sequence = _sequence_for_request(request)

        self.assertEqual(
            sequence,
            [
                {"label": "approach_loaded_tool", "x_cm": 2.0, "y_cm": 53.0},
                {"label": "move_left_to_drop_lane", "x_cm": 0.0, "y_cm": 53.0},
                {"label": "move_forward_release_tool", "x_cm": 0.0, "y_cm": 55.0},
                {"label": "move_right_clear_empty_tool", "x_cm": 2.0, "y_cm": 55.0},
            ],
        )


if __name__ == "__main__":
    unittest.main()
