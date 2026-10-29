"""Edited advanced settings on the tool blocks become both blocks' defaults."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.workspace_defaults import WorkspaceDefaultsService

FUNCTIONS = Path(__file__).resolve().parents[1] / "app" / "functions"


def workflow(*blocks: tuple[str, str, dict]) -> dict:
    return {"nodes": [
        {"id": node_id, "data": {"block": {"id": function_id}, "parameters": parameters}}
        for node_id, function_id, parameters in blocks
    ]}


class ToolSettingsAdoptedTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        functions = Path(directory.name) / "functions"
        for function_id in ("pickup_toolhead", "drop_toolhead"):
            shutil.copytree(FUNCTIONS / function_id, functions / function_id)
        self.functions = functions
        self.service = WorkspaceDefaultsService(Path(directory.name), functions)

    def default(self, function_id: str, key: str):
        manifest = json.loads((self.functions / function_id / "manifest.json").read_text())
        return next(d["default"] for d in [*manifest["inputs"], *manifest["advanced_inputs"]] if d["key"] == key)

    def test_every_advanced_setting_but_the_pins_is_adoptable(self) -> None:
        keys = self.service.toolhead_adoptable_keys()
        for key in ("pickup_clearance_cm", "drop_clearance_cm", "rack_approach_speed_rpm", "home_speed_rpm",
                    "verify_x_home", "contact_settle_seconds", "tool_3_y_cm"):
            self.assertIn(key, keys)
        self.assertFalse([key for key in keys if "pin" in key])

    def test_an_edit_on_one_block_becomes_the_default_of_both(self) -> None:
        before = workflow(("p", "pickup_toolhead", {"rack_approach_speed_rpm": 200.0}))
        after = workflow(("p", "pickup_toolhead", {"rack_approach_speed_rpm": 150.0}))
        self.service.adopt_toolhead_defaults_from_workflow(after, before)
        self.assertEqual(self.default("pickup_toolhead", "rack_approach_speed_rpm"), 150.0)
        self.assertEqual(self.default("drop_toolhead", "rack_approach_speed_rpm"), 150.0)

    def test_a_switch_stays_a_switch(self) -> None:
        before = workflow(("d", "drop_toolhead", {"verify_x_home": True}))
        after = workflow(("d", "drop_toolhead", {"verify_x_home": False}))
        self.service.adopt_toolhead_defaults_from_workflow(after, before)
        self.assertIs(self.default("pickup_toolhead", "verify_x_home"), False)

    def test_an_untouched_older_block_does_not_undo_an_edit(self) -> None:
        before = workflow(("p", "pickup_toolhead", {"pickup_clearance_cm": 2.0}),
                          ("old", "drop_toolhead", {"pickup_clearance_cm": 2.0}))
        after = workflow(("p", "pickup_toolhead", {"pickup_clearance_cm": 10.0}),
                         ("old", "drop_toolhead", {"pickup_clearance_cm": 2.0}))
        self.service.adopt_toolhead_defaults_from_workflow(after, before)
        self.assertEqual(self.default("drop_toolhead", "pickup_clearance_cm"), 10.0)

    def test_an_edited_slot_position_is_adopted(self) -> None:
        before = workflow(("p", "pickup_toolhead", {"tool_2_y_cm": 12.575}))
        after = workflow(("p", "pickup_toolhead", {"tool_2_y_cm": 12.6}))
        self.service.adopt_toolhead_defaults_from_workflow(after, before)
        self.assertEqual(self.default("drop_toolhead", "tool_2_y_cm"), 12.6)

    def test_a_slot_position_without_a_previous_save_is_never_adopted(self) -> None:
        # Could be a block placed before the last teach.
        start = self.default("pickup_toolhead", "tool_2_y_cm")
        self.service.adopt_toolhead_defaults_from_workflow(workflow(("p", "pickup_toolhead", {"tool_2_y_cm": 1.0})), None)
        self.assertEqual(self.default("pickup_toolhead", "tool_2_y_cm"), start)


if __name__ == "__main__":
    unittest.main()
