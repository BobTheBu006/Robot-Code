"""The 24 deepwells: a grid from three taught corners, single wells overridable."""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.deepwell_positions import DeepwellPositionError, DeepwellPositionStore, WELL_NAMES


class GridTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = DeepwellPositionStore(Path(directory.name) / "wells.json")

    def test_there_are_24_wells_a_to_d_by_1_to_6(self) -> None:
        self.assertEqual(len(WELL_NAMES), 24)
        self.assertEqual((WELL_NAMES[0], WELL_NAMES[5], WELL_NAMES[-1]), ("A1", "A6", "D6"))

    def test_the_corners_span_the_whole_grid(self) -> None:
        # Columns 2 cm apart in X, rows 1 cm apart in Y.
        self.store.save_corners({"A1": (10.0, 20.0), "A6": (10.0, 25.0), "D1": (16.0, 20.0)})
        self.assertEqual(self.store.position("A1"), (10.0, 20.0))
        self.assertEqual(self.store.position("B3"), (12.0, 22.0))
        self.assertEqual(self.store.position("D6"), (16.0, 25.0))

    def test_a_slightly_rotated_rack_is_followed(self) -> None:
        # The rows drift +0.1 cm in X over 5 steps; the far corner follows.
        self.store.save_corners({"A1": (10.0, 20.0), "A6": (10.1, 25.0), "D1": (16.0, 20.0)})
        x, y = self.store.position("D6")
        self.assertAlmostEqual(x, 16.1)
        self.assertAlmostEqual(y, 25.0)

    def test_a_taught_well_overrides_the_grid(self) -> None:
        self.store.save_corners({"A1": (10.0, 20.0), "A6": (10.0, 25.0), "D1": (16.0, 20.0)})
        self.store.save_overrides({"b3": (12.2, 21.9)})
        self.assertEqual(self.store.position("B3"), (12.2, 21.9))
        self.assertEqual(self.store.positions()["B3"]["source"], "taught")
        self.assertEqual(self.store.positions()["B4"]["source"], "grid")

    def test_new_corners_reset_old_overrides(self) -> None:
        # A re-taught grid means the rack was placed again.
        self.store.save_corners({"A1": (10.0, 20.0), "A6": (10.0, 25.0), "D1": (16.0, 20.0)})
        self.store.save_overrides({"B3": (12.2, 21.9)})
        self.store.save_corners({"A1": (11.0, 20.0), "A6": (11.0, 25.0), "D1": (17.0, 20.0)})
        self.assertEqual(self.store.positions()["B3"]["source"], "grid")

    def test_a_grid_needs_all_three_corners(self) -> None:
        with self.assertRaisesRegex(DeepwellPositionError, "missing D1"):
            self.store.save_corners({"A1": (10.0, 20.0), "A6": (10.0, 25.0)})

    def test_an_untaught_well_is_refused_loudly(self) -> None:
        with self.assertRaisesRegex(DeepwellPositionError, "no position yet"):
            self.store.position("C2")

    def test_an_unknown_well_is_refused(self) -> None:
        with self.assertRaisesRegex(DeepwellPositionError, "Unknown deepwell"):
            self.store.position("E1")


class TeachDeepwellBlockTests(unittest.TestCase):
    def _execute(self, mode, positions):
        module = importlib.import_module("app.functions.teach_deepwell_positions.handler")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = DeepwellPositionStore(Path(directory.name) / "wells.json")
        with mock.patch.object(module, "deepwell_position_store", store):
            return module.execute({"mode": "test"}, {"mode": mode, "positions": json.dumps(positions)}), store

    def test_corners_build_the_grid(self) -> None:
        result, store = self._execute("corners", {
            "A1": {"x_cm": 10, "y_cm": 20}, "A6": {"x_cm": 10, "y_cm": 25}, "D1": {"x_cm": 16, "y_cm": 20},
        })
        self.assertEqual(len(result["wells"]), 24)
        self.assertEqual(store.position("C4"), (14.0, 23.0))

    def test_individual_wells_are_saved_as_overrides(self) -> None:
        result, store = self._execute("individual", {"c4": {"x_cm": 14.3, "y_cm": 23.1}})
        self.assertEqual(store.position("C4"), (14.3, 23.1))
        self.assertIn("C4", result["saved"])

    def test_incomplete_corners_fail_loudly(self) -> None:
        with self.assertRaises(DeepwellPositionError):
            self._execute("corners", {"A1": {"x_cm": 10, "y_cm": 20}})


if __name__ == "__main__":
    unittest.main()
