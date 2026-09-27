"""Workflows: a record's lifecycle, enforced on the server. Written by Poiesis, and read-only.

The application declares each lifecycle once, in `domain/workflows.py`:

    from ..kernel.workflow import Transition, Workflow, register
    from ..models import PurchaseRequest
    from . import rules

    PURCHASE = register(Workflow(
        "purchase", PurchaseRequest, field="status",
        states={"draft": "Draft", "submitted": "Submitted", "approved": "Approved", "rejected": "Rejected", "ordered": "Ordered"},
        initial="draft",
        transitions=[
            Transition("submit", "draft", "submitted", roles=("requester",), guard=rules.complete_enough),
            Transition("approve", "submitted", "approved", roles=("manager",), approval="finance",
                       guard=rules.within_budget, rule="BR-03"),
            Transition("reject", "submitted", "rejected", roles=("manager", "finance"), requires_reason=True),
            Transition("order", "approved", "ordered", roles=("buyer",), fields=("po_number",)),
        ],
        sla={"submitted": 48},              # hours a record may sit in a state
        escalate={"submitted": "finance"},  # who hears about it when it sits longer
    ))

Then a transition is the only way the status moves:
    POST /api/platform/workflows/purchase_request/42/approve   {"reason": "…", "fields": {…}}
or, from a router or a job, `transition(db, row, "approve", reason="…")`.

What the engine enforces, in order: the record is in a state the transition leaves
from; the actor has one of its roles (or the permission `<entity>:<transition>`); the
reason is given when required; the guard — a domain rule — allows it. A transition with
`approval` does not take effect at once: it opens an approval for that role, and when
someone holding it (never the requester: four eyes) approves, it happens. Every step is
in the audit trail; entering a state with an SLA starts its clock, and the scheduler
escalates a clock that runs out.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any, Callable, Iterable

from sqlalchemy.orm import Session

from . import audit
from .context import Actor, current
from .models import Approval, WorkflowClock, utcnow
from .policy import can, policy
from .rules import RuleViolation, declare, violation

Guard = Callable[[Any, "Context"], Any]
Effect = Callable[[Session, Any, "Context"], Any]

declare("WF-00", "A governed status moves only through its workflow's transitions", kind="workflow",
        source="Platform")
declare("WF-01", "Only the roles a transition names may perform it", kind="authorisation", source="Platform")
declare("WF-02", "Nobody approves their own request (four eyes)", kind="authorisation", source="Platform")


@dataclass
class Transition:
    name: str
    source: str | tuple[str, ...]
    target: str
    label: str = ""
    roles: tuple[str, ...] = ()
    # The role that must approve before it takes effect: a role, or a callable
    # (record, ctx) -> role with a `roles` attribute listing every role it can name
    # (an approver chosen by amount, under a delegation of authority).
    approval: Any = None
    # The state the record waits in while the approval is pending ("submitted"); without
    # one it stays where it was until the approval is decided.
    pending: str | None = None
    requires_reason: bool = False
    guard: Guard | None = None            # a domain rule: raise RuleViolation (or return a message) to refuse
    rule: str | None = None               # the rule id this transition implements, for the catalogue
    fields: tuple[str, ...] = ()          # extra columns the transition may set (duplicate_of_id, po_number)
    effects: tuple[Effect, ...] = ()      # run after the state changes (notify, call a connector, …)
    notify: tuple[str, ...] = ()          # roles told when it happens
    on_reject: str | None = None          # with `approval`: the state a rejected request moves the record to
    tone: str = ""                        # ok | warn | down: how the button looks

    def sources(self) -> tuple[str, ...]:
        return (self.source,) if isinstance(self.source, str) else tuple(self.source)

    def leaves(self, state: str) -> bool:
        return "*" in self.sources() or state in self.sources()

    def approver(self, obj: Any = None, ctx: Any = None) -> str | None:
        """The role whose approval this move waits for, for this record."""
        if not self.approval:
            return None
        if callable(self.approval):
            return str(self.approval(obj, ctx)) if obj is not None else None
        return str(self.approval)

    def approvers(self) -> tuple[str, ...]:
        """Every role that may be asked to approve it."""
        if not self.approval:
            return ()
        if callable(self.approval):
            return tuple(getattr(self.approval, "roles", ()) or ())
        return (str(self.approval),)

    def approval_label(self) -> str | None:
        if not self.approval:
            return None
        return str(self.approval) if callable(self.approval) else self.approval


@dataclass
class Workflow:
    name: str
    model: type
    field: str = "status"
    states: dict[str, str] | list[str] = dc_field(default_factory=dict)
    initial: str = ""
    transitions: list[Transition] = dc_field(default_factory=list)
    sla: dict[str, float] = dc_field(default_factory=dict)          # state -> hours
    escalate: dict[str, str] = dc_field(default_factory=dict)       # state -> role to notify on breach
    final: tuple[str, ...] = ()
    title: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.states, list):
            self.states = {s: s.replace("_", " ").title() for s in self.states}
        self.initial = self.initial or next(iter(self.states), "")
        if not self.final:
            leaving = {s for t in self.transitions for s in t.sources()}
            self.final = tuple(s for s in self.states if s not in leaving)

    @property
    def entity(self) -> str:
        return self.model.__tablename__

    def get(self, name: str) -> Transition:
        for t in self.transitions:
            if t.name == name:
                return t
        raise violation("WF-00", f"the {self.name} workflow has no transition '{name}'; it has: "
                                 + ", ".join(t.name for t in self.transitions))

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title or self.name.replace("_", " ").title(), "entity": self.entity,
                "model": getattr(self.model, "__name__", ""),
                "field": self.field, "initial": self.initial, "final": list(self.final),
                "states": [{"key": k, "label": v, "sla_hours": self.sla.get(k), "escalate_to": self.escalate.get(k)}
                           for k, v in self.states.items()],
                "transitions": [{"name": t.name, "label": t.label or t.name.replace("_", " ").capitalize(),
                                 "from": list(t.sources()), "to": t.target, "roles": list(t.roles),
                                 "approval": t.approval_label(), "approvers": list(t.approvers()),
                                 "pending": t.pending, "requires_reason": t.requires_reason, "rule": t.rule,
                                 "fields": list(t.fields), "tone": t.tone} for t in self.transitions]}


@dataclass
class Context:
    db: Session
    actor: Actor
    workflow: Workflow
    transition: Transition
    from_state: str
    to_state: str
    reason: str = ""
    fields: dict[str, Any] = dc_field(default_factory=dict)
    approval: Approval | None = None
    rule: str | None = None               # the rule that took this move, when the caller knows better than the transition


WORKFLOWS: dict[str, Workflow] = {}


def register(workflow: Workflow) -> Workflow:
    WORKFLOWS[workflow.name] = workflow
    for t in workflow.transitions:
        if t.rule:
            declare(t.rule, t.label or t.name.replace("_", " ").capitalize(), kind="workflow",
                    source=f"{workflow.name} workflow")
    return workflow


def for_model(cls: type) -> list[Workflow]:
    return [w for w in WORKFLOWS.values() if w.model is cls]


def for_entity(entity: str) -> Workflow:
    for w in WORKFLOWS.values():
        if w.entity == entity or w.name == entity:
            return w
    raise violation("WF-00", f"no workflow governs '{entity}'")


def governed_fields(cls: type) -> dict[str, str]:
    return {w.field: w.name for w in for_model(cls)}


def initial_state(cls: type, field_name: str) -> str:
    for w in for_model(cls):
        if w.field == field_name:
            return w.initial
    return ""


# --------------------------------------------------------------------------- deciding

def _refusal(workflow: Workflow, t: Transition, obj: Any, actor: Actor, db: Session | None = None,
             reason: str = "", fields: dict[str, Any] | None = None, check_guard: bool = True) -> tuple[str, str] | None:
    """(rule id, why) when `actor` may not perform `t` on `obj` now; None when they may."""
    state = getattr(obj, workflow.field)
    if not t.leaves(state):
        return "WF-00", (f"{workflow.entity} {getattr(obj, 'id', '')} is {workflow.states.get(state, state)}; "
                         f"'{t.label or t.name}' only applies from: {', '.join(workflow.states.get(s, s) for s in t.sources())}")
    allowed = actor.kind in ("system", "service") or "admin" in actor.roles \
        or (t.roles and actor.has_role(*t.roles)) or (not t.roles and can(f"{workflow.entity}:{t.name}", actor))
    if not allowed:
        who = ", ".join(policy().roles.get(r, r) for r in t.roles) or f"'{workflow.entity}:{t.name}' permission holders"
        return "WF-01", f"only {who} may {t.label or t.name.replace('_', ' ')}; {actor.name} is {', '.join(actor.roles) or 'no role'}"
    if t.requires_reason and not (reason or "").strip() and check_guard:
        return "WF-00", f"'{t.label or t.name}' needs a reason"
    if t.guard and check_guard:
        ctx = Context(db, actor, workflow, t, state, t.target, reason, dict(fields or {}))  # type: ignore[arg-type]
        try:
            said = t.guard(obj, ctx)
        except RuleViolation as exc:
            return exc.rule_id, exc.message
        if isinstance(said, str) and said:
            return t.rule or "WF-00", said
        if said is False:
            return t.rule or "WF-00", f"'{t.label or t.name}' is not allowed for this {workflow.entity} now"
    return None


def available(obj: Any, actor: Actor | None = None, db: Session | None = None) -> list[dict[str, Any]]:
    """Every transition out of the record's state, with whether this actor may take it and why not."""
    actor = actor or current()
    out = []
    for workflow in for_model(type(obj)):
        state = getattr(obj, workflow.field)
        for t in workflow.transitions:
            if not t.leaves(state):
                continue
            refusal = _refusal(workflow, t, obj, actor, db, reason="-", check_guard=True)
            out.append({"workflow": workflow.name, "name": t.name, "label": t.label or t.name.replace("_", " ").capitalize(),
                        "to": t.target, "to_label": workflow.states.get(t.target, t.target),
                        "approval": t.approver(obj) if t.approval else None,
                        "requires_reason": t.requires_reason, "fields": list(t.fields), "tone": t.tone,
                        "allowed": refusal is None, "why_not": refusal[1] if refusal else "",
                        "rule": refusal[0] if refusal else t.rule})
    return out


