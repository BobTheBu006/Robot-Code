"""An E-Stop ends every open workflow run.

A run left open after a stop handed its next blocks to a browser still
waiting on the stopped ones; the moment anything re-armed the latch they
started, and the gantry moved again after the E-Stop.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.routes import engine as engine_routes
from app.core.safety import safety_controller
from app.services.run_sessions import run_session_service


def _workflow():
    def node(node_id, block_id, kind="basic"):
        return {"id": node_id, "data": {"block": {"id": block_id, "displayName": node_id, "kind": kind},
                                         "settings": {}, "parameters": {}, "isActive": True}}
    return {
        "nodes": [node("s", "start"), node("a", "wait"), node("b", "wait")],
        "edges": [{"id": "1", "source": "s", "target": "a", "sourceHandle": "next"},
                  {"id": "2", "source": "a", "target": "b", "sourceHandle": "next"}],
    }


class EStopEndsRunsTests(unittest.TestCase):
    def test_the_runs_are_a_safety_actor_stopped_first(self) -> None:
        registered = safety_controller._actors["workflow-runs"]
        lowest = min(entry.priority for entry in safety_controller._actors.values())
        self.assertEqual(registered.priority, lowest)

    def test_stopping_ends_every_open_run(self) -> None:
        session, _plan = run_session_service.start(_workflow())
        run_session_service.due_payload(session)
        run_session_service.stop_all("Stopped by E-Stop.")
        self.assertIsNone(run_session_service.get(session.run_id))
        self.assertFalse(session.runner.report.ok)
        self.assertTrue(session.runner.finished)

    def test_a_result_for_a_stopped_run_hands_out_nothing(self) -> None:
        session, _plan = run_session_service.start(_workflow())
        run_session_service.due_payload(session)
        run_session_service.stop_all("Stopped by E-Stop.")
        with self.assertRaises(Exception) as caught:
            engine_routes.submit_node_result(session.run_id, engine_routes.NodeResultRequest(node_id="s"))
        self.assertEqual(getattr(caught.exception, "status_code", None), 404)

    def test_no_run_starts_while_the_stop_is_latched(self) -> None:
        with mock.patch.object(safety_controller.motion_blocked, "is_set", return_value=True):
            response = engine_routes.start_run(engine_routes.WorkflowGraph(**_workflow()))
        self.assertFalse(response["ok"])
        self.assertEqual(response["due"], [])


if __name__ == "__main__":
    unittest.main()
