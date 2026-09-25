"""{{project_name}} — the data service. Written by Poiesis, and read-only.

The standard topology every generated application runs:

    browser ──► gateway (nginx: the UI, and /api routing)
                  ├──► api   — this image, app.main: story endpoints + the generic data API
                  └──► data  — this image, app.data_main: the generic data API only
    api, data ──► db (Postgres, seeded from db/init.sql)

The data service contains no story code at all: only the models, the platform's
status route and routers/resources.py. When the api service is down or still
starting, the gateway sends /api to this one instead, so every screen that reads
tables keeps working and the application never shows a blank page because one
story's module broke.
"""
from __future__ import annotations

import os

os.environ.setdefault("POIESIS_SERVICE", "data")  # before the routers package loads: no story code here

import importlib  # noqa: E402
import importlib.util  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402

from . import models  # noqa: E402,F401 — registers every table on Base.metadata
from .routers.resources import router as data_router  # noqa: E402
from .routes import router as base_router  # noqa: E402

APP_NAME = os.getenv("APP_NAME", "{{project_name}}")

# The enterprise kernel, when this application has one: the same sign-in, permissions
# and audit as the api, so falling back to this service never bypasses them. No
# scheduler here: the api runs it.
kernel = importlib.import_module(f"{__package__}.kernel") if importlib.util.find_spec(f"{__package__}.kernel") else None


@asynccontextmanager
async def lifespan(_: FastAPI):
    if kernel is not None:
        kernel.startup("data")
    yield


app = FastAPI(title=f"{APP_NAME} data service", version="0.1.0", lifespan=lifespan)
if kernel is not None:
    kernel.install(app, "data")
app.include_router(base_router, prefix="/api")
app.include_router(data_router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": APP_NAME, "service": "data"}
