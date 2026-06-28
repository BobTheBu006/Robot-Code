import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.function_manifest import FunctionManifest
from app.models.hardware_map import FunctionHardwareAssignment, HardwareDeviceMapping, HardwareMap, HardwarePinMapping
from app.services.hardware_map import HardwareMapService


def _manifest(function_id: str = "example") -> FunctionManifest:
    return FunctionManifest.model_validate({
        "id": function_id,
        "display_name": "Example",
        "category": "Robot Actions",
        "description": "Example function.",
        "version": "0.1.0",
        "hardware_devices": [
            {
                "id": "required-motor",
                "name": "Required Motor",
                "kind": "stepper_motor",
                "pins": [
                    {"id": "required-step", "signal": "step", "function_input_key": "step_pin"},
                ],
            },
        ],
    })


class HardwareMapFunctionAssignmentTests(unittest.TestCase):
    def test_missing_manifest_hardware_syncs_as_disabled_unconnected_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = HardwareMapService(Path(temporary_directory) / "hardware-map.json")
            service.save_map(HardwareMap())
            hardware_map = service.sync_manifest_devices([_manifest()])

        self.assertEqual(hardware_map.boards, [])
        self.assertEqual(len(hardware_map.devices), 1)
        self.assertEqual(hardware_map.devices[0].id, "required-motor")
        self.assertEqual(hardware_map.devices[0].board_id, "")
        self.assertFalse(hardware_map.devices[0].enabled)

    def test_assigned_manifest_hardware_does_not_create_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            service = HardwareMapService(Path(temporary_directory) / "hardware-map.json")
            service.save_map(HardwareMap(
                devices=[
                    HardwareDeviceMapping(
                        id="physical-motor",
                        board_id="ttyUSB0",
                        name="Physical Motor",
                        kind="stepper_motor",
                        pins=[HardwarePinMapping(id="physical-step", signal="step", gpio="32", function_input_key="step_pin")],
                    ),
                ],
                function_assignments=[
                    FunctionHardwareAssignment(
                        function_id="example",
                        device_id="required-motor",
                        hardware_device_id="physical-motor",
                    ),
                ],
            ))
            hardware_map = service.sync_manifest_devices([_manifest()])

        self.assertEqual([device.id for device in hardware_map.devices], ["physical-motor"])


if __name__ == "__main__":
    unittest.main()
