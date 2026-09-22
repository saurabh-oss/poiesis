from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import pack
from ..db import Artifact, Deployment, Event, Evidence, Run, session
from ..graph import engine
from ..graph.graph import STAGE_DETAIL, STAGES
from ..ingest.pipeline import ingest_sources
from ..integrations import gitremote, tracker
from ..workspace import deployment as runtime
from ..workspace import repo
from .schemas import RunCreate

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/stages")
async def stages():
    """The value stream, with who works each stage and whether it can stop to ask."""
    gates = pack().get("gates", {})
    out = []
    for key, label, description in STAGES:
        detail = STAGE_DETAIL.get(key, {})
        gate = detail.get("gate")
        out.append({
            "key": key, "label": label, "description": description,
            "agents": detail.get("agents", []), "produces": detail.get("produces", ""),
            "gate": gate, "asks": detail.get("asks", ""),
            "gate_mode": (gates.get(gate) or {}).get("mode", "require") if gate else None,
        })
    return out


@router.post("")
async def create_run(payload: RunCreate):
    """Create the run and ingest inline sources. Does not start the graph.

    File uploads arrive on a second request, and intake reads the evidence table
    the moment the graph starts — so starting here would race the upload and build
    a vision from a brief that is missing the stakeholder's documents. The client
    finishes intake, then calls /start.
    """
    with session() as s:
        run = Run(title=payload.title)
        s.add(run)
        s.commit()
        run_id = run.id

    await ingest_sources(run_id, [src.model_dump() for src in payload.sources])
    return {"id": run_id, "status": "queued"}


@router.post("/{run_id}/start")
async def start_run(run_id: str):
    # Claim the run inside the transaction that checks it. The graph is driven by a
    # background task, so leaving the status flip to the task lets a second /start
    # slip through and drive the same thread twice.
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run.status != "queued":
            raise HTTPException(409, f"run is already {run.status}")
        evidence = s.query(Evidence).filter(Evidence.run_id == run_id).count()
        if evidence == 0:
            raise HTTPException(422, "nothing was ingested; add a brief, a link or a file")
        run.status = "running"
        s.commit()
        title = run.title

    driving = await engine.start(run_id, title)
    return {"id": run_id, "status": "running" if driving else "scheduled",
            "evidence_count": evidence}


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Stop a run where it is. Everything already built is kept; Retry continues it."""
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        status = run.status
    outcome = await engine.cancel(run_id)
    if outcome == "idle":
        raise HTTPException(409, f"the run is not being driven (it is {status})")
    return {"id": run_id, "outcome": outcome}


@router.get("/{run_id}/git")
async def run_git(run_id: str):
    """Where this run's repository lives on the Git remote, with the pull request if any."""
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
    return gitremote.mapping(run_id)


@router.post("/{run_id}/retry")
async def retry_run(run_id: str):
    """Continue a failed run from its last checkpoint, keeping everything already done."""
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        if run.status not in ("failed", "cancelled"):
            raise HTTPException(409, f"run is {run.status}; only a failed or cancelled run can be retried")
    if not await engine.retry(run_id):
        raise HTTPException(409, "the run is already being driven")
    return {"id": run_id, "status": "running"}


@router.get("")
async def list_runs(limit: int = 50):
    with session() as s:
        runs = s.query(Run).order_by(Run.created_at.desc()).limit(limit).all()
        return [
            {"id": r.id, "title": r.title, "status": r.status, "stage": r.stage,
             "created_at": r.created_at, "summary": r.summary}
            for r in runs
        ]


@router.get("/{run_id}")
async def get_run(run_id: str):
    with session() as s:
        run = s.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        evidence = s.query(Evidence).filter(Evidence.run_id == run_id).count()
        artifacts = (
            s.query(Artifact).filter(Artifact.run_id == run_id)
            .order_by(Artifact.created_at).all()
        )
        return {
            "id": run.id, "title": run.title, "status": run.status, "stage": run.stage,
            "summary": run.summary, "created_at": run.created_at,
            "evidence_count": evidence,
            "artifacts": [
                {"id": a.id, "kind": a.kind, "stage": a.stage, "version": a.version,
                 "body": a.body, "created_at": a.created_at}
                for a in artifacts
            ],
            "files": repo.tree(run_id, limit=400),
            "deployment": (
                runtime.as_row(dep) if (dep := s.get(Deployment, run_id)) else None
            ),
        }


@router.get("/{run_id}/events")
async def run_events(run_id: str, limit: int = 1500):
    with session() as s:
        rows = (
            s.query(Event).filter(Event.run_id == run_id)
            .order_by(Event.at.desc()).limit(limit).all()
        )[::-1]  # the newest `limit` lines, oldest first; a long run used to show only its start
        return [
            {"id": e.id, "at": e.at, "level": e.level, "agent": e.agent,
             "stage": e.stage, "message": e.message, "data": e.data}
            for e in rows
        ]


@router.get("/{run_id}/evidence")
async def run_evidence(run_id: str):
    """Everything intake captured, as the fragments later artifacts cite by id."""
    with session() as s:
        rows = (
            s.query(Evidence).filter(Evidence.run_id == run_id)
            .order_by(Evidence.created_at.asc()).all()
        )
        return [
            {"id": e.id, "source_kind": e.source_kind, "source_ref": e.source_ref,
             "locator": e.locator, "content": e.content[:1500]}
            for e in rows
        ]


@router.get("/{run_id}/tracker")
async def run_tracker(run_id: str):
    """Where this run lives in Jira: initiative, epics, stories and sprint, with links."""
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
    return tracker.mapping(run_id)


@router.post("/{run_id}/tracker/sync")
async def sync_tracker(run_id: str):
    """Mirror a run into Jira after the fact. No model calls; safe to repeat."""
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
    if not tracker.configured():
        raise HTTPException(409, "Jira is not configured on this orchestrator")
    await tracker.backfill(run_id)
    return tracker.mapping(run_id)


@router.get("/{run_id}/file")
async def run_file(run_id: str, path: str):
    content = repo.read(run_id, path)
    if not content:
        raise HTTPException(404, "file not found or empty")
    return {"path": path, "content": content}
