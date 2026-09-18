"""The platform's own endpoints for {{project_name}}. Read-only.

Story endpoints do not go here. Each story adds backend/app/routers/<resource>.py
with its own `router`; see routers/examples.py for the shape to copy.
"""
from __future__ import annotations

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
