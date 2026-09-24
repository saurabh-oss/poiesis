"""Code maps: every generated codebase drawn by ArchiLens (see workspace/codemap.py)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import Run, session
from ..workspace import codemap
from ..workspace.repo import workspace_path

router = APIRouter(tags=["codemap"])


def _brief(doc: dict | None) -> dict:
    if not doc:
        return {"analysed": False}
    return {"analysed": True, "generated_at": doc.get("generated_at"), "git_ref": doc.get("git_ref"),
            "engine": doc.get("engine"), "ai": doc.get("ai"), "stats": doc.get("stats"),
            "preview": (doc.get("views") or {}).get("topology", ""),
            "patterns": doc.get("patterns") or [], "flows": len(doc.get("flows") or [])}


@router.get("/api/codemaps")
async def list_codemaps(limit: int = 60):
    """Every run that has a codebase, with its map if one has been drawn."""
    with session() as s:
        runs = s.query(Run).order_by(Run.created_at.desc()).limit(limit).all()
        rows = [(r.id, r.title, r.status, r.created_at) for r in runs]
    out = []
    for run_id, title, status, created in rows:
        if not (workspace_path(run_id) / "docker-compose.yml").is_file():
            continue
        out.append({"run_id": run_id, "title": title or run_id, "status": status, "created_at": created,
                    **_brief(codemap.load(run_id)), "job": codemap.status(run_id)})
    return {"available": codemap.available(), "codebases": out}


@router.get("/api/runs/{run_id}/codemap")
async def get_codemap(run_id: str):
    doc = codemap.load(run_id)
    body = {k: v for k, v in (doc or {}).items() if k != "snapshot"}
    return {"run_id": run_id, "available": codemap.available(), "job": codemap.status(run_id),
            "map": body or None}


@router.get("/api/runs/{run_id}/codemap/snapshot")
async def get_snapshot(run_id: str):
    """The raw ArchiLens snapshot (nodes, edges, flows), for other tools."""
    doc = codemap.load(run_id)
    if not doc:
        raise HTTPException(404, "no code map yet")
    return doc.get("snapshot") or {}


@router.post("/api/runs/{run_id}/codemap", status_code=202)
async def draw_codemap(run_id: str, ai: bool = True):
    """(Re)draw the map. `ai=true` also asks the local model for summaries, flows and patterns."""
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
    if not (workspace_path(run_id) / "docker-compose.yml").is_file():
        raise HTTPException(409, "this run has no codebase yet")
    if not codemap.available():
        raise HTTPException(503, "ArchiLens is not installed in the orchestrator image")
    codemap.schedule(run_id, ai=ai)
    return {"status": "drawing", "ai": ai}
