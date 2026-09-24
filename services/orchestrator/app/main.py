from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import llm, telemetry
from .api import codemap, deployments, hitl, knowledge, observability, plane, runs, stream, uploads
from .config import pack, settings
from .db import init_db
from .graph import engine
from .integrations import gitremote, tracker
from .kg import vectors
from .kg.client import kg
from .workspace import deployment as runtime

telemetry.configure_logging()
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
    try:
        await kg().bootstrap()
    except Exception:  # noqa: BLE001 — the graph being down must not stop the API
        log.exception("knowledge graph unavailable at startup; runs will design without it")
    try:
        resumed = await engine.recover()
        if resumed:
            log.info("resumed %d run(s) after restart: %s", len(resumed), ", ".join(resumed))
    except Exception:  # noqa: BLE001 — recovery must never block startup
        log.exception("could not recover in-flight runs")
    task = None
    if settings().poiesis_restart_deployments_on_boot:
        task = asyncio.create_task(_restart_deployments())
    yield
    if task:
        task.cancel()
    await engine.shutdown()
    kg().close()


app = FastAPI(title="Poiesis Orchestrator", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _timing(request: Request, call_next):
    """Server-Timing on every response, and a log line for slow or failed ones."""
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    response.headers["Server-Timing"] = f"app;dur={ms:.0f}"
    if response.status_code >= 500 or ms > 5000:
        log.warning("%s %s -> %d in %.0fms", request.method, request.url.path,
                    response.status_code, ms)
    return response


app.include_router(runs.router)
app.include_router(uploads.router)
app.include_router(hitl.router)
app.include_router(knowledge.router)
app.include_router(stream.router)
app.include_router(deployments.router)
app.include_router(observability.router)
app.include_router(codemap.router)
app.include_router(plane.router)


@app.get("/health")
async def health():
    """Shallow: is the process up. Used by the compose healthcheck and the UI badge."""
    s = settings()
    return {
        "status": "ok",
        "version": app.version,
        "llm_profile": s.poiesis_llm_profile,
        "pack": pack().get("name", "unknown"),
        "engine": engine.stats(),
    }


async def _check(name: str, fn) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        detail = await asyncio.wait_for(fn(), timeout=15)
        return {"name": name, "ok": True, "ms": int((time.perf_counter() - t0) * 1000),
                "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "ok": False, "ms": int((time.perf_counter() - t0) * 1000),
                "detail": f"{type(exc).__name__}: {exc}"[:300]}


@app.get("/health/deep")
async def health_deep():
    """Every dependency, probed. The readiness check an operator actually wants."""
    from .db import session
    from .events import redis

    async def _db():
        def q():
            with session() as s:
                s.execute(__import__("sqlalchemy").text("select 1"))
        await asyncio.to_thread(q)
        return "select 1"

    async def _redis():
        return "PONG" if await redis().ping() else "no pong"

    async def _neo4j():
        rows = await kg().run("MATCH (n) RETURN count(n) AS n")
        return f"{rows[0]['n']} nodes" if rows else "empty"

    async def _models():
        h = await llm.health()
        if not h.get("ok"):
            raise RuntimeError("missing " + ", ".join(h.get("missing") or []) if h.get("reachable")
                               else "Ollama unreachable")
        return f"{h['profile']}: " + ", ".join(sorted({llm.local_name(m) for m in h['models'].values()}))

    async def _docker():
        proc = await asyncio.create_subprocess_exec(
            "docker", "version", "--format", "{{.Server.Version}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(out.decode(errors="replace")[-200:])
        return "daemon " + out.decode().strip()

    async def _vectors():
        c = await vectors.counts()
        if not c and settings().poiesis_vectors:
            raise RuntimeError("Qdrant unreachable or empty")
        return ", ".join(f"{k}={v}" for k, v in c.items()) or "disabled"

    checks = await asyncio.gather(
        _check("postgres", _db), _check("redis", _redis), _check("neo4j", _neo4j),
        _check("models", _models), _check("docker", _docker), _check("qdrant", _vectors),
    )
    required = {"postgres", "redis", "docker", "models"}
    ok = all(c["ok"] for c in checks if c["name"] in required)
    return {
        "status": "ok" if ok else "degraded",
        "checks": checks,
        "integrations": {"jira": tracker.configured(), "git": gitremote.configured(),
                         "otlp": bool(settings().otel_exporter_otlp_endpoint)},
        "engine": engine.stats(),
    }
