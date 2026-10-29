"""Paths run side by side unless they need the same hardware.

A path is a straight run of blocks. When its first block is due it claims the
hardware of the whole path; a path needing hardware another path holds waits
until that path has finished. The first test is the workflow that stopped
after the two calibrations: two Z paths and an XY path leaving Start.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.plan import compile_plan
from app.engine.scheduler import ALL_HARDWARE, NodeOutcome, PlanRunner

HARDWARE = {
    "calibrate_xy": {"board:xy"},
    "move_gantry_xy": {"board:xy"},
    "pickup_toolhead": {"board:xy", "toolhead"},
    "calibrate_z": {"board:z", "pi:z-switches"},
    "move_z": {"board:z", "pi:z-switches"},
    "run_pumps": {"board:z"},
    "dispense": {"board:syringe"},
    "deepwell_handling": {ALL_HARDWARE},
}


def _node(node_id, block_id, *, kind="advanced", active=True, failure_mode="stop_flow"):
    return {
        "id": node_id,
        "data": {
            "block": {"id": block_id, "displayName": node_id, "kind": kind},
            "settings": {"failureMode": failure_mode, "retryCount": 0},
            "parameters": {},
            "isActive": active,
        },
    }


def _edge(source, target, handle="next"):
    return {"id": f"{source}:{handle}->{target}", "source": source, "target": target, "sourceHandle": handle}


def _runner(nodes, edges) -> PlanRunner:
    plan = compile_plan({"nodes": nodes, "edges": edges})
    assert plan.ok, [problem.message for problem in plan.errors]
    return PlanRunner(plan, hardware_for=lambda node: frozenset(HARDWARE.get(node.block_id, set())))


def _due(runner: PlanRunner) -> set[str]:
    return {item.node.node_id for item in runner.advance()}


def _finish(runner: PlanRunner, node_id: str, ok: bool = True) -> set[str]:
    runner.submit(node_id, NodeOutcome(ok=ok, result={}, error=None if ok else "failed"))
    return _due(runner)


class HardwarePathTests(unittest.TestCase):
    def test_the_second_z_path_waits_for_the_whole_first_z_path(self) -> None:
        runner = _runner(
            [
                _node("start", "start", kind="basic"),
                _node("cal_xy", "calibrate_xy"),
                _node("cal_z1", "calibrate_z"), _node("move_z", "move_z"),
                _node("cal_z2", "calibrate_z"),
                _node("pickup", "pickup_toolhead"),
            ],
            [
                _edge("start", "cal_z1"), _edge("start", "cal_xy"), _edge("start", "cal_z2"),
                _edge("cal_z1", "move_z"), _edge("move_z", "pickup"),
                _edge("cal_xy", "pickup"), _edge("cal_z2", "pickup"),
            ],
        )
        self.assertEqual(_due(runner), {"start"})
        # XY and the first Z path start together; the second Z path waits.
        self.assertEqual(_finish(runner, "start"), {"cal_z1", "cal_xy"})
        # Not between the first calibration and its Move Z.
        self.assertEqual(_finish(runner, "cal_z1"), {"move_z"})
        self.assertEqual(_finish(runner, "move_z"), {"cal_z2"})
        self.assertEqual(_finish(runner, "cal_xy"), set())
        self.assertEqual(_finish(runner, "cal_z2"), {"pickup"})
        self.assertEqual(_finish(runner, "pickup"), set())
        self.assertTrue(runner.finished)
        self.assertTrue(runner.report.ok)

    def test_paths_on_different_hardware_all_run_at_once(self) -> None:
        runner = _runner(
            [_node("start", "start", kind="basic"), _node("xy", "move_gantry_xy"),
             _node("z", "move_z"), _node("syringe", "dispense")],
            [_edge("start", "xy"), _edge("start", "z"), _edge("start", "syringe")],
        )
        _due(runner)
        self.assertEqual(_finish(runner, "start"), {"xy", "z", "syringe"})

    def test_one_board_is_one_resource(self) -> None:
        # The pumps and the Z motors share an ESP32 that runs one command at a time.
        runner = _runner(
            [_node("start", "start", kind="basic"), _node("z", "move_z"), _node("pumps", "run_pumps")],
            [_edge("start", "z"), _edge("start", "pumps")],
        )
        _due(runner)
        self.assertEqual(_finish(runner, "start"), {"z"})
        self.assertEqual(_finish(runner, "z"), {"pumps"})

    def test_a_block_with_unknown_hardware_runs_alone(self) -> None:
        runner = _runner(
            [_node("start", "start", kind="basic"), _node("deepwell", "deepwell_handling"),
             _node("syringe", "dispense")],
            [_edge("start", "deepwell"), _edge("start", "syringe")],
        )
        _due(runner)
        self.assertEqual(_finish(runner, "start"), {"deepwell"})
        self.assertEqual(_finish(runner, "deepwell"), {"syringe"})

    def test_a_path_ends_at_a_join(self) -> None:
        # z1 -> z2 is one path, but z2 is also fed from elsewhere, so z1 is a
        # path of its own and the other Z path can run in between.
        runner = _runner(
            [_node("start", "start", kind="basic"), _node("z1", "move_z"), _node("z_other", "calibrate_z"),
             _node("z2", "move_z")],
            [_edge("start", "z1"), _edge("start", "z_other"), _edge("z1", "z2"), _edge("z_other", "z2")],
        )
        _due(runner)
        self.assertEqual(_finish(runner, "start"), {"z1"})
        self.assertEqual(_finish(runner, "z1"), {"z_other"})
        self.assertEqual(_finish(runner, "z_other"), {"z2"})

    def test_a_deactivated_block_on_a_path_does_not_hold_the_hardware(self) -> None:
        runner = _runner(
            [_node("start", "start", kind="basic"), _node("z1", "move_z"), _node("off", "move_z", active=False),
             _node("z2", "calibrate_z")],
            [_edge("start", "z1"), _edge("z1", "off"), _edge("start", "z2")],
        )
        _due(runner)
        self.assertEqual(_finish(runner, "start"), {"z1"})
        # The path's last block is deactivated and skipped: the path is over.
        self.assertEqual(_finish(runner, "z1"), {"z2"})

    def test_a_failure_stops_waiting_paths_too(self) -> None:
        runner = _runner(
            [_node("start", "start", kind="basic"), _node("z1", "move_z"), _node("z2", "calibrate_z")],
            [_edge("start", "z1"), _edge("start", "z2")],
        )
        _due(runner)
        _finish(runner, "start")
        self.assertEqual(_finish(runner, "z1", ok=False), set())
        self.assertTrue(runner.finished)
        self.assertFalse(runner.report.ok)

    def test_a_failure_on_a_separate_path_frees_the_hardware(self) -> None:
        runner = _runner(
            [_node("start", "start", kind="basic"), _node("z1", "move_z", failure_mode="separate_path"),
             _node("z1_next", "move_z"), _node("recover", "move_gantry_xy"), _node("z2", "calibrate_z")],
            [_edge("start", "z1"), _edge("z1", "z1_next"), _edge("z1", "recover", "error"), _edge("start", "z2")],
        )
        _due(runner)
        self.assertEqual(_finish(runner, "start"), {"z1"})
        # z1 has two ways out (next and error), so it is a path on its own.
        due = _finish(runner, "z1", ok=False)
        self.assertIn("recover", due)
        self.assertIn("z2", due)

    def test_waiting_is_reported_once(self) -> None:
        runner = _runner(
            [_node("start", "start", kind="basic"), _node("z1", "move_z"), _node("z2", "calibrate_z")],
            [_edge("start", "z1"), _edge("start", "z2")],
        )
        _due(runner)
        _finish(runner, "start")
        waiting = [event for event in runner.report.events if event.kind == "waiting"]
        self.assertEqual([event.node_id for event in waiting], ["z2"])


if __name__ == "__main__":
    unittest.main()
