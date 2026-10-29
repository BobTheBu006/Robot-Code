"""Typing a position into the hand-teach dialog drives the gantry there."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from app.api.routes import xy_teach
from app.services.gantry_controller import GantryControllerError


class TeachGotoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple] = []
        self.fail_goto = False
        controller = mock.Mock()

        def teach(request, action):
            self.calls.append(("teach", action))
            return {"x_cm": 12.5, "y_cm": 30.0, "encoders_ok": True}

        def goto_xy(request):
            self.calls.append(("goto", request.x_cm, request.y_cm, request.speed_rpm))
            if self.fail_goto:
                raise GantryControllerError("ERR ESTOP XY LIMIT X_MAX")

        controller.teach.side_effect = teach
        controller.goto_xy.side_effect = goto_xy
        for patch in (
            mock.patch.object(xy_teach, "gantry_controller_service", controller),
            mock.patch.object(xy_teach.hardware_map_service, "apply_function_defaults", lambda _m, inputs: dict(inputs)),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def test_leaves_teach_mode_moves_gently_and_comes_back(self) -> None:
        result = xy_teach.xy_teach("goto", {"goto_x_cm": 12.5, "goto_y_cm": 30})
        self.assertEqual(self.calls, [("teach", "end"), ("goto", 12.5, 30.0, 200), ("teach", "start")])
        self.assertEqual(result["x_cm"], 12.5)

    def test_teach_mode_is_resumed_even_when_the_move_fails(self) -> None:
        self.fail_goto = True
        with self.assertRaises(HTTPException) as caught:
            xy_teach.xy_teach("goto", {"goto_x_cm": 120, "goto_y_cm": 30})
        self.assertIn("X_MAX", caught.exception.detail)
        self.assertEqual(self.calls[-1], ("teach", "start"))

    def test_a_missing_target_moves_nothing(self) -> None:
        with self.assertRaises(HTTPException):
            xy_teach.xy_teach("goto", {"goto_x_cm": 10})
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
