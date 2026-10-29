"""Deepwell Handling: the step sequence it runs, and what it refuses to start."""

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.deepwell_positions import DeepwellPositionStore

handler = importlib.import_module("app.functions.deepwell_handling.handler")

SETTINGS = {
    "well": "B3", "target_x_cm": 60.0, "target_y_cm": 30.0, "target_z_cm": 8.0,
    "lid_open_deg": 20.0, "lid_grip_deg": -10.0, "lid_grab_z_cm": 12.0,
    "plate_open_deg": 40.0, "plate_grip_deg": 0.0, "plate_grab_z_cm": 10.0,
    "travel_z_left_cm": 1.0, "travel_z_right_cm": 2.0,
}


class DeepwellHandlingTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = DeepwellPositionStore(Path(directory.name) / "wells.json")
        store.save_corners({"A1": (10.0, 20.0), "A6": (10.0, 25.0), "D1": (16.0, 20.0)})  # B3 = (12, 22)

        self.calls: list[tuple[str, dict]] = []
        self.fail_on: str | None = None
        self.held: int | None = 6

        def test_function(function_id, inputs, input_data=None):
            self.calls.append((function_id, inputs))
            if function_id == self.fail_on:
                return SimpleNamespace(ok=False, error="ERR LIMIT", result={})
            if function_id == "pickup_toolhead":
                self.held = int(inputs["toolhead_index"])
            return SimpleNamespace(ok=True, error=None, result={})

        for patch in (
            mock.patch.object(handler, "deepwell_position_store", store),
            mock.patch.object(handler.function_discovery_service, "test_function", side_effect=test_function),
            mock.patch.object(handler.toolhead_state_store, "held_index", side_effect=lambda: self.held),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def _execute(self, action: str, **overrides):
        return handler.execute({"mode": "test"}, {**SETTINGS, "action": action, **overrides})

    def _summary(self):
        out = []
        for function_id, inputs in self.calls:
            if function_id == "move_z":
                out.append(("z", inputs["z_left_cm"], inputs["z_right_cm"]))
            elif function_id == "move_gantry_xy":
                out.append(("xy", inputs["x_cm"], inputs["y_cm"]))
            elif function_id == "gripper":
                key = "left_open_deg" if inputs["action"] == "open" else "left_closed_deg"
                right = "right_open_deg" if inputs["action"] == "open" else "right_closed_deg"
                out.append((inputs["action"], inputs[key], inputs[right]))
            else:
                out.append((function_id,))
        return out

    def test_take_lid_lifts_on_the_right_and_sets_down_on_the_left(self) -> None:
        self._execute("take_lid")
        self.assertEqual(self._summary(), [
            ("z", 1.0, 2.0),
            ("open", 20.0, -20.0),
            ("xy", 12.0, 22.0),
            ("z", 1.0, 12.0),        # right Z lifts the lid into the claws
            ("close", -10.0, 10.0),  # grip
            ("z", 1.0, 2.0),
            ("xy", 60.0, 30.0),
            ("z", 8.0, 2.0),         # left Z rises to the target height
            ("open", 20.0, -20.0),   # release
            ("z", 1.0, 2.0),
        ])

    def test_put_lid_back_is_the_reverse(self) -> None:
        self._execute("put_lid")
        summary = self._summary()
        self.assertEqual(summary[2:5], [("xy", 60.0, 30.0), ("z", 8.0, 2.0), ("close", -10.0, 10.0)])
        self.assertEqual(summary[6:9], [("xy", 12.0, 22.0), ("z", 1.0, 12.0), ("open", 20.0, -20.0)])

    def test_the_plate_uses_its_own_claw_and_grab_settings(self) -> None:
        self._execute("take_plate")
        summary = self._summary()
        self.assertEqual(summary[1], ("open", 40.0, -40.0))
        self.assertEqual(summary[3], ("z", 1.0, 10.0))
        self.assertEqual(summary[4], ("close", 0.0, -0.0))

    def test_sub_blocks_get_their_own_defaults_for_everything_else(self) -> None:
        self._execute("take_lid")
        xy_inputs = next(inputs for function_id, inputs in self.calls if function_id == "move_gantry_xy")
        self.assertIn("trapezoidal_speed", xy_inputs)
        self.assertIn("acceleration_rpm_per_s", xy_inputs)

    def test_the_gripper_is_picked_up_when_the_head_is_empty(self) -> None:
        self.held = None
        self._execute("take_lid")
        self.assertEqual(self.calls[0][0], "pickup_toolhead")
        self.assertEqual(self.calls[0][1]["toolhead_index"], 6)

    def test_another_tool_on_the_head_is_refused(self) -> None:
        self.held = 5
        with self.assertRaisesRegex(handler.DeepwellHandlingError, "Tool 5 is on the head"):
            self._execute("take_lid")
        self.assertEqual(self.calls, [])

    def test_unset_grab_height_is_refused_before_anything_moves(self) -> None:
        with self.assertRaisesRegex(handler.DeepwellHandlingError, "grab height"):
            self._execute("take_lid", lid_grab_z_cm=0.0, travel_z_right_cm=0.0)
        self.assertEqual(self.calls, [])

    def test_an_untaught_well_is_refused_before_anything_moves(self) -> None:
        with mock.patch.object(handler, "deepwell_position_store", DeepwellPositionStore(Path("/nonexistent/x.json"))):
            with self.assertRaisesRegex(Exception, "no position yet"):
                self._execute("take_lid")
        self.assertEqual(self.calls, [])

    def test_a_failure_while_carrying_says_the_lid_may_be_in_the_claws(self) -> None:
        # Fail the first gantry move after the grip: the carry to the target.
        real = handler.function_discovery_service.test_function.side_effect
        moves = []

        def failing(function_id, inputs, input_data=None):
            if function_id == "move_gantry_xy":
                moves.append(inputs)
                if len(moves) == 2:
                    self.calls.append((function_id, inputs))
                    return SimpleNamespace(ok=False, error="ERR FOLLOW ERROR", result={})
            return real(function_id, inputs, input_data)

        handler.function_discovery_service.test_function.side_effect = failing
        with self.assertRaisesRegex(handler.DeepwellHandlingError, r"step 7/10 .*may still be in the claws"):
            self._execute("take_lid")
        self.assertNotIn("Release", str(self.calls[-1]))

    def test_a_failure_before_the_grip_does_not_claim_a_load(self) -> None:
        self.fail_on = "move_gantry_xy"
        with self.assertRaises(handler.DeepwellHandlingError) as caught:
            self._execute("take_lid")
        self.assertNotIn("claws", str(caught.exception))

    def test_a_latched_stop_blocks_the_next_step(self) -> None:
        with mock.patch.object(handler.safety_controller, "raise_if_blocked", side_effect=RuntimeError("E-Stop")):
            with self.assertRaisesRegex(handler.DeepwellHandlingError, "E-Stop"):
                self._execute("take_lid")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
