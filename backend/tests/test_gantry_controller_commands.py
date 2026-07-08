import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.gantry import GantryCircleXYRequest, GantryXYCalibrationRequest
from app.services.gantry_controller import GantryControllerReportedError, GantryControllerService


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
            y_track_length_cm=55.5,
            speed_rpm=500,
            trapezoidal_speed=True,
            acceleration_rpm_per_s=2000,
            steps_per_rotation=800,
            max_probe_rotations=90,
        )

        self.assertEqual(
            service._build_calibrate_xy_command(request),
            "CALIBRATE XY 111.000 55.500 500 1 2000 800 90",
        )

    def test_xy_calibration_ignores_unused_y_limit_pins(self) -> None:
        request = GantryXYCalibrationRequest(
            x_step_pin=27,
            x_dir_pin=14,
            y_step_pin=25,
            y_dir_pin=26,
            x_min_limit_pin=12,
            x_max_limit_pin=13,
            y_max_limit_pin=25,
        )

        self.assertEqual(request.y_step_pin, 25)

    def test_xy_calibration_err_reply_is_reported_as_firmware_error(self) -> None:
        service = GantryControllerService()
        reply = "\n".join([
            "ACTIVE X CALIBRATION RPM 100",
            "COREXY X PROBE STOPPED_BY X_MIN EXPECTED X_MAX A_STEPS 0 B_STEPS 0",
            "ERR XY X_MAX MEASURED_ZERO",
        ])

        self.assertTrue(service._reply_contains_prefix(reply, ("ERR ",)))
        self.assertEqual(
            service._reply_last_prefixed_line(reply, ("ERR ",)),
            "ERR XY X_MAX MEASURED_ZERO",
        )
        self.assertTrue(issubclass(GantryControllerReportedError, RuntimeError))

    def test_circle_repeat_count_sends_one_circle_command_per_repeat(self) -> None:
        class FakeSerialModule:
            SerialException = Exception

        class FakeGantryControllerService(GantryControllerService):
            def __init__(self) -> None:
                super().__init__()
                self.sent_commands: list[str] = []

            def _load_serial_module(self):
                return FakeSerialModule

            def _acquire_connection(self, serial, port: str, baud_rate: int):
                return object()

            def _send_command(
                self,
                serial_port,
                command: str,
                *,
                terminal_prefixes,
                deadline_seconds: float,
                active_session=None,
            ):
                self.sent_commands.append(command)
                if command.startswith("SET XY PINS"):
                    return "OK XY PINS", True
                if command.startswith("SET XY LIMITS"):
                    return "OK XY LIMITS", True
                if command.startswith("CIRCLEXY"):
                    return "OK CIRCLE XY", True
                return "", False

        service = FakeGantryControllerService()
        request = GantryCircleXYRequest(
            tool_port="/dev/ttyUSB9",
            center_x_cm=10,
            center_y_cm=10,
            radius_cm=2,
            repeat_count=3,
            speed_rpm=400,
            trapezoidal_speed=True,
            acceleration_rpm_per_s=600,
        )

        response = service.circle_xy(request)

        self.assertEqual(service.sent_commands.count("CIRCLEXY 10.000 10.000 2.000 400 1 600"), 3)
        self.assertEqual(response.repeat_count, 3)
        self.assertEqual(
            response.move_command_sent,
            "\n".join(["CIRCLEXY 10.000 10.000 2.000 400 1 600"] * 3),
        )


if __name__ == "__main__":
    unittest.main()
