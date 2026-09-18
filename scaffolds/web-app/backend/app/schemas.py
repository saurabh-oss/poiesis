"""Request and response shapes for {{project_name}}.

>>> THIS IS THE SLOT for API schemas. <<<

Every endpoint that accepts a body takes one of these, and every endpoint that
returns rows declares one as its response_model. That buys two things for free:
FastAPI rejects malformed input with a 422 before your code runs, and ORM objects
serialise correctly. Parsing `await request.json()` by hand gives a 500 on bad
input instead of a 422, and returning `row.__dict__` leaks SQLAlchemy internals
and fails to serialise.
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field


class ExampleCreate(BaseModel):
    """What a client sends. Every field is validated; a bad value is a 422."""

    label: str = Field(min_length=1, max_length=200)


class ExampleOut(BaseModel):
    """What the API returns. from_attributes lets it read an ORM object directly."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    created_at: dt.datetime
