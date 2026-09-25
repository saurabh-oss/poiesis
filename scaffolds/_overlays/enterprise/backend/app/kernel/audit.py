"""The audit trail. Written by Poiesis, and read-only.

Every insert, update and delete of an application table made through the ORM — by the
generic data API, a story's router or a scheduled job — is recorded with who made it,
when, and each changed field's value before and after. Nobody has to remember to call
anything: the listener sees the session flush.

Explicit events (a workflow transition, an approval, a rule's decision, a connector
call, a sign-in) are recorded with `record()`, and appear in the same trail.

The listener also enforces workflows: a status that a workflow governs may only change
through `workflow.transition()`. Any other write to it is refused at flush time, so no
router, however it was written, can move a record around its lifecycle's rules.
"""
from __future__ import annotations

import datetime as dt
import decimal
import enum
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .context import current, request_id
from .models import PLATFORM_TABLES, AuditEvent

_SKIP_FIELDS = {"password_hash"}
_PENDING = "poiesis_audit_pending"
_ALLOWED = "poiesis_transitions"


def _plain(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return value


def _entity(obj: Any) -> str:
    return getattr(obj, "__tablename__", type(obj).__name__.lower())


def _pk(obj: Any) -> int | None:
    identity = inspect(obj).identity
    if identity:
        value = identity[0]
        return value if isinstance(value, int) else None
    return getattr(obj, "id", None)


def _label(obj: Any) -> str:
    for key in ("name", "title", "subject", "full_name", "label", "number", "reference", "code"):
        value = getattr(obj, key, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return ""


def allow_transition(session: Session, obj: Any, field: str) -> None:
    """The workflow engine marks the one change it is about to make as permitted."""
    session.info.setdefault(_ALLOWED, set()).add((id(obj), field))


def _governed(obj: Any) -> dict[str, str]:
    from .workflow import governed_fields
    return governed_fields(type(obj))


def _guard(session: Session, flush_context: Any, instances: Any) -> None:
    """Before any SQL is sent: a governed status changes only through a transition, and a
    new record starts in its workflow's initial state."""
    from .rules import violation
    from .workflow import initial_state
    allowed = session.info.get(_ALLOWED, set())
    for obj in list(session.new):
        for field, workflow in _governed(obj).items():
            start = initial_state(type(obj), field)
            value = getattr(obj, field, None)
            if value in (None, ""):
                setattr(obj, field, start)
            elif value != start and (id(obj), field) not in allowed:
                raise violation("WF-00", (
                    f"a new {_entity(obj)} starts as '{start}' in the {workflow} workflow, not '{value}'"),
                    workflow=workflow, field=field)
    for obj in list(session.dirty):
        governed = _governed(obj)
        if not governed:
            continue
        state = inspect(obj)
        for field, workflow in governed.items():
            hist = state.attrs[field].load_history()
            changed = hist.has_changes() and (hist.deleted or [None])[0] != (hist.added or [None])[0]
            if changed and (id(obj), field) not in allowed:
                raise violation("WF-00", (
                    f"{_entity(obj)}.{field} is governed by the {workflow} workflow: move it with a transition "
                    f"(POST /api/platform/workflows/{_entity(obj)}/{_pk(obj)}/<transition>), not by writing it"),
                    workflow=workflow, field=field)


def _collect(session: Session, flush_context: Any) -> None:
    pending: list[dict[str, Any]] = session.info.setdefault(_PENDING, [])
    # A status moved by a transition is recorded by the transition itself, with its
    # name, reason and approver; the plain "Changed status" entry would only repeat it.
    moved = session.info.get(_ALLOWED, set())
    for obj in list(session.new):
        entity = _entity(obj)
        if entity in PLATFORM_TABLES:
            continue
        state = inspect(obj)
        values = {a.key: _plain(a.value) for a in state.attrs if a.key not in _SKIP_FIELDS and a.value is not None}
        pending.append({"action": "create", "obj": obj, "entity": entity, "changes": {k: [None, v] for k, v in values.items()}})
    for obj in list(session.dirty):
        entity = _entity(obj)
        if entity in PLATFORM_TABLES or not session.is_modified(obj, include_collections=False):
            continue
        changes: dict[str, list[Any]] = {}
        for attr in inspect(obj).attrs:
            if attr.key in _SKIP_FIELDS:
                continue
            hist = attr.load_history()
            if hist.has_changes():
                before = _plain(hist.deleted[0]) if hist.deleted else None
                after = _plain(hist.added[0]) if hist.added else None
                if before != after and (id(obj), attr.key) not in moved:
                    changes[attr.key] = [before, after]
        if changes:
            pending.append({"action": "update", "obj": obj, "entity": entity, "changes": changes})
    for obj in list(session.deleted):
        entity = _entity(obj)
        if entity in PLATFORM_TABLES:
            continue
        pending.append({"action": "delete", "obj": obj, "entity": entity, "id": _pk(obj), "label": _label(obj),
                        "changes": None})


def _write(session: Session, flush_context: Any) -> None:
    pending = session.info.pop(_PENDING, [])
    session.info.pop(_ALLOWED, None)
    if not pending:
        return
    actor = current()
    for p in pending:
        obj = p["obj"]
        entity_id = p.get("id") if p["action"] == "delete" else _pk(obj)
        label = p.get("label") or _label(obj)
        verb = {"create": "Created", "update": "Changed", "delete": "Deleted"}[p["action"]]
        fields = ", ".join(sorted((p["changes"] or {}).keys())[:6]) if p["action"] == "update" else ""
        summary = f"{verb} {p['entity']} {entity_id or ''}".strip() + (f" “{label}”" if label else "") \
            + (f": {fields}" if fields else "")
        session.add(AuditEvent(actor_id=actor.id, actor_name=actor.name, actor_kind=actor.kind, action=p["action"],
                               entity=p["entity"], entity_id=entity_id, summary=summary, changes=p["changes"],
                               request_id=request_id()))


def install() -> None:
    """Attach the listener to every ORM session. Idempotent."""
    if getattr(install, "_done", False):
        return
    event.listen(Session, "before_flush", _guard)
    event.listen(Session, "after_flush", _collect)
    event.listen(Session, "after_rollback", lambda session: (session.info.pop(_PENDING, None),
                                                             session.info.pop(_ALLOWED, None)))
    event.listen(Session, "after_flush_postexec", _write)
    install._done = True  # type: ignore[attr-defined]


def record(session: Session, action: str, summary: str, *, entity: str = "", entity_id: int | None = None,
           changes: dict[str, Any] | None = None, rule_id: str | None = None) -> AuditEvent:
    """An explicit entry: a transition, an approval, a rule's decision, a connector call."""
    actor = current()
    row = AuditEvent(actor_id=actor.id, actor_name=actor.name, actor_kind=actor.kind, action=action,
                     entity=entity, entity_id=entity_id, summary=summary[:2000], changes=changes,
                     rule_id=rule_id, request_id=request_id())
    session.add(row)
    return row