# --------------------------------------------------------------------------- doing

def _serial(obj: Any) -> dict[str, Any]:
    from sqlalchemy import inspect as sa_inspect
    return {c.key: getattr(obj, c.key) for c in sa_inspect(type(obj)).columns}


def _start_clock(db: Session, workflow: Workflow, obj: Any, state: str) -> None:
    now = utcnow()
    for clock in db.query(WorkflowClock).filter_by(entity=workflow.entity, entity_id=obj.id, left_at=None):
        clock.left_at = now
    hours = workflow.sla.get(state)
    db.add(WorkflowClock(workflow=workflow.name, entity=workflow.entity, entity_id=obj.id, state=state,
                         entered_at=now, due_at=now + dt.timedelta(hours=float(hours)) if hours else None))


def _apply(db: Session, workflow: Workflow, t: Transition, obj: Any, ctx: Context) -> None:
    audit.allow_transition(db, obj, workflow.field)
    setattr(obj, workflow.field, t.target)
    for name in t.fields:
        if name in ctx.fields:
            setattr(obj, name, ctx.fields[name])
    if getattr(obj, "id", None) is None:
        db.flush()
    _start_clock(db, workflow, obj, t.target)
    by = f" (approved by {ctx.approval.decided_by_name})" if ctx.approval else ""
    audit.record(db, "transition",
                 f"{t.label or t.name.replace('_', ' ').capitalize()}: {workflow.entity} {obj.id} "
                 f"{workflow.states.get(ctx.from_state, ctx.from_state)} → {workflow.states.get(t.target, t.target)}{by}"
                 + (f" — {ctx.reason}" if ctx.reason else ""),
                 entity=workflow.entity, entity_id=obj.id, rule_id=ctx.rule or t.rule,
                 changes={workflow.field: [ctx.from_state, t.target], **{k: [None, v] for k, v in ctx.fields.items() if k in t.fields}})
    for effect in t.effects:
        effect(db, obj, ctx)
    if t.notify:
        from .notify import notify
        notify(db, f"{workflow.entity.replace('_', ' ').title()} {obj.id}: {t.label or t.name.replace('_', ' ')}",
               f"{ctx.actor.name} moved it to {workflow.states.get(t.target, t.target)}." + (f" {ctx.reason}" if ctx.reason else ""),
               roles=t.notify, entity=workflow.entity, entity_id=obj.id, kind="transition")


