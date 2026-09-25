"""{{project_name}} — API entrypoint.

Scaffolding, and read-only. Story endpoints live in backend/app/routers/, one
module per story, discovered by routers/__init__.py and mounted here under /api.
Do not move /health: the archetype's definition of deployable and the platform's
live verification both depend on it answering 200.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401 — registers every table on Base.metadata
from .db import Base, engine
from .routers import routers
from .routes import router as base_router

APP_NAME = os.getenv("APP_NAME", "{{project_name}}")
log = logging.getLogger(__name__)

# The enterprise kernel (sign-in, roles, audit, workflows, rules, connectors) exists
# only in applications built with the enterprise pack. Everything below that uses it
# is skipped when it is absent, so one main.py serves both.
kernel = importlib.import_module(f"{__package__}.kernel") if importlib.util.find_spec(f"{__package__}.kernel") else None


def _create_missing_tables(attempts: int = 10) -> None:
    """Create any table a model declares that init.sql does not.

    init.sql stays the source of truth, but a story that adds a model and forgets
    its CREATE TABLE would otherwise answer 500 on every request in the running
    app while passing every test (the tests build tables from the models).
    create_all only adds what is missing; it never alters an existing table.
    """
    for attempt in range(attempts):
        try:
            Base.metadata.create_all(engine())
            return
        except Exception as exc:  # noqa: BLE001 — the database may still be starting
            if attempt == attempts - 1:
                log.warning("could not create missing tables: %s", exc)
                return
            time.sleep(2)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Only when the server starts: the test client in conftest.py never enters the
    # lifespan, so tests never reach for the real database.
    _create_missing_tables()
    if kernel is not None:
        kernel.startup("api")
    yield
    if kernel is not None:
        kernel.shutdown()


app = FastAPI(title=APP_NAME, version="0.1.0", lifespan=lifespan)

# The frontend proxies /api to this service, so requests are same-origin in
# normal operation. CORS stays permissive for local tooling only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if kernel is not None:
    # First, so its /api/auth and /api/platform routes are matched before any story's.
    kernel.install(app, "api")

app.include_router(base_router, prefix="/api")
for story_router in routers:
    app.include_router(story_router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    """Liveness. Deliberately does not touch the database.

    A health endpoint that fails when the datastore is briefly unavailable turns
    a recoverable blip into a failed deployment. Readiness is a separate concern.
    """
    return {"status": "ok", "app": APP_NAME}
