"""Run a workflow through the engine, one step at a time.

The browser drives: it opens a run, executes whatever nodes it is handed,
reports each result, and is told what that made ready. Execution stays in the
browser because that is where hardware resolution, firmware flashing and the
safety interlocks already live; only the decisions move here.

`/plan` is separate and side-effect free, so the editor can show what is wrong
with a graph - a loop with no body, an unreachable block, a join that can never
complete - without running anything.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.engine.plan import compile_plan
from app.engine.scheduler import NodeOutcome
from app.services.run_sessions import run_session_service

router = APIRouter(prefix="/api/engine", tags=["engine"])


class WorkflowGraph(BaseModel):
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class NodeResultRequest(BaseModel):
    node_id: str
    ok: bool = True
    result: dict | None = None
    error: str | None = None


class EndRunRequest(BaseModel):
    reason: str | None = None


@router.post("/plan")
def plan_workflow(graph: WorkflowGraph) -> dict:
    """Validate a graph without running it."""
    plan = compile_plan(graph.model_dump())
    return plan.as_dict()


@router.post("/runs")
def start_run(graph: WorkflowGraph) -> dict:
    session, plan = run_session_service.start(graph.model_dump())

    if not plan.ok:
        run_session_service.end(session.run_id)
        return {
            "ok": False,
            "run_id": None,
            "problems": [problem.as_dict() for problem in plan.problems],
            "error": "; ".join(problem.message for problem in plan.errors),
            "due": [],
            "finished": True,
        }

    due = run_session_service.due_payload(session)
    return {
        "ok": True,
        "run_id": session.run_id,
        "problems": [problem.as_dict() for problem in plan.problems],
        "due": due,
        "finished": session.runner.finished,
        "report": session.runner.report.as_dict(),
    }


@router.post("/runs/{run_id}/results")
def submit_node_result(run_id: str, payload: NodeResultRequest) -> dict:
    session = run_session_service.get(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' is not in progress.")

    if payload.node_id not in session.plan.nodes:
        raise HTTPException(
            status_code=400,
            detail=f"Block '{payload.node_id}' is not part of the running workflow.",
        )

    run_session_service.submit(
        session,
        payload.node_id,
        NodeOutcome(ok=payload.ok, result=payload.result, error=payload.error),
    )

    due = run_session_service.due_payload(session)
    finished = session.runner.finished
    report = session.runner.report.as_dict()
    if finished:
        run_session_service.end(run_id)

    return {"ok": session.runner.report.ok, "due": due, "finished": finished, "report": report}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    session = run_session_service.get(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' is not in progress.")
    return {
        "run_id": run_id,
        "finished": session.runner.finished,
        "report": session.runner.report.as_dict(),
    }


@router.post("/runs/{run_id}/end")
def end_run(run_id: str, payload: EndRunRequest | None = None) -> dict:
    session = run_session_service.end(run_id, (payload.reason if payload else None) or "Run stopped.")
    if session is None:
        return {"ok": True, "run_id": run_id, "finished": True}
    return {"ok": session.runner.report.ok, "run_id": run_id, "finished": True,
            "report": session.runner.report.as_dict()}
