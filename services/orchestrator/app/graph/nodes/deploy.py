"""Stage: run the increment and open it in a real browser — before review.

This used to run after review and prove only that the backend answered /health.
A released app threw on load and showed the scaffold placeholder while every
check passed. Now each build round is deployed and every screen is opened in
headless Chromium on the app's own network. Review then judges what actually
works: broken screens become blocking findings attributed to their story, which
drive a rework round, and an app that is not proven working is not offered for
release at all.
"""
from __future__ import annotations

from ... import telemetry
from ...events import emit
from ...workspace import browser_check
from ...workspace import deployment as runtime
from ..state import RunState
from ..store import save_artifact, set_stage


async def deploy_increment(state: RunState) -> RunState:
    """Node name is `deploy`; the state key is `deployment`, so they do not collide."""
    run_id = state["run_id"]
    await set_stage(run_id, "deploy")
    await emit(run_id, "Starting the application: building its images and waiting for "
                       "every service to report healthy",
               agent="release", stage="deploy")

    # fresh=True: this is an automated deploy inside the build/review loop, not a
    # stakeholder restarting a released app, so a stale schema from an earlier
    # round in this same run must never survive to shadow the current one.
    async with telemetry.span("deploy", "compose up", fresh=True) as sp:
        outcome = await runtime.deploy(run_id, fresh=True)
        sp.set(status=outcome.status, port=outcome.port)
        if outcome.status == "failed":
            sp.fail(outcome.detail[:500])
    record = {**outcome.as_dict(), "run_id": run_id}

    if outcome.status == "running":
        await set_stage(run_id, "deploy", summary={"url": outcome.url})
        await emit(run_id, f"Running at {outcome.url} — now opening every screen in a real browser",
                   agent="release", stage="deploy", data=outcome.as_dict())
        if (state.get("scaffold") or {}).get("entrypoint") == "frontend":
            async with telemetry.span("browser", "open every screen") as sp:
                verification = await browser_check.verify(run_id)
                sp.set(ok=bool(verification.get("ok")),
                       screens=len(verification.get("screens") or []))
                if not verification.get("ok"):
                    sp.fail("; ".join(verification.get("problems") or [])[:500] or "screens failed")
        else:
            verification = {"ok": True, "skipped": True, "problems": [], "screens": []}
        record["verification"] = verification
        screens = [s for s in verification.get("screens", []) if not s.get("example")]
        if verification.get("ok"):
            await emit(run_id, f"Checked in a browser: {len(screens)} screen(s), all working",
                       agent="release", stage="deploy", data={"verification": verification})
        else:
            problems = list(verification.get("problems", [])) + [
                f"{s.get('title')}: {p}" for s in screens for p in s.get("problems", [])
            ]
            await emit(run_id, f"The browser check found {len(problems)} problem(s): "
                               + "; ".join(problems)[:600],
                       agent="release", stage="deploy", level="error",
                       data={"verification": verification})
    elif outcome.status == "not_applicable":
        await emit(run_id, outcome.detail, agent="release", stage="deploy", level="warn")
    else:
        await emit(run_id, f"The application did not start: {outcome.detail[:400]}",
                   agent="release", stage="deploy", level="error", data=outcome.as_dict())

    await save_artifact(run_id, "deployment", "deploy", record)
    return {"deployment": record}
