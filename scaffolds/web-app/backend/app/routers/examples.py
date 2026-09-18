"""Worked example — a reference, and read-only: edits to it are refused.

Copy this shape into a NEW file, backend/app/routers/<resource>.py, for your
story. Routers live one package down from the app, so siblings are imported with
two dots: `from ..db import get_session`. The platform mounts every router under
/api, so "/examples" is served at "/api/examples". Once any real router exists
this one is no longer mounted.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Example
from ..schemas import ExampleCreate, ExampleOut

router = APIRouter()


@router.post("/examples", response_model=ExampleOut, status_code=201)
def create_example(payload: ExampleCreate, db: Session = Depends(get_session)):
    # FastAPI has already validated `payload`: a missing or mistyped field never
    # reaches this line; the client gets a 422 instead.
    row = Example(label=payload.label)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row  # response_model serialises the ORM object; never return row.__dict__


@router.get("/examples", response_model=list[ExampleOut])
def list_examples(db: Session = Depends(get_session)):
    return db.query(Example).order_by(Example.id).all()