def transition(db: Session, obj: Any, name: str, *, reason: str = "", fields: dict[str, Any] | None = None,
               actor: Actor | None = None, workflow: str | None = None, commit: bool = True,
               rule: str | None = None) -> dict[str, Any]:
    """Perform (or, when it needs approval, request) a transition. Raises RuleViolation when refused.

    `rule` names the rule that took the move when one transition serves several (an
    automatic close by BR-01 or by BR-12); the audit trail records it."""
    actor = actor or current()
    flows = [w for w in for_model(type(obj)) if workflow in (None, w.name)]
    if not flows:
        raise violation("WF-00", f"no workflow governs {type(obj).__name__}")
    wf = next((w for w in flows if any(t.name == name for t in w.transitions)), flows[0])
    t = wf.get(name)
    fields = {k: v for k, v in (fields or {}).items() if k in t.fields}
    refused = _refusal(wf, t, obj, actor, db, reason, fields)
    if refused:
        raise violation(refused[0], refused[1], transition=name)
    state = getattr(obj, wf.field)
    ctx = Context(db, actor, wf, t, state, t.target, reason, fields, rule=rule)
    if t.approval:
        open_ = db.query(Approval).filter_by(entity=wf.entity, entity_id=obj.id, transition=name, status="pending").first()
        if open_:
            raise violation("WF-00", f"'{t.label or name}' is already waiting for approval (#{open_.id})")
        approver = t.approver(obj, ctx)
        if t.pending and state != t.pending:
            # The request is a move of its own: a requisition is "submitted" while it waits.
            if getattr(obj, "id", None) is None:
                db.flush()
            audit.allow_transition(db, obj, wf.field)
            setattr(obj, wf.field, t.pending)
            for field_name in t.fields:
                if field_name in fields:
                    setattr(obj, field_name, fields[field_name])
            _start_clock(db, wf, obj, t.pending)
            audit.record(db, "transition",
                         f"{t.label or name.replace('_', ' ').capitalize()}: {wf.entity} {obj.id} "
                         f"{wf.states.get(state, state)} → {wf.states.get(t.pending, t.pending)}"
                         + (f" — {reason}" if reason else ""),
                         entity=wf.entity, entity_id=obj.id, rule_id=rule or t.rule,
                         changes={wf.field: [state, t.pending]})
            state = t.pending
        label = _label(obj)
        approval = Approval(workflow=wf.name, entity=wf.entity, entity_id=obj.id, transition=name, from_state=state,
                            to_state=t.target, approver_role=approver,
                            title=f"{t.label or name.replace('_', ' ').capitalize()}: {wf.entity.replace('_', ' ')} {obj.id}"
                                  + (f" — {label}" if label else ""),
                            reason=reason, requested_by_id=actor.id, requested_by_name=actor.name,
                            due_at=utcnow() + dt.timedelta(hours=float(wf.sla.get("__approval__", 24))))
        db.add(approval)
        db.flush()
        audit.record(db, "approval", f"Approval requested from {policy().roles.get(approver, approver)} to "
                                     f"{t.label or name}: {wf.entity} {obj.id}" + (f" — {reason}" if reason else ""),
                     entity=wf.entity, entity_id=obj.id, rule_id=t.rule)
        from .notify import notify
        notify(db, f"Approval needed: {approval.title}", f"{actor.name} asks: {reason or 'no reason given'}",
               roles=(approver,), link="#/approvals", entity=wf.entity, entity_id=obj.id, kind="approval_requested",
               exclude_user=actor.id)
        if commit:
            db.commit()
        return {"status": "pending_approval", "approval_id": approval.id, "state": state,
                "message": f"Sent to {policy().roles.get(approver, approver)} for approval"}
    _apply(db, wf, t, obj, ctx)
    if commit:
        db.commit()
        db.refresh(obj)
    return {"status": "done", "state": getattr(obj, wf.field), "record": _serial(obj),
            "message": f"{wf.states.get(t.target, t.target)}"}


