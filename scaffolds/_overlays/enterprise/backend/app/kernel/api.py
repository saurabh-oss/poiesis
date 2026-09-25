"""The kernel's endpoints, all under /api/platform/. Written by Poiesis, and read-only.

    GET  /api/platform/profile                          what this app is: enterprise, auth, workflows, connectors
    GET  /api/platform/workflows                        every lifecycle: states, transitions, SLAs
    GET  /api/platform/workflows/{entity}/{id}          a record's state, what I may do next, its history
    POST /api/platform/workflows/{entity}/{id}/{name}   perform a transition   {"reason": "", "fields": {}}
    GET  /api/platform/approvals?status=pending&scope=mine|all
    POST /api/platform/approvals/{id}/approve | /reject {"note": ""}
    GET  /api/platform/notifications                    my inbox; POST …/{id}/read, …/read-all
    GET  /api/platform/audit?entity=&entity_id=&actor=&action=&q=&limit=
    GET  /api/platform/audit/stats
    GET  /api/platform/rules                            the rule catalogue, with test results
    GET  /api/platform/integrations                     connectors, modes, outbox counts
    GET  /api/platform/integrations/events?connector=&status=
    GET  /api/platform/integrations/{connector}/objects what a sandbox holds
    POST /api/platform/integrations/events/{id}/retry
    POST /api/platform/integrations/{connector}/test
    GET  /api/platform/users
"""
from __future__ import annotations

import datetime as dt
import os
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..db import get_session
from . import rules as rule_registry
from . import workflow as wf
from .context import current
from .models import AppUser, Approval, AuditEvent, ConnectorEvent, Notification, aware, utcnow
from .policy import can, ensure, policy

router = APIRouter(prefix="/platform")
DOMAIN_ERROR: dict[str, str] = {}


# --------------------------------------------------------------------------- profile

@router.get("/profile")
def profile() -> dict[str, Any]:
    from .. import connectors
    from .auth import auth_required, personas_enabled
    p = policy()
    return {
        "enterprise": True, "app": os.getenv("APP_NAME", ""), "auth": auth_required(), "personas": personas_enabled(),
        "check_persona": p.check_persona(), "roles": p.roles,
        "workflows": [w.name for w in wf.iter_workflows()], "rules": len(rule_registry.RULES),
        "connectors": {c["name"]: c["mode"] for c in connectors.catalogue()},
        "errors": {k: v for k, v in {"policy": p.error, **DOMAIN_ERROR}.items() if v},
    }


# --------------------------------------------------------------------------- workflows

@router.get("/workflows")
def workflows() -> list[dict[str, Any]]:
    return [w.describe() for w in wf.iter_workflows()]


