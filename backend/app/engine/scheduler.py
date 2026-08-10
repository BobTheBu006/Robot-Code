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


@dataclass
class ReadyNode:
    """A node the caller must execute, with the data it should receive."""

    node: PlanNode
    context: dict


class PlanRunner:
    """Scheduling state for one run, steppable from outside.

    Execution lives with the caller. `advance()` handles everything the engine
    can decide by itself - loops, deactivated blocks, which edges are dead -
    and hands back the nodes that actually need running; `submit()` takes each
    result and works out what that makes ready next.

    Splitting it this way is what lets the browser keep doing execution
    (hardware resolution, firmware flashing, the safety interlocks) while the
    decisions that were wrong - which branch, how many times, who waits for
    whom - are made here, against tests, in one place.
    """

    def __init__(
        self,
        plan: ExecutionPlan,
        *,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        resolve_loop_items: Callable[[PlanNode, dict], list] | None = None,
    ) -> None:
        self.plan = plan
        self.max_iterations = max_iterations
        self._resolve_loop_items = resolve_loop_items
        self.report = RunReport(ok=True)

        self._results: dict[str, dict | None] = {}
        self._loop_iteration: dict[str, int] = defaultdict(int)
        self._loop_items: dict[str, list] = {}
        self._outstanding: set[str] = set()
        self._steps = 0
        self._halted = False

        if not plan.ok:
            self.report.ok = False
            self.report.error = "; ".join(problem.message for problem in plan.errors)
            self._halted = True
            self._ready: list[str] = []
            self._queued: set[str] = set()
            self._edge_state: dict[str, str] = {}
            self._loop_scopes: dict[str, set[str]] = {}
            return

        # Every edge is one of three things, and the third is what makes a join
        # work: WAITING (its source has not decided yet), LIVE (it delivered),
        # or DEAD (its source ran and chose a different handle, so it never
        # will). A join waits only on WAITING edges, so an `if` that took the
        # true branch does not strand the node below it on the false branch.
        self._edge_state = {edge.edge_id: WAITING for edge in plan.edges}

        # Loop scopes are pure graph shape, so they are found once rather than
        # on every iteration of a loop that may run thousands of times.
        self._loop_scopes = {
            node_id: _loop_scope_edges(plan, node_id)
            for node_id, node in plan.nodes.items()
            if node.is_loop
        }

        self._ready = list(plan.start_node_ids)
        self._queued = set(self._ready)

    # ---- state the caller can read ----

    @property
    def finished(self) -> bool:
        return self._halted or (not self._ready and not self._outstanding)

    @property
    def results(self) -> dict[str, dict | None]:
        return dict(self._results)

    def context_for(self, node_id: str) -> dict:
        """The data a node should receive, from the edges that reached it."""
        merged: dict = {}
        for edge in self.plan.incoming.get(node_id, []):
            if self._edge_state.get(edge.edge_id) != LIVE:
                continue
            upstream = self._results.get(edge.source)
            if isinstance(upstream, dict):
                merged.update(upstream)
        return {
            "$in": merged,
            "$blocks": dict(self._results),
            "$run": {"iteration": self._loop_iteration.get(node_id, 0)},
            "$loop_items": self._loop_items.get(node_id, []),
        }

    # ---- edge bookkeeping ----

    def _barrier_edges(self, node_id: str) -> list:
        # A loop-back edge is not part of the barrier: the body it comes from
        # runs *after* the loop node, so waiting on it would deadlock.
        return [
            edge for edge in self.plan.incoming.get(node_id, [])
            if edge.edge_id not in self.plan.loop_back_edge_ids
        ]

    def _readiness(self, node_id: str) -> str:
        """'ready', 'waiting', or 'dead' for the node below an edge."""
        barrier = self._barrier_edges(node_id)
        if not barrier:
            return "ready"
        states = {self._edge_state[edge.edge_id] for edge in barrier}
        if WAITING in states:
            return "waiting"
        if LIVE in states:
            return "ready"
        return "dead"

    def _enqueue(self, node_id: str) -> None:
        if node_id not in self._queued and node_id not in self._outstanding:
            self._queued.add(node_id)
            self._ready.append(node_id)

    def _settle(self, edge, state: str) -> None:
        """Mark an edge LIVE or DEAD and let the consequences propagate.

        Killing an edge can orphan the node below it, which kills that node's
        own outgoing edges in turn - that cascade is how a join far downstream
        of an untaken branch learns it will never hear from that side.
        """
        pending = [(edge, state)]
        while pending:
            current, current_state = pending.pop(0)
            if self._edge_state[current.edge_id] == current_state:
                continue
            self._edge_state[current.edge_id] = current_state

            target = current.target
            if current.edge_id in self.plan.loop_back_edge_ids:
                # Re-entering a loop: the loop node decides what happens next.
                if current_state == LIVE:
                    self._enqueue(target)
                continue

            verdict = self._readiness(target)
            if verdict == "ready":
                self._enqueue(target)
            elif verdict == "dead":
                for downstream in self.plan.outgoing.get(target, []):
                    pending.append((downstream, DEAD))

    def _activate(self, node_id: str, handles: list[str]) -> None:
        for edge in self.plan.outgoing.get(node_id, []):
            self._settle(edge, LIVE if edge.handle in handles else DEAD)

    def _fail(self, node_id: str | None, message: str) -> None:
        self.report.ok = False
        self.report.error = message
        self.report.stopped_at = node_id
        self._halted = True
        self._ready.clear()
        self._queued.clear()
        self._outstanding.clear()

    # ---- stepping ----

    def advance(self) -> list[ReadyNode]:
        """Settle everything internal; return the nodes needing execution."""
        due: list[ReadyNode] = []
        while self._ready and not self._halted:
            self._steps += 1
            if self._steps > self.max_iterations:
                self._fail(
                    None,
                    f"Run exceeded {self.max_iterations} steps and was stopped. "
                    "A loop is probably not ending.",
                )
                return []

            node_id = self._ready.pop(0)
            self._queued.discard(node_id)
            node = self.plan.nodes[node_id]

            if not node.is_active:
                self.report.events.append(RunEvent("skipped", node_id, "block is deactivated"))
                self._results[node_id] = None
                self._activate(node_id, [DEFAULT_HANDLE])
                continue

            if node.is_loop:
                self._step_loop(node)
                continue

            self._outstanding.add(node_id)
            due.append(ReadyNode(node=node, context=self.context_for(node_id)))

        return due

    def _step_loop(self, node: PlanNode) -> None:
        """Decide whether a loop enters its body again or moves on."""
        node_id = node.node_id
        context = self.context_for(node_id)

        if node.block_id == "loop_over" and node_id not in self._loop_items:
            items = self._resolve_loop_items(node, context) if self._resolve_loop_items else []
            self._loop_items[node_id] = list(items)
            context = self.context_for(node_id)

        try:
            iterate, why = _should_iterate(node, self._loop_iteration[node_id], context)
        except ConditionError as exc:
            self._fail(node_id, str(exc))
            return

        self.report.events.append(
            RunEvent("loop", node_id, ("entering body: " if iterate else "finished: ") + why)
        )

        if iterate:
            self._loop_iteration[node_id] += 1
            items = self._loop_items.get(node_id, [])
            index = self._loop_iteration[node_id] - 1
            self._results[node_id] = {
                "status": "looping",
                "iteration": self._loop_iteration[node_id],
                "item": items[index] if node.block_id == "loop_over" and index < len(items) else None,
            }
            # Re-entering the body means its nodes must run again, so every
            # edge inside the body goes back to WAITING. Without this a body
            # node would still be marked as having received last iteration's
            # input and would never become ready again.
            for edge_id in self._loop_scopes[node_id]:
                self._edge_state[edge_id] = WAITING
            self._activate(node_id, [LOOP_BODY_HANDLE])
        else:
            self._results[node_id] = {"status": "completed", "iterations": self._loop_iteration[node_id]}
            # The body is finished for good; retire its edges so anything
            # downstream of both the loop and its body can still become ready
            # instead of waiting on an iteration that will not come.
            for edge_id in self._loop_scopes[node_id]:
                if self._edge_state[edge_id] == WAITING:
                    self._edge_state[edge_id] = DEAD
            self._activate(node_id, [LOOP_DONE_HANDLE])

    def submit(self, node_id: str, outcome: NodeOutcome, context: dict | None = None) -> None:
        """Record what executing a node produced, and open the paths it takes."""
        if self._halted:
            return

        node = self.plan.nodes[node_id]
        self._outstanding.discard(node_id)
        self._results[node_id] = outcome.result
        self.report.executed.append(node_id)

        if not outcome.ok and node.failure_mode != "separate_path":
            message = outcome.error or f"'{node.display_name}' failed."
            self.report.events.append(RunEvent("failed", node_id, message))
            self._fail(node_id, message)
            return

        try:
            handles, why = _handles_for_outcome(
                self.plan, node, outcome, context if context is not None else self.context_for(node_id)
            )
        except ConditionError as exc:
            self._fail(node_id, str(exc))
            return

        self.report.events.append(RunEvent("ran", node_id, why))
        self._activate(node_id, handles)

    def stop(self, reason: str = "Run stopped.") -> None:
        self._fail(None, reason)


def run_plan(
    plan: ExecutionPlan,
    run_node: NodeRunner,
    *,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    should_stop: Callable[[], bool] | None = None,
    resolve_loop_items: Callable[[PlanNode, dict], list] | None = None,
) -> RunReport:
    """Execute a compiled plan start to finish, in this thread.

    A thin driver over PlanRunner: it executes what the runner hands back and
    feeds the results in. Used by the tests and by any caller that wants the
    whole run in one call.
    """
    runner = PlanRunner(plan, max_iterations=max_iterations, resolve_loop_items=resolve_loop_items)

    while not runner.finished:
        if should_stop is not None and should_stop():
            runner.stop()
            break

        due = runner.advance()
        if not due:
            break

        for ready in due:
            if should_stop is not None and should_stop():
                runner.stop()
                break
            outcome = run_node(ready.node, ready.context)
            runner.submit(ready.node.node_id, outcome, ready.context)
            if runner.report.stopped_at is not None or not runner.report.ok:
                break

    runner.report.results = runner.results
    return runner.report


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
