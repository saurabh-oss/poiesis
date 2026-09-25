"""The kernel's own tables. Written by Poiesis, and read-only.

They live beside the application's tables on the same `Base`, are created at start-up
when missing, and are marked `__poiesis_platform__` so the generic data API does not
serve them: users, the audit trail, approvals, SLA clocks, notifications and the
connector outbox each have their own endpoints with their own permissions.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def aware(value: dt.datetime | None) -> dt.datetime | None:
    """A stored time as UTC-aware: Postgres returns aware values, SQLite naive ones."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.timezone.utc)


class AppUser(Base):
    __tablename__ = "sys_user"
    __poiesis_platform__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(200), default="")
    title: Mapped[str] = mapped_column(String(120), default="")
    team: Mapped[str] = mapped_column(String(120), default="")
    roles: Mapped[str] = mapped_column(String(400), default="")        # comma-separated role keys
    persona: Mapped[bool] = mapped_column(Boolean, default=False)        # offered on the sign-in screen
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_sign_in: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def role_list(self) -> list[str]:
        return [r.strip() for r in (self.roles or "").split(",") if r.strip()]


class AuditEvent(Base):
    __tablename__ = "sys_audit"
    __poiesis_platform__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_name: Mapped[str] = mapped_column(String(160), default="")
    actor_kind: Mapped[str] = mapped_column(String(20), default="user")
    action: Mapped[str] = mapped_column(String(40), index=True)        # create|update|delete|transition|approval|rule|connector|sign_in|job
    entity: Mapped[str] = mapped_column(String(80), default="", index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    changes: Mapped[Any] = mapped_column(JSON, nullable=True)            # {"field": [before, after]}
    rule_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    request_id: Mapped[str] = mapped_column(String(40), default="")


class Approval(Base):
    __tablename__ = "sys_approval"
    __poiesis_platform__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    transition: Mapped[str] = mapped_column(String(80))
    from_state: Mapped[str] = mapped_column(String(80), default="")
    to_state: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    approver_role: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)   # pending|approved|rejected|withdrawn
    reason: Mapped[str] = mapped_column(Text, default="")
    requested_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by_name: Mapped[str] = mapped_column(String(160), default="")
    decided_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decided_by_name: Mapped[str] = mapped_column(String(160), default="")
    decision_note: Mapped[str] = mapped_column(Text, default="")
    requested_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowClock(Base):
    """How long a record has been in its state, against the state's SLA."""
    __tablename__ = "sys_sla_clock"
    __poiesis_platform__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    state: Mapped[str] = mapped_column(String(80))
    entered_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    left_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    breached_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notification(Base):
    __tablename__ = "sys_notification"
    __poiesis_platform__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(20), default="info")     # info|ok|warn|down
    link: Mapped[str] = mapped_column(String(300), default="")
    entity: Mapped[str] = mapped_column(String(80), default="")
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConnectorEvent(Base):
    __tablename__ = "sys_connector_event"
    __poiesis_platform__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connector: Mapped[str] = mapped_column(String(40), index=True)
    operation: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)        # pending|sent|failed|deferred|superseded
    request: Mapped[Any] = mapped_column(JSON, nullable=True)
    response: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remote_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    actor_name: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retry_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ConnectorObject(Base):
    """What a connector's sandbox holds: issues, incidents, mails and messages."""
    __tablename__ = "sys_connector_object"
    __poiesis_platform__ = True
    __table_args__ = (UniqueConstraint("connector", "key", name="uq_connector_object"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connector: Mapped[str] = mapped_column(String(40), index=True)
    key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    data: Mapped[Any] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


PLATFORM_MODELS = (AppUser, AuditEvent, Approval, WorkflowClock, Notification, ConnectorEvent, ConnectorObject)
PLATFORM_TABLES = frozenset(m.__tablename__ for m in PLATFORM_MODELS)
