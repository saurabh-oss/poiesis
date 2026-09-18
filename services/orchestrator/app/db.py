from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine
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


def init_db() -> None:
    Base.metadata.create_all(engine)


def session() -> Session:
    return SessionLocal()
