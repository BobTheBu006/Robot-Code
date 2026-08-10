"""Compile a saved workflow graph into a validated ExecutionPlan.

Compile before moving. Everything that can be known about a workflow without
touching hardware is decided here - which node starts, which edges are control
branches, where the joins are, which loops are legitimate cycles and which are
mistakes - so a graph that cannot run says so before the first motor turns
rather than half way through.

The browser-side runner this replaces walked the graph as a plain DFS over the
edge array. That single choice produced most of the run defects at once: order
followed the order edges happened to be drawn, a node with two incoming
branches fired on the first one to arrive, `if` ran both branches because every
outgoing edge was followed, and error edges were taken during healthy runs.

Nothing here executes anything. The scheduler consumes the plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Handles that mean "this is a control decision", not "carry on".
BRANCH_HANDLES = {"true", "false"}
LOOP_BODY_HANDLE = "loop"
LOOP_DONE_HANDLE = "done"
ERROR_HANDLE = "error"
DEFAULT_HANDLE = "next"

LOOP_BLOCK_IDS = {"while", "for", "loop_over"}
BRANCH_BLOCK_IDS = {"if", "if_else"}
START_BLOCK_IDS = {"start"}


class PlanProblemLevel(str, Enum):
    ERROR = "error"
    """The workflow cannot run."""

    WARNING = "warning"
    """It can run, but something is probably not what the author meant."""


@dataclass(frozen=True)
class PlanProblem:
    level: PlanProblemLevel
    message: str
    node_id: str | None = None

    def as_dict(self) -> dict:
        return {"level": self.level.value, "message": self.message, "node_id": self.node_id}


@dataclass(frozen=True)
class PlanEdge:
    edge_id: str
    source: str
    target: str
    handle: str

    @property
    def is_error_path(self) -> bool:
        return self.handle == ERROR_HANDLE

    @property
    def is_loop_body(self) -> bool:
        return self.handle == LOOP_BODY_HANDLE


@dataclass(frozen=True)
class PlanNode:
    node_id: str
    block_id: str
    display_name: str
    kind: str
    is_active: bool
    failure_mode: str
    retry_count: int
    parameters: dict

    @property
    def is_loop(self) -> bool:
        return self.block_id in LOOP_BLOCK_IDS

    @property
    def is_branch(self) -> bool:
        return self.block_id in BRANCH_BLOCK_IDS

    @property
    def is_start(self) -> bool:
        return self.block_id in START_BLOCK_IDS

    @property
    def selects_one_branch(self) -> bool:
        """True when only the chosen outgoing handle may be activated."""
        return self.is_loop or self.is_branch


@dataclass
class ExecutionPlan:
    nodes: dict[str, PlanNode]
    edges: list[PlanEdge]
    start_node_ids: list[str]
    problems: list[PlanProblem] = field(default_factory=list)

    # node_id -> edges leaving / entering it
    outgoing: dict[str, list[PlanEdge]] = field(default_factory=dict)
    incoming: dict[str, list[PlanEdge]] = field(default_factory=dict)

    # Nodes reachable from a start, ignoring error edges: a healthy run's shape.
    reachable: set[str] = field(default_factory=set)

    # Nodes with more than one incoming non-error edge. These are real join
    # barriers: the old runner fired them as soon as any one branch arrived.
    join_node_ids: set[str] = field(default_factory=set)

    # Edges that legitimately close a cycle because they run a loop body.
    loop_back_edge_ids: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not any(problem.level is PlanProblemLevel.ERROR for problem in self.problems)

    @property
    def errors(self) -> list[PlanProblem]:
        return [p for p in self.problems if p.level is PlanProblemLevel.ERROR]

    @property
    def warnings(self) -> list[PlanProblem]:
        return [p for p in self.problems if p.level is PlanProblemLevel.WARNING]

    def outgoing_for_handle(self, node_id: str, handle: str) -> list[PlanEdge]:
        return [edge for edge in self.outgoing.get(node_id, []) if edge.handle == handle]

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "start_node_ids": list(self.start_node_ids),
            "join_node_ids": sorted(self.join_node_ids),
            "loop_back_edge_ids": sorted(self.loop_back_edge_ids),
            "unreachable_node_ids": sorted(set(self.nodes) - self.reachable),
            "problems": [problem.as_dict() for problem in self.problems],
        }


def _coerce_int(value, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def compile_plan(workflow: dict, start_node_ids: list[str] | None = None) -> ExecutionPlan:
    """Build and validate a plan from a saved workflow document.

    `start_node_ids` names the entry point explicitly. A compound block needs
    this: its inner graph is a fragment whose entry is recorded on the block,
    and guessing from the shape could start branches the compound never meant
    to begin on their own.
    """
    raw_nodes = workflow.get("nodes") or []
    raw_edges = workflow.get("edges") or []

    nodes: dict[str, PlanNode] = {}
    problems: list[PlanProblem] = []

    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        node_id = raw.get("id")
        data = raw.get("data") or {}
        block = data.get("block") or {}
        if not node_id or not block.get("id"):
            problems.append(PlanProblem(PlanProblemLevel.ERROR, "A node is missing its id or block.", node_id))
            continue
        if node_id in nodes:
            problems.append(PlanProblem(PlanProblemLevel.ERROR, f"Duplicate node id '{node_id}'.", node_id))
            continue

        settings = data.get("settings") or {}
        nodes[node_id] = PlanNode(
            node_id=node_id,
            block_id=block["id"],
            display_name=data.get("customName") or block.get("displayName") or block["id"],
            kind=block.get("kind") or "advanced",
            is_active=data.get("isActive") is not False,
            failure_mode="separate_path" if settings.get("failureMode") == "separate_path" else "stop_flow",
            retry_count=_coerce_int(settings.get("retryCount")),
            parameters=data.get("parameters") or {},
        )

    edges: list[PlanEdge] = []
    outgoing: dict[str, list[PlanEdge]] = {node_id: [] for node_id in nodes}
    incoming: dict[str, list[PlanEdge]] = {node_id: [] for node_id in nodes}

    for raw in raw_edges:
        if not isinstance(raw, dict):
            continue
        source = raw.get("source")
        target = raw.get("target")
        if source not in nodes or target not in nodes:
            # Contract 10: a dangling reference is reported, never silently
            # dropped, so a workflow that lost a block does not quietly change
            # meaning.
            problems.append(
                PlanProblem(
                    PlanProblemLevel.ERROR,
                    f"Edge '{raw.get('id')}' connects a node that is not in this workflow "
                    f"({source} -> {target}).",
                )
            )
            continue

        edge = PlanEdge(
            edge_id=raw.get("id") or f"{source}->{target}",
            source=source,
            target=target,
            handle=raw.get("sourceHandle") or DEFAULT_HANDLE,
        )
        edges.append(edge)
        outgoing[source].append(edge)
        incoming[target].append(edge)

    if start_node_ids:
        requested = [node_id for node_id in start_node_ids if node_id in nodes]
        for missing in [node_id for node_id in start_node_ids if node_id not in nodes]:
            problems.append(
                PlanProblem(
                    PlanProblemLevel.ERROR,
                    f"The starting block '{missing}' is not in this workflow.",
                    missing,
                )
            )
        start_node_ids = requested
    else:
        start_node_ids = _find_starts(nodes, incoming)

    if not start_node_ids:
        problems.append(
            PlanProblem(
                PlanProblemLevel.ERROR,
                "This workflow has no starting point: every block has an incoming connection, "
                "so there is nowhere to begin.",
            )
        )

    plan = ExecutionPlan(
        nodes=nodes,
        edges=edges,
        start_node_ids=start_node_ids,
        problems=problems,
        outgoing=outgoing,
        incoming=incoming,
    )

    _validate_branch_handles(plan)
    plan.loop_back_edge_ids = _find_loop_back_edges(plan)
    _reject_cycles_outside_loops(plan)
    plan.reachable = _reachable_from_starts(plan)
    _report_unreachable(plan)
    plan.join_node_ids = {
        node_id
        for node_id, entering in plan.incoming.items()
        if len([e for e in entering if not e.is_error_path and e.edge_id not in plan.loop_back_edge_ids]) > 1
    }
    _warn_on_dead_error_paths(plan)

    return plan


def _find_starts(nodes: dict[str, PlanNode], incoming: dict[str, list[PlanEdge]]) -> list[str]:
    """Explicit start blocks, else anything with nothing feeding it."""
    explicit = [node_id for node_id, node in nodes.items() if node.is_start]
    if explicit:
        return sorted(explicit)
    return sorted(node_id for node_id in nodes if not incoming.get(node_id))


def _validate_branch_handles(plan: ExecutionPlan) -> None:
    """A control block must be able to take every branch it offers."""
    for node_id, node in plan.nodes.items():
        handles = {edge.handle for edge in plan.outgoing.get(node_id, [])}
        if node.is_branch:
            missing = BRANCH_HANDLES - handles
            if missing and handles:
                plan.problems.append(
                    PlanProblem(
                        PlanProblemLevel.WARNING,
                        f"'{node.display_name}' has no {'/'.join(sorted(missing))} branch connected; "
                        "that outcome ends the flow.",
                        node_id,
                    )
                )
        if node.is_loop and LOOP_BODY_HANDLE not in handles and handles:
            plan.problems.append(
                PlanProblem(
                    PlanProblemLevel.ERROR,
                    f"'{node.display_name}' is a loop with nothing connected to its Loop output, "
                    "so its body would never run.",
                    node_id,
                )
            )


def _find_loop_back_edges(plan: ExecutionPlan) -> set[str]:
    """Edges that close a cycle back into a loop node via its body.

    A cycle is legitimate exactly when it re-enters a loop block: that is what
    a loop *is*. Any other cycle is a mistake and is rejected below.
    """
    loop_back: set[str] = set()
    for node_id, node in plan.nodes.items():
        if not node.is_loop:
            continue
        body = {edge.target for edge in plan.outgoing_for_handle(node_id, LOOP_BODY_HANDLE)}
        if not body:
            continue
        # Anything reachable from the body, without passing back through the
        # loop node, is inside the loop scope.
        scope: set[str] = set()
        stack = list(body)
        while stack:
            current = stack.pop()
            if current in scope or current == node_id:
                continue
            scope.add(current)
            for edge in plan.outgoing.get(current, []):
                stack.append(edge.target)
        for edge in plan.edges:
            if edge.target == node_id and edge.source in scope:
                loop_back.add(edge.edge_id)
    return loop_back


def _reject_cycles_outside_loops(plan: ExecutionPlan) -> None:
    """A cycle that is not a loop body means the run would never finish."""
    colour: dict[str, int] = {}  # 0 = visiting, 1 = done

    def visit(node_id: str, path: list[str]) -> None:
        colour[node_id] = 0
        for edge in plan.outgoing.get(node_id, []):
            if edge.edge_id in plan.loop_back_edge_ids:
                continue
            state = colour.get(edge.target)
            if state == 0:
                cycle = " -> ".join(
                    plan.nodes[n].display_name for n in path[path.index(edge.target):] + [edge.target]
                ) if edge.target in path else plan.nodes[edge.target].display_name
                plan.problems.append(
                    PlanProblem(
                        PlanProblemLevel.ERROR,
                        f"These blocks form a loop that is not a loop block, so the run would never "
                        f"finish: {cycle}. Use a While/For block to repeat work.",
                        edge.target,
                    )
                )
                continue
            if state is None:
                visit(edge.target, path + [edge.target])
        colour[node_id] = 1

    for node_id in plan.nodes:
        if colour.get(node_id) is None:
            visit(node_id, [node_id])


def _reachable_from_starts(plan: ExecutionPlan) -> set[str]:
    """What a healthy run can touch. Error edges are excluded on purpose: a
    block only reachable through a failure is not part of the normal path."""
    reachable: set[str] = set()
    stack = list(plan.start_node_ids)
    while stack:
        node_id = stack.pop()
        if node_id in reachable:
            continue
        reachable.add(node_id)
        for edge in plan.outgoing.get(node_id, []):
            if edge.is_error_path:
                continue
            stack.append(edge.target)
    return reachable


def _report_unreachable(plan: ExecutionPlan) -> None:
    for node_id, node in plan.nodes.items():
        if node_id in plan.reachable:
            continue
        # A node reached only by an error edge is intentional, not orphaned.
        if any(edge.is_error_path for edge in plan.incoming.get(node_id, [])):
            continue
        plan.problems.append(
            PlanProblem(
                PlanProblemLevel.WARNING,
                f"'{node.display_name}' is never reached from the start, so it will not run.",
                node_id,
            )
        )


def _warn_on_dead_error_paths(plan: ExecutionPlan) -> None:
    """An error edge from a block set to stop the whole flow can never fire."""
    for node_id, node in plan.nodes.items():
        if node.failure_mode == "separate_path":
            continue
        for edge in plan.outgoing.get(node_id, []):
            if edge.is_error_path:
                plan.problems.append(
                    PlanProblem(
                        PlanProblemLevel.WARNING,
                        f"'{node.display_name}' has an error path connected, but its failure mode is "
                        "Stop whole flow, so that path can never run. Set it to a separate path.",
                        node_id,
                    )
                )