def _record(db: Session, entity: str, item_id: int) -> tuple[wf.Workflow, Any]:
    flow = wf.for_entity(entity)
    ensure(f"{flow.entity}:read")
    obj = db.get(flow.model, item_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{flow.entity} {item_id} not found")
    return flow, obj


def _history(db: Session, entity: str, item_id: int, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.query(AuditEvent).filter(AuditEvent.entity == entity, AuditEvent.entity_id == item_id) \
        .order_by(AuditEvent.id.desc()).limit(limit).all()
    return [_audit_out(r) for r in rows]


@router.get("/workflows/{entity}/{item_id}")
def record_state(entity: str, item_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    flow, obj = _record(db, entity, item_id)
    state = getattr(obj, flow.field)
    pending = db.query(Approval).filter_by(entity=flow.entity, entity_id=item_id, status="pending").all()
    return {"workflow": flow.name, "entity": flow.entity, "id": item_id, "state": state,
            "state_label": flow.states.get(state, state), "final": state in flow.final,
            "available": wf.available(obj, db=db), "approvals": [_approval_out(a) for a in pending],
            "clocks": wf.clocks_for(db, flow.entity, item_id), "history": _history(db, flow.entity, item_id),
            "definition": flow.describe()}


class Move(BaseModel):
    reason: str = ""
    fields: dict[str, Any] = {}


@router.post("/workflows/{entity}/{item_id}/{name}")
def move(entity: str, item_id: int, name: str, payload: Move | None = None,
         db: Session = Depends(get_session)) -> dict[str, Any]:
    flow, obj = _record(db, entity, item_id)
    payload = payload or Move()
    return wf.transition(db, obj, name, reason=payload.reason, fields=payload.fields, workflow=flow.name)


# --------------------------------------------------------------------------- approvals

def _approval_out(a: Approval) -> dict[str, Any]:
    actor = current()
    mine = actor.has_role(a.approver_role) or actor.kind in ("system", "service")
    return {"id": a.id, "workflow": a.workflow, "entity": a.entity, "entity_id": a.entity_id, "transition": a.transition,
            "title": a.title, "from_state": a.from_state, "to_state": a.to_state, "approver_role": a.approver_role,
            "approver_label": policy().roles.get(a.approver_role, a.approver_role), "status": a.status,
            "reason": a.reason, "requested_by": a.requested_by_name, "requested_at": a.requested_at,
            "decided_by": a.decided_by_name, "decided_at": a.decided_at, "decision_note": a.decision_note,
            "due_at": a.due_at, "overdue": bool(a.status == "pending" and a.due_at and aware(a.due_at) < utcnow()),
            "can_decide": bool(a.status == "pending" and mine and a.requested_by_id != actor.id)}


@router.get("/approvals")
def approvals(status: str = "pending", scope: str = "mine", limit: int = 200,
              db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    actor = current()
    q = db.query(Approval)
    if status != "all":
        q = q.filter(Approval.status == status)
    if scope == "mine" and actor.kind == "user" and "admin" not in actor.roles:
        q = q.filter(or_(Approval.approver_role.in_(actor.roles), Approval.requested_by_id == actor.id))
    return [_approval_out(a) for a in q.order_by(Approval.id.desc()).limit(min(limit, 1000)).all()]


class Decision(BaseModel):
    note: str = ""


@router.post("/approvals/{approval_id}/approve")
def approve(approval_id: int, payload: Decision | None = None, db: Session = Depends(get_session)) -> dict[str, Any]:
    return wf.decide(db, approval_id, True, (payload or Decision()).note)


@router.post("/approvals/{approval_id}/reject")
def reject(approval_id: int, payload: Decision | None = None, db: Session = Depends(get_session)) -> dict[str, Any]:
    return wf.decide(db, approval_id, False, (payload or Decision()).note)


# --------------------------------------------------------------------------- notifications

@router.get("/notifications")
def notifications(limit: int = 50, db: Session = Depends(get_session)) -> dict[str, Any]:
    actor = current()
    if actor.id is None:
        return {"unread": 0, "items": []}
    q = db.query(Notification).filter(Notification.user_id == actor.id)
    unread = q.filter(Notification.read_at.is_(None)).count()
    items = q.order_by(Notification.id.desc()).limit(min(limit, 200)).all()
    return {"unread": unread, "items": [{"id": n.id, "at": n.at, "title": n.title, "body": n.body, "level": n.level,
                                         "link": n.link, "entity": n.entity, "entity_id": n.entity_id,
                                         "read": n.read_at is not None} for n in items]}


@router.post("/notifications/{notification_id}/read")
def read_one(notification_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != current().id:
        raise HTTPException(status_code=404, detail="no such notification")
    n.read_at = n.read_at or utcnow()
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(db: Session = Depends(get_session)) -> dict[str, Any]:
    actor = current()
    count = db.query(Notification).filter(Notification.user_id == actor.id, Notification.read_at.is_(None)) \
        .update({Notification.read_at: utcnow()}, synchronize_session=False)
    db.commit()
    return {"ok": True, "marked": count}


# --------------------------------------------------------------------------- audit

def _audit_out(r: AuditEvent) -> dict[str, Any]:
    return {"id": r.id, "at": r.at, "actor": r.actor_name, "actor_kind": r.actor_kind, "action": r.action,
            "entity": r.entity, "entity_id": r.entity_id, "summary": r.summary, "changes": r.changes,
            "rule": r.rule_id}


@router.get("/audit")
def audit_trail(entity: str = "", entity_id: int | None = None, actor: str = "", action: str = "", q: str = "",
                since: str = "", limit: int = 500, db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """Everyone with audit:read sees the whole trail; anyone who may read a record sees its own history."""
    if not (entity and entity_id is not None and can(f"{entity}:read")):
        ensure("audit:read", what="read the audit trail")
    query = db.query(AuditEvent)
    if entity:
        query = query.filter(AuditEvent.entity == entity)
    if entity_id is not None:
        query = query.filter(AuditEvent.entity_id == entity_id)
    if actor:
        query = query.filter(AuditEvent.actor_name == actor)
    if action:
        query = query.filter(AuditEvent.action == action)
    if q:
        query = query.filter(AuditEvent.summary.ilike(f"%{q}%"))
    if since:
        try:
            query = query.filter(AuditEvent.at >= dt.datetime.fromisoformat(since.replace("Z", "+00:00")))
        except ValueError:
            raise HTTPException(status_code=422, detail="since must be an ISO date or time") from None
    return [_audit_out(r) for r in query.order_by(AuditEvent.id.desc()).limit(min(limit, 5000)).all()]


@router.get("/audit/stats")
def audit_stats(days: int = 30, db: Session = Depends(get_session)) -> dict[str, Any]:
    ensure("audit:read", what="read the audit trail")
    since = utcnow() - dt.timedelta(days=days)
    rows = db.query(AuditEvent.at, AuditEvent.action, AuditEvent.actor_name, AuditEvent.entity) \
        .filter(AuditEvent.at >= since).all()
    per_day: Counter = Counter()
    for at, _, _, _ in rows:
        per_day[(at if isinstance(at, dt.datetime) else dt.datetime.fromisoformat(str(at))).date().isoformat()] += 1
    # Every day of the window, quiet ones included, so the chart reads as a timeline.
    today = utcnow().date()
    window = [(today - dt.timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    return {"total": db.query(func.count(AuditEvent.id)).scalar() or 0, "window_days": days,
            "per_day": [{"date": d, "value": per_day.get(d, 0)} for d in window],
            "by_action": Counter(r[1] for r in rows).most_common(),
            "by_actor": Counter(r[2] for r in rows).most_common(8),
            "by_entity": Counter(r[3] for r in rows if r[3]).most_common(8)}


# --------------------------------------------------------------------------- rules

@router.get("/rules")
def rule_catalogue() -> dict[str, Any]:
    results = rule_registry.results()
    return {"rules": rule_registry.catalogue(), "workflows": [w.describe() for w in wf.iter_workflows()],
            "tests": {"total": results.get("total", 0), "passed": results.get("passed", 0),
                      "failed": results.get("failed", 0), "ran_at": results.get("ran_at")},
            "roles": policy().roles, "permissions": policy().permissions}


# --------------------------------------------------------------------------- integrations

def _event_out(e: ConnectorEvent) -> dict[str, Any]:
    return {"id": e.id, "connector": e.connector, "operation": e.operation, "mode": e.mode, "status": e.status,
            "request": e.request, "response": e.response, "error": e.error, "attempts": e.attempts,
            "remote_key": e.remote_key, "url": e.url, "ref": e.ref, "actor": e.actor_name,
            "created_at": e.created_at, "sent_at": e.sent_at, "retry_at": e.retry_at, "superseded_by": e.superseded_by}


@router.get("/integrations")
def integrations(db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    ensure("integrations:read", what="see the integrations")
    from .. import connectors
    counts = Counter()
    last: dict[str, Any] = {}
    for name, status, created in db.query(ConnectorEvent.connector, ConnectorEvent.status, ConnectorEvent.created_at).all():
        counts[(name, status)] += 1
        last[name] = max(last.get(name) or created, created)
    out = []
    for c in connectors.catalogue():
        n = c["name"]
        out.append({**c, "counts": {s: counts[(n, s)] for s in ("sent", "failed", "deferred", "pending", "superseded")},
                    "last_at": last.get(n)})
    return out


@router.get("/integrations/events")
def integration_events(connector: str = "", status: str = "", limit: int = 300,
                       db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    ensure("integrations:read", what="see the integrations")
    q = db.query(ConnectorEvent)
    if connector:
        q = q.filter(ConnectorEvent.connector == connector)
    if status:
        q = q.filter(ConnectorEvent.status == status)
    return [_event_out(e) for e in q.order_by(ConnectorEvent.id.desc()).limit(min(limit, 2000)).all()]


@router.get("/integrations/{connector}/objects")
def integration_objects(connector: str) -> list[dict[str, Any]]:
    ensure("integrations:read", what="see the integrations")
    from .. import connectors
    return list(reversed(connectors.store().objects(connector)))


@router.post("/integrations/events/{event_id}/retry")
def retry_event(event_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    ensure("integrations:manage", what="retry a connector call")
    from .jobs import replay_event
    e = db.get(ConnectorEvent, event_id)
    if e is None:
        raise HTTPException(status_code=404, detail="no such event")
    if e.status not in ("failed", "deferred"):
        raise HTTPException(status_code=409, detail=f"event {event_id} is {e.status}; only failed or deferred calls are retried")
    return replay_event(db, e)


@router.post("/integrations/{connector}/test")
def test_connector(connector: str) -> dict[str, Any]:
    ensure("integrations:manage", what="test a connector")
    from .. import connectors
    actor = current()
    name = os.getenv("APP_NAME", "the application")
    c = connectors.get(connector)
    if connector == "email":
        r = c.send(actor.email or "test@example.com", f"Test from {name}", f"{actor.name} sent this test from {name}.")
    elif connector in ("slack", "teams"):
        r = c.post(f"Test from {name}", f"{actor.name} sent this test.", facts={"Mode": c.mode})
    elif connector == "jira":
        r = c.create_issue(f"Connection test from {name}", f"Created by {actor.name}; safe to delete.")
    elif connector == "servicenow":
        r = c.create_incident(f"Connection test from {name}", f"Raised by {actor.name}; safe to close.", urgency=3, impact=3)
    elif connector == "plane":
        r = c.create_work_item(f"Connection test from {name}", f"Created by {actor.name}; safe to delete.")
    else:
        raise HTTPException(status_code=404, detail=f"no connector {connector}")
    return r.as_dict()


# --------------------------------------------------------------------------- people

@router.get("/users")
def users(db: Session = Depends(get_session)) -> list[dict[str, Any]]:
    ensure("users:read", what="see people and their roles")
    labels = policy().roles
    return [{"id": u.id, "username": u.username, "full_name": u.full_name, "title": u.title, "team": u.team,
             "email": u.email, "roles": u.role_list(), "role_labels": [labels.get(r, r) for r in u.role_list()],
             "active": u.active, "persona": u.persona, "last_sign_in": u.last_sign_in}
            for u in db.query(AppUser).order_by(AppUser.full_name).all()]
