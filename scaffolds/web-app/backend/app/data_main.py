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

from fastapi import FastAPI  # noqa: E402

from . import models  # noqa: E402,F401 — registers every table on Base.metadata
from .routers.resources import router as data_router  # noqa: E402
from .routes import router as base_router  # noqa: E402

APP_NAME = os.getenv("APP_NAME", "{{project_name}}")

app = FastAPI(title=f"{APP_NAME} data service", version="0.1.0")
app.include_router(base_router, prefix="/api")
app.include_router(data_router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": APP_NAME, "service": "data"}
