"""The platform's own endpoints for {{project_name}}. Read-only.

Story endpoints do not go here. Each story adds backend/app/routers/<resource>.py
with its own `router`; see routers/examples.py for the shape to copy.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import get_session

router = APIRouter()


@router.get("/status")
def status(db: Session = Depends(get_session)) -> dict:
    """Readiness: proves the API reaches its datastore. The shell's banner calls it."""
    db.execute(text("SELECT 1"))
    return {"database": "connected"}


@router.get("/platform/profile")
def profile() -> dict:
    """What kind of application this is. The shell asks on load; an enterprise
    application's kernel answers this path first, with its sign-in and roles."""
    return {"enterprise": False, "app": os.getenv("APP_NAME", "{{project_name}}")}


@router.get("/platform/modules")
def modules() -> dict:
    """Which story modules loaded. A module that failed to import is left out of the
    API rather than taking it down; this is where that shows."""
    from .routers import broken

    return {"service": os.getenv("POIESIS_SERVICE", "api"), "broken": broken}
