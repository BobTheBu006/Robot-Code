"""An edited X Calibration Y on a Calibrate XY block becomes the default."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.workspace_defaults import WorkspaceDefaultsService

FUNCTIONS = Path(__file__).resolve().parents[1] / "app" / "functions"


def workflow(*blocks: tuple[str, float]) -> dict:
    return {"nodes": [
        {"id": node_id, "data": {"block": {"id": "calibrate_xy"}, "parameters": {"x_calibration_y_cm": value}}}
        for node_id, value in blocks
    ]}


class CalibrateDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        functions = Path(directory.name) / "functions"
        shutil.copytree(FUNCTIONS / "calibrate_xy", functions / "calibrate_xy")
        self.manifest = functions / "calibrate_xy" / "manifest.json"
        self.service = WorkspaceDefaultsService(Path(directory.name), functions)
        self.start = self.default()

    def default(self) -> float:
        manifest = json.loads(self.manifest.read_text())
        return next(d["default"] for d in manifest["inputs"] if d["key"] == "x_calibration_y_cm")

    def test_an_edited_value_becomes_the_default(self) -> None:
        self.service.adopt_calibrate_defaults_from_workflow(workflow(("c1", 4.0)), workflow(("c1", self.start)))
        self.assertEqual(self.default(), 4.0)

    def test_a_new_block_with_a_different_value_is_adopted(self) -> None:
        self.service.adopt_calibrate_defaults_from_workflow(workflow(("c1", 3.7)), None)
        self.assertEqual(self.default(), 3.7)

    def test_an_untouched_old_block_does_not_undo_the_edit(self) -> None:
        # c2 still carries the value it was placed with; only c1 was edited.
        self.service.adopt_calibrate_defaults_from_workflow(
            workflow(("c1", 4.0), ("c2", 1.0)), workflow(("c1", 2.0), ("c2", 1.0))
        )
        self.assertEqual(self.default(), 4.0)

    def test_nothing_changed_writes_nothing(self) -> None:
        changed = self.service.adopt_calibrate_defaults_from_workflow(
            workflow(("c1", 1.0)), workflow(("c1", 1.0))
        )
        self.assertEqual(changed, [])
        self.assertEqual(self.default(), self.start)


if __name__ == "__main__":
    unittest.main()
