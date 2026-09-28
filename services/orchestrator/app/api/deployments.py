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


def _bring_up_to_date(run_id: str) -> list[str]:
    """The platform's own files in an application already built (the shell, the kernel, a
    department library, their screens), as they stand in the platform now."""
    from ..graph.nodes.scaffold import refresh_platform_files
    from ..workspace import guide, repo
    with session() as s:
        run = s.get(Run, run_id)
        title = run.title if run is not None else ""
    state = {"run_id": run_id, "title": title, "vision": guide._latest(run_id, "vision"),
             "architecture": guide._latest(run_id, "architecture")}
    changed = refresh_platform_files(run_id, state)
    if changed:
        repo.commit(run_id, "chore(platform): the platform's own files brought up to date")
    return changed


async def _deploy_and_announce(run_id: str, fresh: bool = False, refresh: bool = False) -> None:
    await emit(run_id, "Starting the application on request"
                       + (" with a fresh database (init.sql runs again)" if fresh else ""),
               agent="release", stage="deploy")
    if refresh:
        changed = await asyncio.to_thread(_bring_up_to_date, run_id)
        await emit(run_id, ("The platform's own files brought up to date: " + ", ".join(changed[:12])
                            + (f" and {len(changed) - 12} more" if len(changed) > 12 else ""))
                   if changed else "The platform's own files were already up to date",
                   agent="scaffold", stage="deploy", data={"files": changed})
    outcome = await runtime.deploy(run_id, fresh=fresh)
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
async def deploy_run(run_id: str, fresh: bool = False, refresh: bool = False):
    """Start (or restart) the run's application. `fresh=true` drops its database volume
    first, so regenerated demonstration data in db/init.sql is what it opens with.
    `refresh=true` first brings the platform's own files in it up to date (the shell, the
    kernel, a department library), so an application built last month gets this month's fixes."""
    with session() as s:
        if s.get(Run, run_id) is None:
            raise HTTPException(404, "run not found")
    if engine.is_busy(run_id):
        raise HTTPException(409, "The run is still being built; it starts its "
                                 "application itself before the release decision.")
    job = _jobs.get(run_id)
    if job is None or job.done():
        _jobs[run_id] = asyncio.create_task(_deploy_and_announce(run_id, fresh, refresh))
    return {"status": "starting", "fresh": fresh, "refresh": refresh}


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