def _label(obj: Any) -> str:
    for key in ("name", "title", "subject", "label", "full_name", "number", "reference"):
        v = getattr(obj, key, None)
        if isinstance(v, str) and v.strip():
            return v.strip()[:80]
    return ""


def decide(db: Session, approval_id: int, approve: bool, note: str = "", actor: Actor | None = None) -> dict[str, Any]:
    actor = actor or current()
    a = db.get(Approval, approval_id)
    if a is None:
        raise violation("WF-00", f"no approval {approval_id}")
    if a.status != "pending":
        raise violation("WF-00", f"approval {approval_id} is already {a.status}")
    if actor.kind not in ("system", "service") and not actor.has_role(a.approver_role):
        raise violation("WF-01", f"only {policy().roles.get(a.approver_role, a.approver_role)} may decide this approval")
    if actor.id is not None and actor.id == a.requested_by_id:
        raise violation("WF-02", "you cannot approve your own request; someone else holding the role must")
    wf = WORKFLOWS[a.workflow]
    obj = db.get(wf.model, a.entity_id)
    a.decided_by_id, a.decided_by_name, a.decision_note, a.decided_at = actor.id, actor.name, note, utcnow()
    from .notify import notify
    if not approve:
        a.status = "rejected"
        audit.record(db, "approval", f"Rejected: {a.title}" + (f" — {note}" if note else ""),
                     entity=a.entity, entity_id=a.entity_id)
        t = next((x for x in wf.transitions if x.name == a.transition), None)
        if t is not None and t.on_reject and obj is not None and getattr(obj, wf.field) == a.from_state:
            # The request itself is the record (a proposed change): a rejection ends it.
            audit.allow_transition(db, obj, wf.field)
            setattr(obj, wf.field, t.on_reject)
            _start_clock(db, wf, obj, t.on_reject)
            audit.record(db, "transition", f"Rejected by {actor.name}: {wf.entity} {obj.id} "
                                           f"{wf.states.get(a.from_state, a.from_state)} → {wf.states.get(t.on_reject, t.on_reject)}"
                                           + (f" — {note}" if note else ""),
                         entity=wf.entity, entity_id=obj.id, rule_id=t.rule,
                         changes={wf.field: [a.from_state, t.on_reject]})
        if a.requested_by_id:
            notify(db, f"Rejected: {a.title}", f"{actor.name}: {note or 'no note'}", users=(a.requested_by_id,),
                   level="down", entity=a.entity, entity_id=a.entity_id, kind="approval_decided")
        db.commit()
        return {"status": "rejected", "approval_id": a.id}
    if obj is None or getattr(obj, wf.field) != a.from_state:
        a.status = "withdrawn"
        db.commit()
        raise violation("WF-00", f"{a.entity} {a.entity_id} has moved on since the request; the approval is withdrawn")
    t = wf.get(a.transition)
    ctx = Context(db, actor, wf, t, a.from_state, t.target, a.reason, {}, approval=a)
    a.status = "approved"
    _apply(db, wf, t, obj, ctx)
    if a.requested_by_id:
        notify(db, f"Approved: {a.title}", f"{actor.name}" + (f": {note}" if note else ""), users=(a.requested_by_id,),
               level="ok", entity=a.entity, entity_id=a.entity_id, kind="approval_decided")
    db.commit()
    return {"status": "approved", "approval_id": a.id, "state": getattr(obj, wf.field)}


