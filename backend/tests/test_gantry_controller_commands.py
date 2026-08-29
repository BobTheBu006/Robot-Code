import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.gantry import GantryCircleXYRequest, GantryXYCalibrationRequest
from app.services.gantry_controller import GantryControllerError, GantryControllerReportedError, GantryControllerService


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
            "CALIBRATE XY 111.000 55.500 500 1 2000 800 90 3.200 0.500",
        )

    def test_xy_calibration_command_sends_requested_limit_buffer(self) -> None:
        service = GantryControllerService()
        request = GantryXYCalibrationRequest(
            x_track_length_cm=111,
            y_track_length_cm=55.5,
            speed_rpm=500,
            trapezoidal_speed=True,
            acceleration_rpm_per_s=2000,
            steps_per_rotation=800,
            max_probe_rotations=90,
            limit_buffer_cm=1.0,
        )

        # The firmware persists this buffer and maps every later move through it.
        self.assertEqual(
            service._build_calibrate_xy_command(request),
            "CALIBRATE XY 111.000 55.500 500 1 2000 800 90 3.200 1.000",
        )

    def test_xy_calibration_command_sends_requested_calibration_y(self) -> None:
        service = GantryControllerService()
        request = GantryXYCalibrationRequest(
            x_track_length_cm=111,
            y_track_length_cm=55.5,
            speed_rpm=500,
            trapezoidal_speed=True,
            acceleration_rpm_per_s=2000,
            steps_per_rotation=800,
            max_probe_rotations=90,
            x_calibration_y_cm=5.0,
        )

        # The park Y cm arg is appended last so firmware built before it still parses
        # the command and falls back to its own default.
        self.assertEqual(
            service._build_calibrate_xy_command(request),
            "CALIBRATE XY 111.000 55.500 500 1 2000 800 90 5.000 0.500",
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


class MoveXYWithEncodersIntegrationTests(unittest.TestCase):
    """move_xy end to end against a fake serial connection.

    Exercises the actual entry point a block calls, not just the command
    builders in isolation - the plan for this feature calls out that testing
    only the helper is exactly what let a previous bug reach the machine.
    """

    class FakeSerialModule:
        SerialException = Exception

    def _service(self, replies: dict[str, str]):
        sent: list[str] = []

        class FakeGantryControllerService(GantryControllerService):
            def _load_serial_module(inner_self):
                return MoveXYWithEncodersIntegrationTests.FakeSerialModule

            def _acquire_connection(inner_self, serial, port, baud_rate):
                return object()

            def _send_command(inner_self, serial_port, command, *, terminal_prefixes, deadline_seconds, active_session=None):
                sent.append(command)
                for prefix, reply in replies.items():
                    if command.startswith(prefix):
                        return reply, True
                return "", False

        return FakeGantryControllerService(), sent

    def _request(self, **overrides):
        from app.models.gantry import GantryXYMoveRequest

        defaults = dict(
            x_cm=1.0, y_cm=1.0, x_step_pin=16, x_dir_pin=17, y_step_pin=18, y_dir_pin=19,
            x_min_limit_pin=21, x_max_limit_pin=22, y_min_limit_pin=23,
        )
        defaults.update(overrides)
        return GantryXYMoveRequest(**defaults)

    def test_a_machine_with_no_encoders_sends_none_of_the_new_commands(self) -> None:
        service, sent = self._service({
            "SET XY PINS": "OK XY PINS", "SET Z PINS": "OK Z PINS",
            "SET XY LIMITS": "OK XY LIMITS", "SET Z LIMITS": "OK Z LIMITS",
            "MOVE XYZ": "OK MOVE XYZ",
        })
        response = service.move_xy(self._request())

        self.assertFalse(any("ENCODER" in c or "PID" in c or "FOLLOW" in c for c in sent))
        self.assertIsNone(response.follow_error_peak_a)
        self.assertFalse(response.follow_error_tripped)

    def test_a_machine_with_encoders_configures_and_reports_error(self) -> None:
        service, sent = self._service({
            "SET XY PINS": "OK XY PINS", "SET Z PINS": "OK Z PINS",
            "SET ENCODER PINS": "OK ENCODER PINS 5 27",
            "SET XY PID": "OK XY PID 0.0000 0.0000 0.0000",
            "SET XY FOLLOW LIMIT": "OK XY FOLLOW LIMIT 205.00",
            "SET XY LIMITS": "OK XY LIMITS", "SET Z LIMITS": "OK Z LIMITS",
            "MOVE XYZ": "FOLLOW ERROR PEAK 8.50 -2.00\nOK MOVE XYZ",
        })
        response = service.move_xy(self._request(encoder_a_cs_pin=5, encoder_b_cs_pin=27))

        self.assertIn("SET ENCODER PINS 5 27", sent)
        self.assertIn("SET XY PID 0.0000 0.0000 0.0000", sent)
        self.assertEqual(response.follow_error_peak_a, 8.50)
        self.assertEqual(response.follow_error_peak_b, -2.00)
        self.assertFalse(response.follow_error_tripped)

    def test_the_encoder_setup_is_sent_before_the_limits(self) -> None:
        # Ordering matters for readability of the wire trace, not correctness -
        # pinned so a future change that reorders it is a deliberate choice.
        service, sent = self._service({
            "SET XY PINS": "OK XY PINS", "SET Z PINS": "OK Z PINS",
            "SET ENCODER PINS": "OK ENCODER PINS 5 27",
            "SET XY PID": "OK XY PID 0.0000 0.0000 0.0000",
            "SET XY FOLLOW LIMIT": "OK XY FOLLOW LIMIT 205.00",
            "SET XY LIMITS": "OK XY LIMITS", "SET Z LIMITS": "OK Z LIMITS",
            "MOVE XYZ": "OK MOVE XYZ",
        })
        service.move_xy(self._request(encoder_a_cs_pin=5, encoder_b_cs_pin=27))

        self.assertLess(sent.index("SET ENCODER PINS 5 27"), sent.index("SET XY LIMITS 4 21 22 23 -1"))

    def test_a_tripped_following_error_is_a_reported_firmware_error(self) -> None:
        # A caller must be told the move stopped for a different reason than a
        # limit switch, so it can be surfaced distinctly rather than lumped in
        # with "something hit a switch."
        service, sent = self._service({
            "SET XY PINS": "OK XY PINS", "SET Z PINS": "OK Z PINS",
            "SET ENCODER PINS": "OK ENCODER PINS 5 27",
            "SET XY PID": "OK XY PID 0.0000 0.0000 0.0000",
            "SET XY FOLLOW LIMIT": "OK XY FOLLOW LIMIT 205.00",
            "SET XY LIMITS": "OK XY LIMITS", "SET Z LIMITS": "OK Z LIMITS",
            "MOVE XYZ": "ERR FOLLOW ERROR XY 300.00 12.00",
        })
        # _send_config_and_action wraps every exception in a plain
        # GantryControllerError (existing behaviour, not new here), so the
        # firmware's own error text is checked instead of the exception's type.
        with self.assertRaises(GantryControllerError) as caught:
            service.move_xy(self._request(encoder_a_cs_pin=5, encoder_b_cs_pin=27))
        self.assertIn("FOLLOW ERROR", str(caught.exception))



class ClosedLoopEncoderCommandTests(unittest.TestCase):
    """Protocol formatting for the AS5047P encoder / PID commands.

    A machine with no encoders wired must behave exactly as it did before this
    feature existed - these commands are only ever built and sent when both
    encoder CS pins are actually configured.
    """

    def _request(self, **overrides):
        from app.models.gantry import GantryXYMoveRequest

        defaults = dict(
            x_cm=1.0, y_cm=1.0, x_step_pin=16, x_dir_pin=17, y_step_pin=18, y_dir_pin=19,
            x_min_limit_pin=21, x_max_limit_pin=22, y_min_limit_pin=23,
        )
        defaults.update(overrides)
        return GantryXYMoveRequest(**defaults)

    def test_no_encoder_command_when_pins_are_unset(self) -> None:
        service = GantryControllerService()
        request = self._request()
        self.assertIsNone(service._build_encoder_pin_command(request))
        self.assertIsNone(service._build_xy_pid_command(request))
        self.assertIsNone(service._build_xy_follow_limit_command(request))

    def test_no_encoder_command_with_only_one_cs_pin_set(self) -> None:
        service = GantryControllerService()
        request = self._request(encoder_a_cs_pin=5)
        self.assertIsNone(service._build_encoder_pin_command(request))

    def test_encoder_pin_command_names_both_chip_selects(self) -> None:
        service = GantryControllerService()
        request = self._request(encoder_a_cs_pin=5, encoder_b_cs_pin=27)
        self.assertEqual(service._build_encoder_pin_command(request), "SET ENCODER PINS 5 27")

    def test_pid_command_sends_all_three_gains(self) -> None:
        service = GantryControllerService()
        request = self._request(
            encoder_a_cs_pin=5, encoder_b_cs_pin=27,
            xy_pid_kp=1.5, xy_pid_ki=0.25, xy_pid_kd=0.1,
        )
        self.assertEqual(service._build_xy_pid_command(request), "SET XY PID 1.5000 0.2500 0.1000")

    def test_pid_command_is_withheld_without_encoders_even_with_nonzero_gains(self) -> None:
        service = GantryControllerService()
        request = self._request(xy_pid_kp=2.0)
        self.assertIsNone(service._build_xy_pid_command(request))

    def test_follow_limit_command_is_sent_with_encoders(self) -> None:
        service = GantryControllerService()
        request = self._request(encoder_a_cs_pin=5, encoder_b_cs_pin=27, xy_follow_limit_counts=150.0)
        self.assertEqual(service._build_xy_follow_limit_command(request), "SET XY FOLLOW LIMIT 150.00")


class FollowErrorReplyParsingTests(unittest.TestCase):
    """Reading the follow-error numbers back out of a move reply."""

    def test_a_reply_with_no_follow_error_lines_reports_nothing(self) -> None:
        peak_a, peak_b, tripped = GantryControllerService._parse_follow_error_reply("OK MOVE XYZ")
        self.assertIsNone(peak_a)
        self.assertIsNone(peak_b)
        self.assertFalse(tripped)

    def test_a_none_reply_reports_nothing(self) -> None:
        peak_a, peak_b, tripped = GantryControllerService._parse_follow_error_reply(None)
        self.assertIsNone(peak_a)
        self.assertFalse(tripped)

    def test_a_successful_move_reports_the_peak_error(self) -> None:
        reply = "ACTIVE XY RPM 400 TRAPEZOID 1 ACCEL 600\nFOLLOW ERROR PEAK 12.50 -3.25\nOK MOVE XYZ"
        peak_a, peak_b, tripped = GantryControllerService._parse_follow_error_reply(reply)
        self.assertEqual(peak_a, 12.50)
        self.assertEqual(peak_b, -3.25)
        self.assertFalse(tripped)

    def test_a_tripped_move_reports_the_error_that_stopped_it(self) -> None:
        reply = "ACTIVE XY RPM 400 TRAPEZOID 1 ACCEL 600\nERR FOLLOW ERROR XY 220.00 15.00"
        peak_a, peak_b, tripped = GantryControllerService._parse_follow_error_reply(reply)
        self.assertEqual(peak_a, 220.00)
        self.assertEqual(peak_b, 15.00)
        self.assertTrue(tripped)

    def test_a_tripped_reply_is_distinguishable_from_a_completed_one(self) -> None:
        tripped_reply = "ERR FOLLOW ERROR XY 300.00 300.00"
        completed_reply = "FOLLOW ERROR PEAK 5.00 5.00\nOK MOVE XYZ"
        _, _, tripped = GantryControllerService._parse_follow_error_reply(tripped_reply)
        _, _, completed_tripped = GantryControllerService._parse_follow_error_reply(completed_reply)
        self.assertTrue(tripped)
        self.assertFalse(completed_tripped)
if __name__ == "__main__":
    unittest.main()
