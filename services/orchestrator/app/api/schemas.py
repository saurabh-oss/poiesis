from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceIn(BaseModel):
    kind: Literal["text", "url"]
    value: str
    label: str = ""


class RunCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    sources: list[SourceIn] = []


class GateResolve(BaseModel):
    decision: str
    notes: str = ""
    answers: dict[str, str] = {}
    actor: str = "stakeholder"
    extra: dict[str, Any] = {}