# --------------------------------------------------------------------------- records that arrive waiting

_ASKED_BY = ("requester_name", "requested_by", "buyer_name", "owner_name", "created_by", "raised_by")


def adopt(db: Session, limit: int = 500) -> int:
    """Records that arrived already waiting for a decision (loaded, imported, migrated) are given
    the approval request they are waiting on, so that someone can decide them. Returns how many."""
    from .models import AppUser
    found = 0
    people: dict[str, int] | None = None
    for wf in list(WORKFLOWS.values()):
        column = getattr(wf.model, wf.field, None)
        for t in wf.transitions:
            if column is None or not t.approval or not t.pending or t.pending in t.sources():
                continue
            waiting = db.query(wf.model).filter(column == t.pending).limit(limit).all()
            if not waiting:
                continue
            asked = {a.entity_id for a in db.query(Approval).filter_by(entity=wf.entity, status="pending")}
            for obj in waiting:
                if obj.id in asked:
                    continue
                ctx = Context(db, current(), wf, t, t.pending, t.target, "", {})
                try:
                    approver = t.approver(obj, ctx)
                except Exception:  # noqa: BLE001 — a record the rule cannot read is left as it is
                    approver = None
                if not approver:
                    continue
                if people is None:
                    people = {str(u.full_name).strip().lower(): u.id for u in db.query(AppUser).all()}
                name = next((str(getattr(obj, k)).strip() for k in _ASKED_BY if isinstance(getattr(obj, k, None), str)
                             and str(getattr(obj, k)).strip()), "")
                label = _label(obj)
                db.add(Approval(workflow=wf.name, entity=wf.entity, entity_id=obj.id, transition=t.name, from_state=t.pending,
                                to_state=t.target, approver_role=approver,
                                title=f"{t.label or t.name.replace('_', ' ').capitalize()}: {wf.entity.replace('_', ' ')} {obj.id}"
                                      + (f" — {label}" if label else ""),
                                reason="", requested_by_id=people.get(name.lower()), requested_by_name=name or "Not recorded",
                                due_at=utcnow() + dt.timedelta(hours=float(wf.sla.get("__approval__", 24)))))
                audit.record(db, "approval", f"Approval requested from {policy().roles.get(approver, approver)} to "
                                             f"{t.label or t.name}: {wf.entity} {obj.id} (it arrived waiting)",
                             entity=wf.entity, entity_id=obj.id, rule_id=t.rule)
                found += 1
    if found:
        db.commit()
    return found


