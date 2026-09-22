from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import settings

engine = create_engine(settings().database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def uid() -> str:
    return uuid.uuid4().hex[:16]


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One pass of the value stream, from a stakeholder brief to a release verdict."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(32), default="queued")
    stage: Mapped[str] = mapped_column(String(48), default="intake")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Evidence(Base):
    """A single traceable stakeholder statement. Everything downstream cites these."""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    source_kind: Mapped[str] = mapped_column(String(24))  # text|file|url|audio|image
    source_ref: Mapped[str] = mapped_column(String(512))
    locator: Mapped[str] = mapped_column(String(120), default="")  # page 3, 00:04:12, para 7
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Artifact(Base):
    """A produced deliverable: vision, backlog, ADR, sprint, diff, test report, verdict."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    stage: Mapped[str] = mapped_column(String(48))
    version: Mapped[int] = mapped_column(default=1)
    body: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Gate(Base):
    """A typed human decision point. Open gates block the graph; closed ones are the audit trail."""

    __tablename__ = "gates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(48))
    stage: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(24), default="open")  # open|resolved|auto
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str] = mapped_column(String(120), default="")


class Event(Base):
    """Append-only narration of what agents did, for the live tape and post-hoc audit."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    level: Mapped[str] = mapped_column(String(16), default="info")
    agent: Mapped[str] = mapped_column(String(48), default="system")
    stage: Mapped[str] = mapped_column(String(48), default="")
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class NodeCache(Base):
    """Memoised output of a non-deterministic step, so a replay reuses it.

    LangGraph resumes an interrupt by re-executing the whole node from the top.
    Anything before the interrupt therefore runs twice — including model calls,
    which do not return the same answer twice. Without this the stakeholder
    approves the artifact they were shown and the graph proceeds with a second,
    unreviewed one generated during the replay.
    """

    __tablename__ = "node_cache"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Deployment(Base):
    """A generated application running at a URL. One row per run; redeploys update it.

    The row is the platform's claim about the app; `deployment.sync_statuses`
    reconciles it with what the Docker daemon is actually running.
    """

    __tablename__ = "deployments"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    project: Mapped[str] = mapped_column(String(120))
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str] = mapped_column(String(240), default="")
    status: Mapped[str] = mapped_column(String(24), default="starting")  # starting|running|failed|stopped
    detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )


class Span(Base):
    """One timed piece of work: a stage, a model call, a sandbox run, a deploy.

    The Postgres copy of what is also exported over OpenTelemetry when an
    exporter is configured. Stored so the control room can show a run's timeline
    without a tracing backend, and so a run's cost can be added up after the fact.
    """

    __tablename__ = "spans"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String(24), index=True)   # stage|llm|sandbox|deploy|browser|jira|git|kg|run
    name: Mapped[str] = mapped_column(String(200))
    stage: Mapped[str] = mapped_column(String(48), default="")
    step: Mapped[str] = mapped_column(String(160), default="")
    agent: Mapped[str] = mapped_column(String(48), default="")
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|error
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str] = mapped_column(String(32), default="")
    span_id: Mapped[str] = mapped_column(String(16), default="")


class LLMCall(Base):
    """Every model call the platform makes, with what went in and what came back.

    This is the LLM trace: prompt, reply, tokens, duration, which agent asked and
    for which memo step. It is what makes a bad artifact explainable — you can
    read exactly what the Developer was shown when it wrote the wrong file.
    """

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=True
    )
    stage: Mapped[str] = mapped_column(String(48), default="")
    step: Mapped[str] = mapped_column(String(160), default="")
    agent: Mapped[str] = mapped_column(String(48), default="")
    role: Mapped[str] = mapped_column(String(16))
    model: Mapped[str] = mapped_column(String(120))
    profile: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    finish_reason: Mapped[str] = mapped_column(String(24), default="")
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok|truncated|unparseable|error
    error: Mapped[str] = mapped_column(Text, default="")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    max_tokens: Mapped[int] = mapped_column(Integer, default=0)
    think: Mapped[bool] = mapped_column(Boolean, default=False)
    schema_used: Mapped[bool] = mapped_column(Boolean, default=False)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    response: Mapped[str] = mapped_column(Text, default="")
    thinking: Mapped[str] = mapped_column(Text, default="")
    span_id: Mapped[str] = mapped_column(String(16), default="")


def init_db() -> None:
    Base.metadata.create_all(engine)


def session() -> Session:
    return SessionLocal()
