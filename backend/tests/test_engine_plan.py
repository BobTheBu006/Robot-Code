"""Compiling a workflow graph into a validated plan.

Each test here corresponds to something the browser-side runner got wrong by
walking the graph as a plain DFS over the edge array (defects 3-6 in
BACKEND_ARCHITECTURE_V2.md): order followed edge-drawing order, joins fired on
the first branch to arrive, `if` ran both branches, and error edges were taken
during healthy runs.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.plan import PlanProblemLevel, compile_plan


def _node(node_id: str, block_id: str, **data):
    settings = {"failureMode": data.pop("failure_mode", "stop_flow"), "retryCount": data.pop("retry_count", 0)}
    return {
        "id": node_id,
        "data": {
            "block": {"id": block_id, "displayName": data.pop("name", block_id), "kind": data.pop("kind", "advanced")},
            "settings": settings,
            "parameters": data.pop("parameters", {}),
            **data,
        },
    }


def _edge(source: str, target: str, handle: str = "next"):
    return {"id": f"{source}:{handle}->{target}", "source": source, "target": target, "sourceHandle": handle}


def _workflow(nodes, edges):
    return {"nodes": nodes, "edges": edges}


class StartAndShapeTests(unittest.TestCase):
    def test_explicit_start_block_wins_over_orphan_detection(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z"), _node("loose", "move_z")],
            [_edge("s", "a")],
        ))
        self.assertEqual(plan.start_node_ids, ["s"])

    def test_graph_with_no_entry_point_is_rejected(self) -> None:
        # Two nodes feeding each other: nothing can begin.
        plan = compile_plan(_workflow(
            [_node("a", "move_z"), _node("b", "move_z")],
            [_edge("a", "b"), _edge("b", "a")],
        ))
        self.assertFalse(plan.ok)

    def test_edge_to_a_missing_node_is_reported_not_dropped(self) -> None:
        plan = compile_plan(_workflow([_node("s", "start")], [_edge("s", "ghost")]))
        self.assertFalse(plan.ok)
        self.assertIn("not in this workflow", plan.errors[0].message)


class JoinTests(unittest.TestCase):
    def test_a_node_fed_by_two_branches_is_a_join(self) -> None:
        # The old runner fired this on whichever branch arrived first.
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z"), _node("b", "dispense"), _node("j", "move_z")],
            [_edge("s", "a"), _edge("s", "b"), _edge("a", "j"), _edge("b", "j")],
        ))
        self.assertTrue(plan.ok)
        self.assertEqual(plan.join_node_ids, {"j"})

    def test_a_single_incoming_edge_is_not_a_join(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z")],
            [_edge("s", "a")],
        ))
        self.assertEqual(plan.join_node_ids, set())

    def test_an_error_edge_does_not_make_a_join(self) -> None:
        # A node reachable normally and also on failure is not a barrier: the
        # failure path is an alternative, not a second thing to wait for.
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z", failure_mode="separate_path"), _node("h", "move_z")],
            [_edge("s", "a"), _edge("a", "h"), _edge("a", "h", "error")],
        ))
        self.assertEqual(plan.join_node_ids, set())


class BranchTests(unittest.TestCase):
    def test_branch_handles_are_kept_distinct(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("i", "if", kind="basic"), _node("t", "move_z"), _node("f", "dispense")],
            [_edge("s", "i"), _edge("i", "t", "true"), _edge("i", "f", "false")],
        ))
        self.assertTrue(plan.ok)
        self.assertEqual([e.target for e in plan.outgoing_for_handle("i", "true")], ["t"])
        self.assertEqual([e.target for e in plan.outgoing_for_handle("i", "false")], ["f"])

    def test_if_with_only_one_branch_connected_warns(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("i", "if", kind="basic", name="Check"), _node("t", "move_z")],
            [_edge("s", "i"), _edge("i", "t", "true")],
        ))
        self.assertTrue(plan.ok)
        self.assertTrue(any("false" in w.message for w in plan.warnings))


class LoopTests(unittest.TestCase):
    def test_a_loop_body_returning_to_the_loop_is_legal(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("w", "while", kind="basic"), _node("body", "move_z"), _node("after", "dispense")],
            [_edge("s", "w"), _edge("w", "body", "loop"), _edge("body", "w"), _edge("w", "after", "done")],
        ))
        self.assertTrue(plan.ok, [p.message for p in plan.errors])
        self.assertEqual(len(plan.loop_back_edge_ids), 1)

    def test_a_cycle_that_is_not_a_loop_block_is_rejected(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z"), _node("b", "dispense")],
            [_edge("s", "a"), _edge("a", "b"), _edge("b", "a")],
        ))
        self.assertFalse(plan.ok)
        self.assertTrue(any("never finish" in e.message for e in plan.errors))

    def test_a_loop_with_no_body_connected_is_rejected(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("w", "while", kind="basic", name="Repeat"), _node("after", "move_z")],
            [_edge("s", "w"), _edge("w", "after", "done")],
        ))
        self.assertFalse(plan.ok)
        self.assertTrue(any("body would never run" in e.message for e in plan.errors))


class ReachabilityTests(unittest.TestCase):
    def test_orphan_node_is_reported_but_does_not_block_the_run(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z"), _node("orphan", "dispense", name="Left over")],
            [_edge("s", "a")],
        ))
        self.assertTrue(plan.ok)
        self.assertNotIn("orphan", plan.reachable)
        self.assertTrue(any("never reached" in w.message for w in plan.warnings))

    def test_a_node_only_on_an_error_path_is_not_called_orphaned(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z", failure_mode="separate_path"), _node("recover", "dispense")],
            [_edge("s", "a"), _edge("a", "recover", "error")],
        ))
        self.assertTrue(plan.ok)
        self.assertNotIn("recover", plan.reachable)
        self.assertFalse(any("never reached" in w.message for w in plan.warnings))


class FailurePolicyTests(unittest.TestCase):
    def test_error_path_on_a_stop_flow_block_is_flagged_as_dead(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z", name="Move"), _node("h", "dispense")],
            [_edge("s", "a"), _edge("a", "h", "error")],
        ))
        self.assertTrue(plan.ok)
        self.assertTrue(any("can never run" in w.message for w in plan.warnings))

    def test_node_policy_is_carried_into_the_plan(self) -> None:
        plan = compile_plan(_workflow(
            [_node("s", "start"), _node("a", "move_z", failure_mode="separate_path", retry_count=3)],
            [_edge("s", "a")],
        ))
        self.assertEqual(plan.nodes["a"].failure_mode, "separate_path")
        self.assertEqual(plan.nodes["a"].retry_count, 3)


class RealWorkflowTests(unittest.TestCase):
    def test_the_machines_saved_workflow_compiles(self) -> None:
        path = Path(__file__).resolve().parents[2] / "workflows" / "active-workflow.json"
        if not path.exists():
            self.skipTest("no saved workflow on this machine")
        import json

        plan = compile_plan(json.loads(path.read_text(encoding="utf-8")))
        self.assertTrue(plan.ok, [p.message for p in plan.errors])


if __name__ == "__main__":
    unittest.main()
