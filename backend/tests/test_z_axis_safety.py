"""Keeping the Z position honest across aborts, and refusing blind moves.

Both behaviours exist because of the same underlying fact: the Z axis tracks
its position by counting steps it believes it issued. Anything that makes that
count disagree with the carriage - an abort part way, or a move against a
workspace that was never measured - is a position the machine cannot recover
without homing again.
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("ROBOT_GPIO_SIMULATE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.hybrid_z_axis import HybridZAxisError, HybridZAxisService


class StepCountParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = HybridZAxisService()

    def test_a_completed_burst_reports_what_it_did(self) -> None:
        self.assertEqual(self.service._parse_step_done("OK STEP Z 1200 -800", 0, 0), (1200, -800))

    def test_an_aborted_burst_reports_how_far_it_got(self) -> None:
        # The whole point: 37 steps travelled out of 1200 commanded.
        self.assertEqual(self.service._parse_step_done("OK STOP STEP Z 37 0", 1200, 0), (37, 0))

    def test_the_counts_are_signed_so_direction_survives(self) -> None:
        self.assertEqual(self.service._parse_step_done("OK STOP STEP Z -450 -450", -1000, -1000), (-450, -450))

    def test_boot_chatter_before_the_reply_is_ignored(self) -> None:
        reply = "rst:0x1 (POWERON_RESET)\nload:0x3fff0030\nOK STEP Z 900 900"
        self.assertEqual(self.service._parse_step_done(reply, 0, 0), (900, 900))

    def test_an_unreadable_reply_falls_back_to_what_was_commanded(self) -> None:
        # Not ideal, but the best guess available - and it keeps the tracked
        # position moving in the right direction rather than freezing it.
        self.assertEqual(self.service._parse_step_done("garbled", 500, -500), (500, -500))

    def test_a_missing_reply_falls_back_too(self) -> None:
        self.assertEqual(self.service._parse_step_done(None, 10, 20), (10, 20))


class CalibrationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = HybridZAxisService()

    def _calibration(self, left: bool, right: bool) -> None:
        self.service._left_calibrated = left
        self.service._right_calibrated = right

    def test_a_move_on_an_uncalibrated_side_is_refused(self) -> None:
        self._calibration(left=False, right=True)
        with self.assertRaises(HybridZAxisError) as caught:
            self.service._assert_sides_calibrated(500, 0)
        self.assertIn("left", str(caught.exception))
        self.assertIn("Calibrate Z Axis", str(caught.exception))

    def test_the_calibrated_side_can_still_move(self) -> None:
        self._calibration(left=False, right=True)
        self.service._assert_sides_calibrated(0, 500)

    def test_holding_an_uncalibrated_side_still_is_allowed(self) -> None:
        # Commanding a side to where it already sits is how one axis is moved
        # while the other is left alone. No motion means no calibration needed.
        self._calibration(left=False, right=True)
        self.service._assert_sides_calibrated(0, 500)

    def test_both_uncalibrated_sides_are_named_together(self) -> None:
        self._calibration(left=False, right=False)
        with self.assertRaises(HybridZAxisError) as caught:
            self.service._assert_sides_calibrated(100, 100)
        message = str(caught.exception)
        self.assertIn("left", message)
        self.assertIn("right", message)

    def test_a_fully_calibrated_axis_moves_freely(self) -> None:
        self._calibration(left=True, right=True)
        self.service._assert_sides_calibrated(-2000, 2000)

    def test_a_zero_move_never_needs_calibration(self) -> None:
        self._calibration(left=False, right=False)
        self.service._assert_sides_calibrated(0, 0)


if __name__ == "__main__":
    unittest.main()