# --------------------------------------------------------------------------- SLAs

def tick(db: Session) -> int:
    """Escalate every clock past its due time. Returns how many breached now."""
    now = utcnow()
    due = db.query(WorkflowClock).filter(WorkflowClock.left_at.is_(None), WorkflowClock.breached_at.is_(None),
                                         WorkflowClock.due_at.is_not(None), WorkflowClock.due_at < now).all()
    from .notify import notify
    for clock in due:
        clock.breached_at = now
        wf = WORKFLOWS.get(clock.workflow)
        role = wf.escalate.get(clock.state) if wf else None
        state = wf.states.get(clock.state, clock.state) if wf else clock.state
        hours = wf.sla.get(clock.state) if wf else None
        audit.record(db, "sla", f"SLA breached: {clock.entity} {clock.entity_id} has been {state} for more than {hours} h"
                     + (f"; escalated to {policy().roles.get(role, role)}" if role else ""),
                     entity=clock.entity, entity_id=clock.entity_id)
        if role:
            notify(db, f"SLA breached: {clock.entity.replace('_', ' ')} {clock.entity_id}",
                   f"{state} for more than {hours} hours.", roles=(role,), level="warn",
                   entity=clock.entity, entity_id=clock.entity_id, kind="sla_breached")
    if due:
        db.commit()
    return len(due)


def clocks_for(db: Session, entity: str, entity_id: int) -> list[dict[str, Any]]:
    rows = db.query(WorkflowClock).filter_by(entity=entity, entity_id=entity_id).order_by(WorkflowClock.id).all()
    return [{"state": c.state, "entered_at": c.entered_at, "left_at": c.left_at, "due_at": c.due_at,
             "breached_at": c.breached_at} for c in rows]


def iter_workflows() -> Iterable[Workflow]:
    return WORKFLOWS.values()
