"""Hold the scheduling state for in-flight runs.

The browser still executes blocks - it owns hardware resolution, firmware
flashing and the safety interlocks - but it no longer decides what runs next.
It opens a session with the workflow, is told which nodes are due, executes
them, reports back, and is told what that made ready. Every control-flow
decision happens in the engine, against tests.

Sessions live in memory: a run is tied to the browser tab driving it, and a
backend restart already interrupts the run itself, so there is nothing worth
persisting here. The journal (a durable record of what ran) is a separate
concern and is not this.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field

from app.engine.journal import RunJournal, prune_old_runs
from app.engine.plan import ExecutionPlan, PlanNode, compile_plan
from app.engine.scheduler import NodeOutcome, PlanRunner

# A session the browser walked away from (tab closed, machine slept) would
# otherwise sit in memory forever.
SESSION_IDLE_TIMEOUT_SECONDS = 6 * 60 * 60


@dataclass
class RunSession:
    run_id: str
    plan: ExecutionPlan
    runner: PlanRunner
    created_at: float = field(default_factory=time.time)
    touched_at: float = field(default_factory=time.time)
    # Contexts handed out with each due node, so the result can be matched to
    # the data the node actually received rather than to whatever the graph
    # looks like by the time it reports back.
    handed_out: dict[str, dict] = field(default_factory=dict)
    # How much of the event log the caller has already been told about, so each
    # step returns only what is new.
    reported_events: int = 0
    # Tracked separately from reported_events: the journal and the HTTP caller
    # consume the same log at different moments, and a loop decision recorded
    # only when the caller happens to ask is a loop decision easily lost.
    journaled_events: int = 0
    journal: RunJournal | None = None


def _resolve_loop_items(node: PlanNode, context: dict) -> list:
    """Find the list a `loop over` block should iterate.

    The block names a field on its upstream input; anything that is not a list
    is treated as a single item, which is friendlier than failing a run because
    one dispense returned an object instead of an array.
    """
    source = str(node.parameters.get("source_path") or node.parameters.get("items") or "").strip()
    data = context.get("$in") or {}

    if not source:
        for candidate in ("items", "results", "values"):
            if isinstance(data.get(candidate), list):
                return list(data[candidate])
        return []

    current = data
    for part in source.replace("$in.", "").split("."):
        if not part:
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return []

    if isinstance(current, list):
        return list(current)
    if current is None:
        return []
    return [current]


class RunSessionService:
    def __init__(self) -> None:
        self._sessions: dict[str, RunSession] = {}
        self._lock = threading.Lock()

    def _prune(self) -> None:
        cutoff = time.time() - SESSION_IDLE_TIMEOUT_SECONDS
        for run_id in [rid for rid, s in self._sessions.items() if s.touched_at < cutoff]:
            self._sessions.pop(run_id, None)

    def start(self, workflow: dict) -> tuple[RunSession, ExecutionPlan]:
        plan = compile_plan(workflow)
        runner = PlanRunner(plan, resolve_loop_items=_resolve_loop_items)
        run_id = uuid.uuid4().hex
        session = RunSession(run_id=run_id, plan=plan, runner=runner, journal=RunJournal(run_id))

        session.journal.write(
            "run_started",
            ok=plan.ok,
            node_count=len(plan.nodes),
            edge_count=len(plan.edges),
            start_node_ids=plan.start_node_ids,
            problems=[problem.as_dict() for problem in plan.problems],
            blocks={node_id: node.display_name for node_id, node in plan.nodes.items()},
        )

        with self._lock:
            self._prune()
            self._sessions[run_id] = session
        prune_old_runs()
        return session, plan

    def get(self, run_id: str) -> RunSession | None:
        with self._lock:
            session = self._sessions.get(run_id)
            if session is not None:
                session.touched_at = time.time()
            return session

    def end(self, run_id: str, reason: str | None = None) -> RunSession | None:
        with self._lock:
            session = self._sessions.pop(run_id, None)
        if session is None:
            return None

        if reason and not session.runner.finished:
            session.runner.stop(reason)

        self._journal_decisions(session)
        report = session.runner.report
        if session.journal is not None:
            session.journal.write(
                "run_finished",
                ok=report.ok,
                error=report.error,
                stopped_at=report.stopped_at,
                blocks_executed=len(report.executed),
            )
        return session

    def _journal_decisions(self, session: RunSession) -> None:
        """Record what the engine decided, whenever it may have decided it.

        Loop entry and exit happen inside advance(), not when a block reports
        back, so journalling only on submit() silently loses how many times a
        loop actually went round - usually the thing you most want to know.
        """
        if session.journal is None:
            return
        events = session.runner.report.events
        for event in events[session.journaled_events:]:
            payload = event.as_dict()
            session.journal.write("decision", decision=payload.pop("kind"), **payload)
        session.journaled_events = len(events)

    def due_payload(self, session: RunSession) -> list[dict]:
        """Advance the engine and describe what the caller must now execute."""
        due = session.runner.advance()
        self._journal_decisions(session)
        payload = []
        for item in due:
            session.handed_out[item.node.node_id] = item.context
            payload.append({
                "node_id": item.node.node_id,
                "block_id": item.node.block_id,
                "display_name": item.node.display_name,
                "input": item.context.get("$in") or {},
                "iteration": (item.context.get("$run") or {}).get("iteration", 0),
            })
            if session.journal is not None:
                session.journal.write(
                    "block_started",
                    node_id=item.node.node_id,
                    block_id=item.node.block_id,
                    display_name=item.node.display_name,
                    input=item.context.get("$in") or {},
                )
        return payload

    def submit(self, session: RunSession, node_id: str, outcome: NodeOutcome) -> None:
        context = session.handed_out.pop(node_id, None)
        session.runner.submit(node_id, outcome, context)

        if session.journal is None:
            return

        node = session.plan.nodes.get(node_id)
        session.journal.write(
            "block_finished",
            node_id=node_id,
            display_name=node.display_name if node else node_id,
            ok=outcome.ok,
            error=outcome.error,
            result=outcome.result,
        )
        # Which branch this result opened, or whether a loop went round again.
        self._journal_decisions(session)

    def new_events(self, session: RunSession) -> list[dict]:
        """What the engine settled by itself since the caller last asked.

        Loops and deactivated blocks are decided in here and never handed out
        for execution, so without this the caller would have no idea they
        happened - a loop block would sit unmarked while its body ran.
        """
        events = session.runner.report.events
        fresh = [event.as_dict() for event in events[session.reported_events:]]
        session.reported_events = len(events)
        return fresh


run_session_service = RunSessionService()
