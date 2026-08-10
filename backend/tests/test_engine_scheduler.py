"""Scheduling a compiled plan.

Every test here is a behaviour the browser-side runner got wrong. It walked the
graph depth-first over the edge array and ran every node it touched, so `if`
ran both branches, loops ran their body once, joins fired on the first arriving
branch, and error edges were followed even when nothing failed.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.plan import compile_plan
from app.engine.scheduler import NodeOutcome, run_plan


def _node(node_id, block_id, *, kind="advanced", params=None, failure_mode="stop_flow", active=True):
    return {
        "id": node_id,
        "data": {
            "block": {"id": block_id, "displayName": node_id, "kind": kind},
            "settings": {"failureMode": failure_mode, "retryCount": 0},
            "parameters": params or {},
            "isActive": active,
        },
    }


def _edge(source, target, handle="next"):
    return {"id": f"{source}:{handle}->{target}", "source": source, "target": target, "sourceHandle": handle}


def _runner(record, failures=()):
    def run(node, context):
        record.append(node.node_id)
        if node.node_id in failures:
            return NodeOutcome(ok=False, error=f"{node.node_id} failed", result={"status": "error"})
        return NodeOutcome(ok=True, result={"status": "ok", "node": node.node_id})
    return run


class BranchTests(unittest.TestCase):
    def test_if_runs_only_the_true_branch(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("i", "if", kind="basic", params={"condition": "$in.temperature > 40"}),
                _node("hot", "move_z"), _node("cold", "dispense"),
            ],
            "edges": [_edge("s", "i"), _edge("i", "hot", "true"), _edge("i", "cold", "false")],
        })
        self.assertTrue(plan.ok, [p.message for p in plan.errors])

        ran = []
        def run(node, context):
            ran.append(node.node_id)
            if node.node_id == "s":
                return NodeOutcome(result={"temperature": 45})
            return NodeOutcome(result={"status": "ok"})

        report = run_plan(plan, run)
        self.assertTrue(report.ok, report.error)
        self.assertIn("hot", ran)
        self.assertNotIn("cold", ran, "the false branch must not run")

    def test_if_runs_only_the_false_branch(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("i", "if", kind="basic", params={"condition": "$in.temperature > 40"}),
                _node("hot", "move_z"), _node("cold", "dispense"),
            ],
            "edges": [_edge("s", "i"), _edge("i", "hot", "true"), _edge("i", "cold", "false")],
        })
        ran = []
        def run(node, context):
            ran.append(node.node_id)
            return NodeOutcome(result={"temperature": 10} if node.node_id == "s" else {"status": "ok"})

        report = run_plan(plan, run)
        self.assertTrue(report.ok, report.error)
        self.assertIn("cold", ran)
        self.assertNotIn("hot", ran)

    def test_a_condition_that_cannot_be_read_stops_the_run(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("i", "if", kind="basic", params={"condition": "$in.nope > 1"}),
                _node("a", "move_z"),
            ],
            "edges": [_edge("s", "i"), _edge("i", "a", "true")],
        })
        report = run_plan(plan, _runner([]))
        self.assertFalse(report.ok)
        self.assertIn("nope", report.error)


class LoopTests(unittest.TestCase):
    def test_a_for_loop_runs_its_body_the_requested_number_of_times(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("f", "for", kind="basic", params={"iterations": 3}),
                _node("body", "move_z"), _node("after", "dispense"),
            ],
            "edges": [
                _edge("s", "f"), _edge("f", "body", "loop"),
                _edge("body", "f"), _edge("f", "after", "done"),
            ],
        })
        self.assertTrue(plan.ok, [p.message for p in plan.errors])

        ran = []
        report = run_plan(plan, _runner(ran))
        self.assertTrue(report.ok, report.error)
        self.assertEqual(ran.count("body"), 3, "the loop body must run three times")
        self.assertEqual(ran.count("after"), 1)
        self.assertLess(ran.index("body"), ran.index("after"))

    def test_zero_iterations_skips_the_body_entirely(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("f", "for", kind="basic", params={"iterations": 0}),
                _node("body", "move_z"), _node("after", "dispense"),
            ],
            "edges": [_edge("s", "f"), _edge("f", "body", "loop"), _edge("body", "f"), _edge("f", "after", "done")],
        })
        ran = []
        report = run_plan(plan, _runner(ran))
        self.assertTrue(report.ok, report.error)
        self.assertNotIn("body", ran)
        self.assertIn("after", ran)

    def test_a_while_loop_stops_when_the_condition_goes_false(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("w", "while", kind="basic", params={"condition": "$run.iteration < 4"}),
                _node("body", "move_z"), _node("after", "dispense"),
            ],
            "edges": [_edge("s", "w"), _edge("w", "body", "loop"), _edge("body", "w"), _edge("w", "after", "done")],
        })
        ran = []
        report = run_plan(plan, _runner(ran))
        self.assertTrue(report.ok, report.error)
        self.assertEqual(ran.count("body"), 4)
        self.assertIn("after", ran)

    def test_a_runaway_loop_is_stopped_rather_than_running_forever(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("w", "while", kind="basic", params={"condition": "true"}),
                _node("body", "move_z"),
            ],
            "edges": [_edge("s", "w"), _edge("w", "body", "loop"), _edge("body", "w")],
        })
        report = run_plan(plan, _runner([]), max_iterations=50)
        self.assertFalse(report.ok)
        self.assertIn("not ending", report.error)

    def test_loop_over_iterates_the_resolved_items(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("lo", "loop_over", kind="basic", params={"source_path": "items"}),
                _node("body", "dispense"), _node("after", "move_z"),
            ],
            "edges": [_edge("s", "lo"), _edge("lo", "body", "loop"), _edge("body", "lo"), _edge("lo", "after", "done")],
        })
        ran = []
        report = run_plan(plan, _runner(ran), resolve_loop_items=lambda node, ctx: ["a", "b"])
        self.assertTrue(report.ok, report.error)
        self.assertEqual(ran.count("body"), 2)


class JoinTests(unittest.TestCase):
    def test_a_join_waits_for_every_branch(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"), _node("a", "move_z"),
                _node("b", "dispense"), _node("j", "move_z"),
            ],
            "edges": [_edge("s", "a"), _edge("s", "b"), _edge("a", "j"), _edge("b", "j")],
        })
        self.assertEqual(plan.join_node_ids, {"j"})

        ran = []
        report = run_plan(plan, _runner(ran))
        self.assertTrue(report.ok, report.error)
        self.assertEqual(ran.count("j"), 1, "the join must run exactly once, not once per branch")
        self.assertLess(ran.index("a"), ran.index("j"))
        self.assertLess(ran.index("b"), ran.index("j"))

    def test_a_join_downstream_of_an_if_does_not_wait_for_the_untaken_branch(self) -> None:
        # The false branch never runs, so the join must not deadlock on it.
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("i", "if", kind="basic", params={"condition": "true"}),
                _node("t", "move_z"), _node("f", "dispense"), _node("j", "move_z"),
            ],
            "edges": [
                _edge("s", "i"), _edge("i", "t", "true"), _edge("i", "f", "false"),
                _edge("t", "j"), _edge("f", "j"),
            ],
        })
        ran = []
        report = run_plan(plan, _runner(ran))
        self.assertTrue(report.ok, report.error)
        self.assertIn("j", ran)
        self.assertNotIn("f", ran)


class FailureTests(unittest.TestCase):
    def test_a_failed_block_stops_the_run(self) -> None:
        plan = compile_plan({
            "nodes": [_node("s", "start", kind="basic"), _node("a", "move_z"), _node("b", "dispense")],
            "edges": [_edge("s", "a"), _edge("a", "b")],
        })
        ran = []
        report = run_plan(plan, _runner(ran, failures={"a"}))
        self.assertFalse(report.ok)
        self.assertEqual(report.stopped_at, "a")
        self.assertNotIn("b", ran, "downstream work must not run after a failure")

    def test_error_path_is_taken_only_on_failure(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"),
                _node("a", "move_z", failure_mode="separate_path"),
                _node("ok", "dispense"), _node("recover", "dispense"),
            ],
            "edges": [_edge("s", "a"), _edge("a", "ok"), _edge("a", "recover", "error")],
        })

        healthy = []
        report = run_plan(plan, _runner(healthy))
        self.assertTrue(report.ok)
        self.assertIn("ok", healthy)
        self.assertNotIn("recover", healthy, "error path must not run during a healthy run")

        failed = []
        report = run_plan(plan, _runner(failed, failures={"a"}))
        self.assertTrue(report.ok, "an error path handles the failure, so the run continues")
        self.assertIn("recover", failed)
        self.assertNotIn("ok", failed)


class DeactivatedBlockTests(unittest.TestCase):
    def test_a_deactivated_block_is_skipped_but_the_flow_continues(self) -> None:
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"), _node("off", "move_z", active=False), _node("b", "dispense"),
            ],
            "edges": [_edge("s", "off"), _edge("off", "b")],
        })
        ran = []
        report = run_plan(plan, _runner(ran))
        self.assertTrue(report.ok, report.error)
        self.assertNotIn("off", ran)
        self.assertIn("b", ran)


class OrderTests(unittest.TestCase):
    def test_order_follows_the_graph_not_the_edge_array(self) -> None:
        # Edges are listed in an order that a naive DFS would follow literally.
        plan = compile_plan({
            "nodes": [
                _node("s", "start", kind="basic"), _node("first", "move_z"),
                _node("second", "dispense"), _node("third", "move_z"),
            ],
            "edges": [_edge("second", "third"), _edge("s", "first"), _edge("first", "second")],
        })
        ran = []
        report = run_plan(plan, _runner(ran))
        self.assertTrue(report.ok, report.error)
        self.assertEqual(ran, ["s", "first", "second", "third"])


if __name__ == "__main__":
    unittest.main()
