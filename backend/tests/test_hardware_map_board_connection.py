import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.hardware_map import HardwareBoardMapping, HardwareMap
from app.services.hardware_map import HardwareMapError, HardwareMapService
from app.services.serial_ports import SerialPortInfo


def _dynamic_board(**overrides: object) -> HardwareBoardMapping:
    defaults = {
        "id": "syringe-controller",
        "label": "7 Syringe Pump Controller",
        "usb_port": "/dev/ttyUSB0",
        "dynamic": True,
        "expected_serial_number": "ABC123",
    }
    defaults.update(overrides)
    return HardwareBoardMapping.model_validate(defaults)


class HardwareMapBoardConnectionTests(unittest.TestCase):
    def _service_with_board(self, board: HardwareBoardMapping) -> HardwareMapService:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        service = HardwareMapService(Path(temporary_directory.name) / "hardware-map.json")
        service.save_map(HardwareMap(boards=[board]))
        return service

    def test_matching_serial_number_is_connected_and_matched(self) -> None:
        service = self._service_with_board(_dynamic_board())

        with patch(
            "app.services.hardware_map.list_serial_ports",
            return_value=[SerialPortInfo(device="/dev/ttyUSB0", serial_number="ABC123")],
        ):
            status = service.verify_board_connection("syringe-controller")

        self.assertTrue(status.connected)
        self.assertTrue(status.matched)

    def test_wrong_device_on_port_is_connected_but_not_matched(self) -> None:
        service = self._service_with_board(_dynamic_board())

        with patch(
            "app.services.hardware_map.list_serial_ports",
            return_value=[SerialPortInfo(device="/dev/ttyUSB0", serial_number="SOME-OTHER-DEVICE")],
        ):
            status = service.verify_board_connection("syringe-controller")

        self.assertTrue(status.connected)
        self.assertFalse(status.matched)

    def test_nothing_plugged_in_is_not_connected(self) -> None:
        service = self._service_with_board(_dynamic_board())

        with patch("app.services.hardware_map.list_serial_ports", return_value=[]):
            status = service.verify_board_connection("syringe-controller")

        self.assertFalse(status.connected)
        self.assertFalse(status.matched)

    def test_dynamic_board_without_expected_identity_raises(self) -> None:
        service = self._service_with_board(_dynamic_board(expected_serial_number=None))

        with patch("app.services.hardware_map.list_serial_ports", return_value=[]):
            with self.assertRaises(HardwareMapError):
                service.verify_board_connection("syringe-controller")

    def test_unknown_board_id_raises(self) -> None:
        service = self._service_with_board(_dynamic_board())

        with patch("app.services.hardware_map.list_serial_ports", return_value=[]):
            with self.assertRaises(HardwareMapError):
                service.verify_board_connection("does-not-exist")

    def test_non_dynamic_board_only_checks_presence(self) -> None:
        board = _dynamic_board(dynamic=False, expected_serial_number=None)
        service = self._service_with_board(board)

        with patch(
            "app.services.hardware_map.list_serial_ports",
            return_value=[SerialPortInfo(device="/dev/ttyUSB0", serial_number="ANYTHING")],
        ):
            status = service.verify_board_connection("syringe-controller")

        self.assertTrue(status.connected)
        self.assertTrue(status.matched)


if __name__ == "__main__":
    unittest.main()
