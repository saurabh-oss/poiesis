"""Plane boards: every idea's project, its board, and mirroring past runs into it."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..db import Artifact, Run, session
from ..graph import engine
from ..integrations import plane

router = APIRouter(tags=["plane"])

_sync_all: asyncio.Task | None = None


def _runs_with_backlog() -> list[tuple[str, str, str, object]]:
    with session() as s:
        ids = {rid for (rid,) in s.query(Artifact.run_id).filter(Artifact.kind == "backlog").distinct()}
        runs = s.query(Run).filter(Run.id.in_(ids)).order_by(Run.created_at.desc()).all() if ids else []
        return [(r.id, r.title, r.status, r.created_at) for r in runs]


async def _counts(p: plane.Plane, pid: str) -> dict[str, int]:
    states = {st["id"]: st["group"] for st in await p.all(f"/projects/{pid}/states/")}
    out = {"backlog": 0, "unstarted": 0, "started": 0, "completed": 0, "cancelled": 0}
    for it in await p.all(f"/projects/{pid}/work-items/"):
        g = states.get(it.get("state"), "backlog")
        out[g] = out.get(g, 0) + 1
    return out


@router.get("/api/plane")
async def overview():
    """Every idea that has a backlog, with its Plane project and how far its stories are."""
    rows = _runs_with_backlog()
    out = []
    p = plane.Plane() if plane.configured() else None
    sem = asyncio.Semaphore(6)

    async def one(run_id, title, status, created):
        m = plane.mapping(run_id)
        counts = None
        if p and m["project"]:
            async with sem:
                try:
                    counts = await _counts(p, m["project"]["id"])
                except Exception:  # noqa: BLE001 — one unreachable project must not blank the page
                    counts = None
        return {"run_id": run_id, "title": title or run_id, "status": status, "created_at": created,
                "project": m["project"], "sprint": m["sprint"], "release": m["release"],
                "stories": len(m["stories"]), "epics": len(m["epics"]), "counts": counts}
    try:
        out = await asyncio.gather(*(one(*r) for r in rows))
    finally:
        if p:
            await p.close()
    return {"enabled": plane.configured(), "url": plane.settings().plane_url,
            "syncing": bool(_sync_all and not _sync_all.done()), "ideas": out}


@router.get("/api/runs/{run_id}/plane")
async def run_board(run_id: str):
    try:
        return await plane.board(run_id)
    except plane.PlaneError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/api/runs/{run_id}/plane/sync")
async def sync_run(run_id: str):
    """Mirror a past run into Plane (safe to repeat; no model calls)."""
    if not plane.configured():
        raise HTTPException(409, "Plane is not configured; run scripts/plane-bootstrap.py")
    if engine.is_busy(run_id):
        raise HTTPException(409, "The run is being built; it mirrors itself as it goes.")
    return await plane.backfill(run_id)


@router.post("/api/plane/sync", status_code=202)
async def sync_all():
    """Mirror every past run that has a backlog, one after another, in the background."""
    global _sync_all
    if not plane.configured():
        raise HTTPException(409, "Plane is not configured; run scripts/plane-bootstrap.py")
    if _sync_all is None or _sync_all.done():
        async def go():
            for run_id, *_ in _runs_with_backlog():
                if not engine.is_busy(run_id):
                    await plane.backfill(run_id)
        _sync_all = asyncio.create_task(go())
    return {"status": "syncing"}
