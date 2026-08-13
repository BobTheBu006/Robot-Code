"""A Z calibration becoming the app's defaults and allowed ranges.

The point is that the app follows the machine as measured, rather than numbers
typed in once and never revisited: what an operator measures during calibration
is what the next block offers, and a Move Z block cannot offer a target the
carriage physically cannot reach.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("ROBOT_GPIO_SIMULATE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.workspace_defaults import WorkspaceDefaultsService, usable_max_cm


def _manifest(inputs, advanced=None):
    return {"inputs": inputs, "advanced_inputs": advanced or []}


def _number(key, default=0.0, minimum=None, maximum=None):
    return {"key": key, "label": key, "type": "number", "default": default,
            "min": minimum, "max": maximum, "options": []}


class ZWriteBackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        root = Path(self._dir.name)
        self.functions = root / "functions"

        (self.functions / "calibrate_z").mkdir(parents=True)
        (self.functions / "calibrate_z" / "manifest.json").write_text(json.dumps(_manifest([
            _number("z_left_track_length_cm", 60.0),
            _number("z_right_track_length_cm", 60.0),
            _number("limit_buffer_cm", 0.5),
        ])), encoding="utf-8")

        (self.functions / "move_z").mkdir(parents=True)
        (self.functions / "move_z" / "manifest.json").write_text(json.dumps(_manifest([
            _number("z_left_cm"),
            _number("z_right_cm"),
            _number("speed_rpm", 240.0),
        ])), encoding="utf-8")

        self.service = WorkspaceDefaultsService(root, self.functions)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _read(self, function_id):
        path = self.functions / function_id / "manifest.json"
        return {i["key"]: i for i in json.loads(path.read_text(encoding="utf-8"))["inputs"]}

    def test_move_z_gets_a_range_from_the_calibration(self) -> None:
        self.service.apply_z_track_lengths(50.0, 50.0, 0.5)
        inputs = self._read("move_z")
        self.assertEqual(inputs["z_left_cm"]["min"], 0.0)
        self.assertEqual(inputs["z_left_cm"]["max"], usable_max_cm(50.0, 0.5))

    def test_each_side_gets_its_own_range(self) -> None:
        # The two screws are calibrated independently and rarely measure the
        # same; one shared maximum would let a block overshoot the shorter one.
        self.service.apply_z_track_lengths(60.0, 55.0, 0.5)
        inputs = self._read("move_z")
        self.assertEqual(inputs["z_left_cm"]["max"], usable_max_cm(60.0, 0.5))
        self.assertEqual(inputs["z_right_cm"]["max"], usable_max_cm(55.0, 0.5))
        self.assertNotEqual(inputs["z_left_cm"]["max"], inputs["z_right_cm"]["max"])

    def test_the_range_is_inset_by_the_limit_buffer(self) -> None:
        # The usable maximum stops short of the switch, or a move to "max"
        # would drive into it.
        self.service.apply_z_track_lengths(60.0, 60.0, 2.0)
        self.assertLess(self._read("move_z")["z_left_cm"]["max"], 60.0)

    def test_measured_track_lengths_become_the_calibration_defaults(self) -> None:
        self.service.apply_z_track_lengths(58.4, 57.9, 0.5)
        inputs = self._read("calibrate_z")
        self.assertEqual(inputs["z_left_track_length_cm"]["default"], 58.4)
        self.assertEqual(inputs["z_right_track_length_cm"]["default"], 57.9)

    def test_the_buffer_is_adopted_too(self) -> None:
        self.service.apply_z_track_lengths(60.0, 60.0, 1.25)
        self.assertEqual(self._read("calibrate_z")["limit_buffer_cm"]["default"], 1.25)

    def test_unrelated_inputs_are_left_alone(self) -> None:
        self.service.apply_z_track_lengths(60.0, 60.0, 0.5)
        speed = self._read("move_z")["speed_rpm"]
        self.assertEqual(speed["default"], 240.0)
        self.assertIsNone(speed["max"], "speed is not derived from track length")

    def test_recalibrating_narrower_shrinks_the_range(self) -> None:
        # A later, shorter calibration has to reduce the allowed range, not
        # leave a stale wider one that permits an unreachable target.
        self.service.apply_z_track_lengths(60.0, 60.0, 0.5)
        wide = self._read("move_z")["z_left_cm"]["max"]
        self.service.apply_z_track_lengths(40.0, 40.0, 0.5)
        self.assertLess(self._read("move_z")["z_left_cm"]["max"], wide)

    def test_applying_the_same_values_reports_no_change(self) -> None:
        self.service.apply_z_track_lengths(60.0, 60.0, 0.5)
        again = self.service.apply_z_track_lengths(60.0, 60.0, 0.5)
        self.assertEqual(again["changed"], [])

    def test_the_summary_reports_the_usable_maxima(self) -> None:
        out = self.service.apply_z_track_lengths(60.0, 55.0, 0.5)
        self.assertEqual(out["usable_left_max_cm"], usable_max_cm(60.0, 0.5))
        self.assertEqual(out["usable_right_max_cm"], usable_max_cm(55.0, 0.5))

    def test_a_missing_manifest_is_skipped_rather_than_raising(self) -> None:
        # A machine without the Z blocks installed must still calibrate.
        import shutil

        shutil.rmtree(self.functions / "move_z")
        self.service.apply_z_track_lengths(60.0, 60.0, 0.5)


if __name__ == "__main__":
    unittest.main()
