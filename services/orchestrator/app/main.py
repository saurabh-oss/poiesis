from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import deployments, hitl, knowledge, runs, stream, uploads
from .config import pack, settings
from .db import init_db
from .graph import engine
from .kg.client import kg
from .workspace import deployment as runtime

log = logging.getLogger("poiesis")


async def _restart_deployments() -> None:
    """Bring generated apps back after a restart, in the background.

    Not awaited from lifespan: each redeploy runs `docker compose up --build
    --wait`, which can take minutes across several apps, and /health must
    answer immediately for the platform's own health check to pass.
    """
    try:
        restarted = await runtime.restart_running()
        if restarted:
            log.info("restarted %d deployment(s) after startup: %s",
                     len(restarted), ", ".join(restarted))
    except Exception:  # noqa: BLE001 — must never crash the process
        log.exception("could not restart deployments")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await kg().bootstrap()
    try:
        resumed = await engine.recover()
        if resumed:
            log.info("resumed %d run(s) after restart: %s", len(resumed), ", ".join(resumed))
    except Exception:  # noqa: BLE001 — recovery must never block startup
        log.exception("could not recover in-flight runs")
    task = asyncio.create_task(_restart_deployments())
    yield
    task.cancel()
    await engine.shutdown()
    kg().close()


app = FastAPI(title="Poiesis Orchestrator", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs.router)
app.include_router(uploads.router)
app.include_router(hitl.router)
app.include_router(knowledge.router)
app.include_router(stream.router)
app.include_router(deployments.router)


@app.get("/health")
async def health():
    s = settings()
    return {
        "status": "ok",
        "llm_profile": s.poiesis_llm_profile,
        "pack": pack().get("name", "unknown"),
    }
