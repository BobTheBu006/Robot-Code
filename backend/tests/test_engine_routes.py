"""Driving a run through the HTTP engine, the way the browser does.

The browser executes blocks and reports results; the engine decides what runs
next. These tests walk that conversation end to end, so a regression in the
route shape shows up here rather than on the machine.
"""

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("ROBOT_GPIO_SIMULATE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.main import app


def _node(node_id, block_id, *, kind="advanced", params=None):
    return {
        "id": node_id,
        "data": {
            "block": {"id": block_id, "displayName": node_id, "kind": kind},
            "settings": {"failureMode": "stop_flow", "retryCount": 0},
            "parameters": params or {},
            "isActive": True,
        },
    }


def _edge(source, target, handle="next"):
    return {"id": f"{source}:{handle}->{target}", "source": source, "target": target, "sourceHandle": handle}


class EnginePlanRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_a_broken_graph_is_described_rather_than_run(self) -> None:
        # A loop wired onwards but with nothing on its body handle: it looks
        # connected on the canvas and can never do anything.
        response = self.client.post("/api/engine/plan", json={
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("w", "while", kind="basic"),
                _node("after", "move_z"),
            ],
            "edges": [_edge("s", "w"), _edge("w", "after", "done")],
        })
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertTrue(any("body would never run" in p["message"] for p in body["problems"]))

    def test_a_healthy_graph_plans_cleanly(self) -> None:
        response = self.client.post("/api/engine/plan", json={
            "nodes": [_node("s", "start", kind="basic"), _node("a", "move_z")],
            "edges": [_edge("s", "a")],
        })
        self.assertTrue(response.json()["ok"])


class EngineRunRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def _drive(self, workflow, outcomes=None):
        """Play the browser: execute whatever is due, report, repeat."""
        outcomes = outcomes or {}
        started = self.client.post("/api/engine/runs", json=workflow).json()
        if not started["ok"]:
            return started, []

        run_id = started["run_id"]
        executed = []
        due = started["due"]
        last = started

        while due:
            for item in due:
                executed.append(item["node_id"])
                payload = outcomes.get(item["node_id"], {"ok": True, "result": {"status": "ok"}})
                last = self.client.post(
                    f"/api/engine/runs/{run_id}/results",
                    json={"node_id": item["node_id"], **payload},
                ).json()
            due = last["due"]
            if last["finished"]:
                break

        return last, executed

    def test_an_if_takes_one_branch(self) -> None:
        workflow = {
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("i", "if", kind="basic", params={"condition": "$in.temperature > 40"}),
                _node("hot", "move_z"), _node("cold", "dispense"),
            ],
            "edges": [_edge("s", "i"), _edge("i", "hot", "true"), _edge("i", "cold", "false")],
        }
        final, executed = self._drive(workflow, outcomes={
            "s": {"ok": True, "result": {"temperature": 45}},
        })
        self.assertTrue(final["ok"], final.get("report"))
        self.assertIn("hot", executed)
        self.assertNotIn("cold", executed)

    def test_a_for_loop_runs_its_body_each_time(self) -> None:
        workflow = {
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("f", "for", kind="basic", params={"iterations": 3}),
                _node("body", "move_z"), _node("after", "dispense"),
            ],
            "edges": [_edge("s", "f"), _edge("f", "body", "loop"), _edge("body", "f"), _edge("f", "after", "done")],
        }
        final, executed = self._drive(workflow)
        self.assertTrue(final["ok"], final.get("report"))
        self.assertEqual(executed.count("body"), 3)
        self.assertIn("after", executed)

    def test_a_failed_block_stops_the_run(self) -> None:
        workflow = {
            "nodes": [_node("s", "start", kind="basic"), _node("a", "move_z"), _node("b", "dispense")],
            "edges": [_edge("s", "a"), _edge("a", "b")],
        }
        final, executed = self._drive(workflow, outcomes={
            "a": {"ok": False, "error": "Limit switch tripped", "result": {"status": "error"}},
        })
        self.assertFalse(final["ok"])
        self.assertNotIn("b", executed)
        self.assertIn("Limit switch tripped", final["report"]["error"])

    def test_a_broken_graph_never_opens_a_run(self) -> None:
        started = self.client.post("/api/engine/runs", json={
            "nodes": [_node("a", "move_z"), _node("b", "dispense")],
            "edges": [_edge("a", "b"), _edge("b", "a")],
        }).json()
        self.assertFalse(started["ok"])
        self.assertIsNone(started["run_id"])

    def test_reporting_against_an_unknown_run_is_refused(self) -> None:
        response = self.client.post(
            "/api/engine/runs/nosuchrun/results",
            json={"node_id": "a", "ok": True, "result": {}},
        )
        self.assertEqual(response.status_code, 404)

    def test_a_run_can_be_ended_early(self) -> None:
        started = self.client.post("/api/engine/runs", json={
            "nodes": [_node("s", "start", kind="basic"), _node("a", "move_z")],
            "edges": [_edge("s", "a")],
        }).json()
        ended = self.client.post(
            f"/api/engine/runs/{started['run_id']}/end",
            json={"reason": "Access door opened."},
        ).json()
        self.assertTrue(ended["finished"])
        self.assertIn("Access door", ended["report"]["error"])


if __name__ == "__main__":
    unittest.main()
