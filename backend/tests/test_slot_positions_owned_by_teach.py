"""Rack slot positions are owned by Teach Tool Positions.

Saving a workflow used to adopt every Pick Up / Drop block's parameters as the
new defaults - including a stale copy of the slot positions - and on the
machine that silently undid a teach. Other tool settings still carry over.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.workspace_defaults import workspace_defaults_service


class SaveDoesNotAdoptSlotPositionsTests(unittest.TestCase):
    def _adopted(self, parameters: dict) -> dict:
        workflow = {"nodes": [{"data": {"block": {"id": "pickup_toolhead"}, "parameters": parameters}}]}
        with mock.patch.object(workspace_defaults_service, "apply_toolhead_defaults", return_value=[]) as apply:
            workspace_defaults_service.adopt_toolhead_defaults_from_workflow(workflow)
        return apply.call_args.args[0] if apply.called else {}

    def test_stale_slot_positions_in_a_saved_block_are_ignored(self) -> None:
        adopted = self._adopted({"tool_1_x_cm": 0.0, "tool_1_y_cm": 2.5, "dip_depth_cm": 1.6})
        self.assertNotIn("tool_1_x_cm", adopted)
        self.assertNotIn("tool_1_y_cm", adopted)

    def test_other_tool_settings_still_carry_over(self) -> None:
        self.assertEqual(self._adopted({"dip_depth_cm": 1.6})["dip_depth_cm"], 1.6)


if __name__ == "__main__":
    unittest.main()
