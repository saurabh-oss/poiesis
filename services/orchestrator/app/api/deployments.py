"""Running applications: what is up, where, and the controls to stop or start it."""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..db import Deployment, Run, session
from ..events import emit
from ..graph import engine
from ..graph.store import save_artifact
from ..workspace import browser_check, repo
from ..workspace import deployment as runtime

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_SHOT = re.compile(r"^[A-Za-z0-9_-]{1,80}\.png$")

router = APIRouter(tags=["deployments"])

# Manual deploys run in the background (a first build takes minutes). Held here
# so the task is not garbage-collected and a second click does not start another.
_jobs: dict[str, asyncio.Task] = {}


@router.get("/api/deployments")
async def list_deployments():
    await runtime.sync_statuses()
    with session() as s:
        rows = (
            s.query(Deployment, Run.title)
            .join(Run, Run.id == Deployment.run_id)
            .order_by(Deployment.updated_at.desc())
            .all()
        )
        return [runtime.as_row(d, title) for d, title in rows]


@router.get("/api/runs/{run_id}/deployment")
async def get_deployment(run_id: str):
    with session() as s:
        row = s.get(Deployment, run_id)
        return runtime.as_row(row) if row else None


async def _deploy_and_announce(run_id: str) -> None:
    await emit(run_id, "Starting the application on request", agent="release", stage="deploy")
    outcome = await runtime.deploy(run_id)
    if outcome.status == "running":
        await emit(run_id, f"Running at {outcome.url} — checking every screen in a browser",
                   agent="release", stage="deploy", data=outcome.as_dict())
        verification = await browser_check.verify(run_id)
        await save_artifact(run_id, "deployment", "deploy",
                            {**outcome.as_dict(), "run_id": run_id, "verification": verification})
        await emit(run_id, "Checked in a browser: every screen works" if verification.get("ok")
                   else "The browser check found problems — see the Deploy stage",
                   agent="release", stage="deploy",
                   level="info" if verification.get("ok") else "error",
                   data={"verification": verification})
    else:
        await emit(run_id, f"The application did not start: {outcome.detail[:400]}",
                   agent="release", stage="deploy", level="error", data=outcome.as_dict())


@router.post("/api/runs/{run_id}/deploy", status_code=202)
async def deploy_run(run_id: str):
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
    if engine.is_busy(run_id):
        raise HTTPException(409, "The run is still being built; it starts its "
                                 "application itself before the release decision.")
    job = _jobs.get(run_id)
    if job is None or job.done():
        _jobs[run_id] = asyncio.create_task(_deploy_and_announce(run_id))
    return {"status": "starting"}


@router.get("/api/runs/{run_id}/shots/{name}")
async def screenshot(run_id: str, name: str):
    """A screenshot the browser check took of one screen of the running app."""
    if not (_SAFE_ID.match(run_id) and _SAFE_SHOT.match(name)):
        raise HTTPException(404, "no such screenshot")
    path = repo.workspace_path(run_id) / ".poiesis" / "shots" / name
    if not path.is_file():
        raise HTTPException(404, "no such screenshot")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})


@router.post("/api/runs/{run_id}/deployment/stop")
async def stop_run(run_id: str):
    outcome = await runtime.stop(run_id)
    await emit(
        run_id,
        "Application stopped; its data is kept" if outcome.status == "stopped"
        else f"Could not stop the application: {outcome.detail[:300]}",
        agent="release", stage="deploy",
        level="info" if outcome.status == "stopped" else "error",
    )
    return outcome.as_dict()
