"""One CoreXY direction convention across the XY firmware.

Measured on the machine (2026-10-27): DIR LOW on motor A alone moves the
carriage X+Y+, DIR LOW on both motors moves pure +X. With A = X+Y and B = X-Y,
a positive A or B is LOW (XY_DIR_TOWARD_X_MAX) everywhere. The firmware once
mixed conventions: Move XY drove the wrong way and calibration homed Y into
+Y. These checks read the source, since the firmware has no host-side tests.
"""

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIRMWARE = Path(__file__).resolve().parents[2] / "functions/esp 32 code/esp32 xy-closed-loop/firmware/main.ino"


class DirectionConventionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = FIRMWARE.read_text()

    def test_toward_x_max_is_low(self) -> None:
        self.assertIn("const int XY_DIR_TOWARD_X_MAX = LOW;", self.source)

    def test_no_cartesian_move_maps_a_positive_delta_to_high(self) -> None:
        for line in re.findall(r"digitalWrite\((?:xAxis|yAxis)\.dirPin, [ab]Positive \? [^;]+;", self.source):
            self.assertNotRegex(line, r"Positive \? HIGH", line)

    def test_y_homing_toward_min_drives_a_negative_and_b_positive(self) -> None:
        self.assertIn("digitalWrite(xAxis.dirPin, towardMin ? XY_DIR_TOWARD_X_MIN : XY_DIR_TOWARD_X_MAX);", self.source)
        self.assertIn("digitalWrite(yAxis.dirPin, towardMin ? XY_DIR_TOWARD_X_MAX : XY_DIR_TOWARD_X_MIN);", self.source)


if __name__ == "__main__":
    unittest.main()
