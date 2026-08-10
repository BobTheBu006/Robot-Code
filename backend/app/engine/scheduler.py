"""Walk an ExecutionPlan the way the graph says, not the way it was drawn.

This is the half of the engine that decides *what runs next*. The browser-side
runner it replaces did a depth-first walk over the edge array and executed
every node it touched, which is why:

- run order followed the order edges happened to be drawn (defect 3)
- a node fed by two branches fired on whichever arrived first (defect 4)
- `if` ran both branches, and loops ran their body once (defect 5)
- error edges were followed during healthy runs (defect 6)

Here a node becomes ready only when every incoming edge that was actually
*activated* has delivered, control blocks activate exactly one outgoing handle,
and a loop is a re-entrant scope with an iteration guard.

Execution itself is injected: the scheduler calls a `run_node` callable and
only interprets its result. That keeps this module pure and testable without
hardware, and keeps the hardware drivers untouched.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Protocol

from app.engine.conditions import ConditionError, evaluate_condition
from app.engine.plan import (
    DEFAULT_HANDLE,
    ERROR_HANDLE,
    LOOP_BODY_HANDLE,
    LOOP_DONE_HANDLE,
    ExecutionPlan,
    PlanNode,
)

# A loop that never stops would hold the machine forever. The guard is high
# enough not to interfere with real work and low enough to end a runaway.
DEFAULT_MAX_ITERATIONS = 10_000

# Edge states. See the comment in run_plan: DEAD is what lets a join proceed
# when one of the branches feeding it was never taken.
WAITING = "waiting"
LIVE = "live"
DEAD = "dead"


class NodeRunner(Protocol):
    def __call__(self, node: PlanNode, context: dict) -> "NodeOutcome": ...


@dataclass
class NodeOutcome:
    """What executing one node produced."""

    ok: bool = True
    result: dict | None = None
    error: str | None = None


@dataclass
class RunEvent:
    kind: str
    node_id: str | None = None
    detail: str = ""
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "node_id": self.node_id, "detail": self.detail, **({"data": self.data} if self.data else {})}


@dataclass
class RunReport:
    ok: bool
    executed: list[str] = field(default_factory=list)
    results: dict[str, dict | None] = field(default_factory=dict)
    events: list[RunEvent] = field(default_factory=list)
    error: str | None = None
    stopped_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "executed": list(self.executed),
            "results": dict(self.results),
            "events": [event.as_dict() for event in self.events],
            "error": self.error,
            "stopped_at": self.stopped_at,
        }


def _handles_for_outcome(plan: ExecutionPlan, node: PlanNode, outcome: NodeOutcome, context: dict) -> tuple[list[str], str]:
    """Which outgoing handles this node activates, and why.

    This is the whole of control flow: a node activates the handles named here
    and no others, so an `if` cannot run both branches.
    """
    if not outcome.ok:
        if node.failure_mode == "separate_path":
            return [ERROR_HANDLE], "failed; taking the error path"
        return [], "failed"

    if node.is_branch:
        decision = evaluate_condition(node.parameters.get("condition"), context)
        handle = "true" if decision.value else "false"
        return [handle], f"condition {decision.detail}"

    if node.is_loop:
        # Loop entry/exit is decided by _should_iterate; this function only
        # reports the default path for a non-control node.
        return [DEFAULT_HANDLE], "continue"

    return [DEFAULT_HANDLE], "continue"


def _should_iterate(node: PlanNode, iteration: int, context: dict) -> tuple[bool, str]:
    """Does this loop run its body again?"""
    if node.block_id == "for":
        try:
            total = int(float(node.parameters.get("iterations") or 0))
        except (TypeError, ValueError):
            total = 0
        return iteration < total, f"iteration {iteration + 1} of {total}"

    if node.block_id == "loop_over":
        items = context.get("$loop_items") or []
        return iteration < len(items), f"item {iteration + 1} of {len(items)}"

    # while
    decision = evaluate_condition(node.parameters.get("condition"), context)
    return decision.value, f"condition {decision.detail}"


def run_plan(
    plan: ExecutionPlan,
    run_node: NodeRunner,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    should_stop: Callable[[], bool] | None = None,
    resolve_loop_items: Callable[[PlanNode, dict], list] | None = None,
) -> RunReport:
    """Execute a compiled plan.

    `run_node` performs the actual work; everything here is scheduling. A node
    is ready when every activated incoming edge has delivered, which is what
    makes a fan-in a real join instead of a race.
    """
    report = RunReport(ok=True)
    if not plan.ok:
        report.ok = False
        report.error = "; ".join(problem.message for problem in plan.errors)
        return report

    results: dict[str, dict | None] = {}
    loop_iteration: dict[str, int] = defaultdict(int)
    loop_items: dict[str, list] = {}

    # Every edge is one of three things, and the third is what makes a join
    # work: WAITING (its source has not decided yet), LIVE (it delivered), or
    # DEAD (its source ran and chose a different handle, so it never will).
    # A join waits only on WAITING edges, so an `if` that took the true branch
    # does not strand the node below it forever on the false branch.
    edge_state: dict[str, str] = {edge.edge_id: WAITING for edge in plan.edges}

    # Loop scopes are pure graph shape, so they are found once rather than on
    # every iteration of a loop that may run thousands of times.
    loop_scopes: dict[str, set[str]] = {
        node_id: _loop_scope_edges(plan, node_id)
        for node_id, node in plan.nodes.items()
        if node.is_loop
    }

    ready: list[str] = list(plan.start_node_ids)
    queued: set[str] = set(ready)

    def barrier_edges(node_id: str) -> list:
        # A loop-back edge is not part of the barrier: the body it comes from
        # runs *after* the loop node, so waiting on it would deadlock.
        return [
            edge for edge in plan.incoming.get(node_id, [])
            if edge.edge_id not in plan.loop_back_edge_ids
        ]

    def context_for(node_id: str) -> dict:
        merged: dict = {}
        for edge in plan.incoming.get(node_id, []):
            if edge_state[edge.edge_id] != LIVE:
                continue
            upstream = results.get(edge.source)
            if isinstance(upstream, dict):
                merged.update(upstream)
        return {
            "$in": merged,
            "$blocks": dict(results),
            "$run": {"iteration": loop_iteration.get(node_id, 0)},
            "$loop_items": loop_items.get(node_id, []),
        }

    def enqueue(node_id: str) -> None:
        if node_id not in queued:
            queued.add(node_id)
            ready.append(node_id)

    def readiness(node_id: str) -> str:
        """'ready', 'waiting', or 'dead' for the node below an edge."""
        barrier = barrier_edges(node_id)
        if not barrier:
            return "ready"
        states = {edge_state[edge.edge_id] for edge in barrier}
        if WAITING in states:
            return "waiting"
        if LIVE in states:
            return "ready"
        return "dead"

    def settle(edge, state: str) -> None:
        """Mark an edge LIVE or DEAD and let the consequences propagate.

        Killing an edge can orphan the node below it, which kills that node's
        own outgoing edges in turn - that cascade is how a join far downstream
        of an untaken branch learns it will never hear from that side.
        """
        pending = [(edge, state)]
        while pending:
            current, current_state = pending.pop(0)
            if edge_state[current.edge_id] == current_state:
                continue
            edge_state[current.edge_id] = current_state

            target = current.target
            if current.edge_id in plan.loop_back_edge_ids:
                # Re-entering a loop: the loop node decides what happens next.
                if current_state == LIVE:
                    enqueue(target)
                continue

            verdict = readiness(target)
            if verdict == "ready":
                enqueue(target)
            elif verdict == "dead":
                for downstream in plan.outgoing.get(target, []):
                    pending.append((downstream, DEAD))

    def activate(node_id: str, handles: list[str]) -> None:
        for edge in plan.outgoing.get(node_id, []):
            settle(edge, LIVE if edge.handle in handles else DEAD)

    guard = 0
    while ready:
        if should_stop is not None and should_stop():
            report.ok = False
            report.error = "Run stopped."
            return report

        guard += 1
        if guard > max_iterations:
            report.ok = False
            report.error = (
                f"Run exceeded {max_iterations} steps and was stopped. A loop is probably not ending."
            )
            return report

        node_id = ready.pop(0)
        queued.discard(node_id)
        node = plan.nodes[node_id]

        if not node.is_active:
            report.events.append(RunEvent("skipped", node_id, "block is deactivated"))
            results[node_id] = None
            activate(node_id, [DEFAULT_HANDLE])
            continue

        context = context_for(node_id)

        # ---- loops are scopes, not one-shot nodes ----
        if node.is_loop:
            if node.block_id == "loop_over" and node_id not in loop_items:
                items = resolve_loop_items(node, context) if resolve_loop_items else []
                loop_items[node_id] = list(items)
                context = context_for(node_id)

            try:
                iterate, why = _should_iterate(node, loop_iteration[node_id], context)
            except ConditionError as exc:
                report.ok = False
                report.error = str(exc)
                report.stopped_at = node_id
                return report

            report.events.append(
                RunEvent("loop", node_id, ("entering body: " if iterate else "finished: ") + why)
            )
            if iterate:
                loop_iteration[node_id] += 1
                results[node_id] = {
                    "status": "looping",
                    "iteration": loop_iteration[node_id],
                    "item": (loop_items.get(node_id) or [None])[loop_iteration[node_id] - 1]
                    if node.block_id == "loop_over" and loop_iteration[node_id] <= len(loop_items.get(node_id, []))
                    else None,
                }
                # Re-entering the body means its nodes must run again, so every
                # edge inside the body goes back to WAITING. Without this a body
                # node would still be marked as having received last iteration's
                # input and would never become ready again.
                for edge_id in loop_scopes[node_id]:
                    edge_state[edge_id] = WAITING
                activate(node_id, [LOOP_BODY_HANDLE])
            else:
                results[node_id] = {"status": "completed", "iterations": loop_iteration[node_id]}
                # The body is finished for good; retire its edges so anything
                # downstream of both the loop and its body can still become
                # ready instead of waiting on an iteration that will not come.
                for edge_id in loop_scopes[node_id]:
                    if edge_state[edge_id] == WAITING:
                        edge_state[edge_id] = DEAD
                activate(node_id, [LOOP_DONE_HANDLE])
            continue

        # ---- ordinary and branch nodes ----
        outcome = run_node(node, context)
        results[node_id] = outcome.result
        report.executed.append(node_id)

        if not outcome.ok and node.failure_mode != "separate_path":
            report.ok = False
            report.error = outcome.error or f"'{node.display_name}' failed."
            report.stopped_at = node_id
            report.events.append(RunEvent("failed", node_id, report.error))
            return report

        try:
            handles, why = _handles_for_outcome(plan, node, outcome, context)
        except ConditionError as exc:
            report.ok = False
            report.error = str(exc)
            report.stopped_at = node_id
            return report

        report.events.append(RunEvent("ran", node_id, why))
        activate(node_id, handles)

    return report


def _loop_scope_edges(plan: ExecutionPlan, loop_node_id: str) -> set[str]:
    """Every edge that lives inside a loop's body.

    Walking forward from the body handle stops at the loop node itself, so the
    scope is the body and nothing after the `done` handle.
    """
    scope_nodes: set[str] = set()
    scope_edge_ids: set[str] = set()
    stack = []
    for edge in plan.outgoing_for_handle(loop_node_id, LOOP_BODY_HANDLE):
        scope_edge_ids.add(edge.edge_id)
        stack.append(edge.target)

    while stack:
        current = stack.pop()
        if current in scope_nodes or current == loop_node_id:
            continue
        scope_nodes.add(current)
        for edge in plan.outgoing.get(current, []):
            scope_edge_ids.add(edge.edge_id)
            stack.append(edge.target)

    return scope_edge_ids
