"""Exercise the migrated blocks through map resolution and their handlers."""
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.models.function_manifest import FunctionManifest
from app.services.esp32_builder import Esp32BuilderService
from app.services.gantry_controller import GantryControllerService
from app.services.hardware_map import HardwareMapError, HardwareMapService
from app.services.serial_ports import SerialPortInfo

ROOT = Path(__file__).resolve().parents[2]
SERIAL = "2ebcd7b203bdf0119170167148e9de0f"


class RecordingController(GantryControllerService):
    def __init__(self):
        super().__init__()
        self.sent = []

    def _load_serial_module(self):
        return object()

    def _acquire_connection(self, serial, port, baud_rate):
        self.port = port
        return object()

    def _send_command(self, serial_port, command, **kwargs):
        self.sent.append(command)
        for prefix, reply in (
            ("SET XY PINS", "OK XY PINS"),
            ("SET XY ENABLE", "OK XY ENABLE"),
            ("SET XY LIMITS", "OK XY LIMITS"),
            ("SET ENCODER PINS", "OK ENCODER PINS"),
            ("SET ENCODER SCALE", "OK ENCODER SCALE"),
            ("SET XY PID", "OK XY PID"),
            ("SET XY FOLLOW LIMIT", "OK XY FOLLOW LIMIT"),
            ("GOTOXY", "XY POSITION CM 10.100 5.100\nFOLLOW ERROR PEAK 1.50 2.25\nOK MOVE XY"),
            ("CALIBRATE XY", "OK CALIBRATE XY"),
        ):
            if command.startswith(prefix):
                return reply, True
        raise AssertionError(f"Unexpected command: {command}")


class XYMigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        path = self.root / "hardware-map.json"
        path.write_text((ROOT / "hardware-map.json").read_text())
        self.hardware = HardwareMapService(path)
        self.port = SerialPortInfo(device="/dev/ttyUSB7", description="XY", hardware_id="test", serial_number=SERIAL)

    def manifest(self, fid):
        return FunctionManifest.model_validate_json(
            (ROOT / "backend/app/functions" / fid / "manifest.json").read_text())

    def inputs(self, fid, **overrides):
        manifest = self.manifest(fid)
        inputs = {i.key: i.default for i in [*manifest.inputs, *manifest.advanced_inputs]}
        inputs.update(overrides)
        with patch("app.services.hardware_map.list_serial_ports", return_value=[self.port]):
            inputs = self.hardware.apply_function_defaults(manifest, inputs)
        context = {"mode": "test", "function_id": fid,
                   "manifest": manifest.model_dump(),
                   "hardware_map": self.hardware.load_map().model_dump(mode="json")}
        return context, inputs

    def test_move_uses_real_board_identity_pins_and_shared_enable(self):
        context, inputs = self.inputs("move_gantry_xy", tool_port="/dev/ttyUSB0", x_cm=10, y_cm=5)
        module = importlib.import_module("app.functions.move_gantry_xy.handler")
        controller = RecordingController()
        with patch.object(module, "gantry_controller_service", controller), \
             patch.object(module, "planned_move_xy_result", side_effect=AssertionError("Must not drive Pi GPIO")):
            result = module.execute(context, inputs)
        self.assertEqual(controller.port, "/dev/ttyUSB7")
        self.assertEqual(controller.sent[:2], ["SET XY PINS 25 26 27 14", "SET XY ENABLE 13 13 1"])
        self.assertIn("SET XY LIMITS 4 32 33 4 -1", controller.sent[:-1])
        self.assertTrue(controller.sent[-1].startswith("GOTOXY 10.000 5.000 "))
        self.assertFalse(any(" Z " in c for c in controller.sent))
        # The encoders are enabled in the map, so the Move XY block (GOTOXY)
        # is monitored: setup before the move, the peaks in the result.
        self.assertIn("SET ENCODER PINS 21 22 19 18", controller.sent)
        self.assertIn("SET ENCODER SCALE 1600 1 0", controller.sent)
        self.assertLess(controller.sent.index("SET ENCODER PINS 21 22 19 18"), len(controller.sent) - 1)
        self.assertEqual((result["follow_error_peak_a"], result["follow_error_peak_b"]), (1.5, 2.25))
        self.assertFalse(result["follow_error_tripped"])
        self.assertTrue(result["move_applied"])

    def test_calibration_preserves_cm_park_and_clearances(self):
        context, inputs = self.inputs("calibrate_xy", x_calibration_y_cm=4.5, x_start_clear_cm=2.5, x_end_clear_cm=3.0, limit_buffer_cm=0.5)
        module = importlib.import_module("app.functions.calibrate_xy.handler")
        controller = RecordingController()
        with patch.object(module, "gantry_controller_service", controller), \
             patch.object(module, "planned_calibrate_xy_result", side_effect=AssertionError("Must not drive Pi GPIO")), \
             patch.object(module.workspace_defaults_service, "apply_track_lengths", return_value={}):
            result = module.execute(context, inputs)
        self.assertIn("SET XY ENABLE 13 13 1", controller.sent)
        self.assertIn("SET XY LIMITS 32 33 4 -1", controller.sent)
        self.assertTrue(controller.sent[-1].endswith(" 4.500 0.500 2.500 3.000"))
        self.assertTrue(result["calibrated"])

    def test_wrong_controller_on_old_port_is_refused(self):
        wrong = SerialPortInfo(device="/dev/ttyUSB0", description="Z", hardware_id="test", serial_number="different-board")
        with patch("app.services.hardware_map.list_serial_ports", return_value=[wrong]):
            with self.assertRaisesRegex(HardwareMapError, "XY controller is not connected"):
                self.hardware.apply_function_defaults(self.manifest("move_gantry_xy"), {"tool_port": "/dev/ttyUSB0"})

    def test_boot_header_uses_map_and_does_not_claim_encoder_pins(self):
        service = Esp32BuilderService(ROOT, ROOT / "backend/app/functions")
        with patch("app.services.esp32_builder.hardware_map_service", self.hardware):
            service._write_xy_board_config(self.root, "xy-closed-loop")
        header = (self.root / "xy_board_config.h").read_text()
        for definition in ("XY_A_STEP 25", "XY_A_DIR 26", "XY_B_STEP 27", "XY_B_DIR 14", "XY_ENABLE 13", "XY_X_MIN 32", "XY_X_MAX 33", "XY_Y_MIN 4"):
            self.assertIn("#define " + definition, header)
        for pin in (18, 19, 21, 22):  # the encoders, disabled for now
            self.assertNotIn(f" {pin}\n", header)


if __name__ == "__main__":
    unittest.main()
