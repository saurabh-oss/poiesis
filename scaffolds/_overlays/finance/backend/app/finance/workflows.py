"""The lifecycles of procurement and finance, ready to register. Written by Poiesis, and read-only.

Each function returns the workflow of one standard record, built on the kernel: who may
move it, which moves wait for an approval and whose, what happens when it is refused,
and how long it may sit before someone is told. An application registers the ones it
has tables for, against its own models, naming its own roles:

    from ..finance import workflows as flows
    from ..kernel.workflow import register
    from ..models import Requisition, PurchaseOrder, Invoice, Supplier

    REQUISITION = register(flows.requisition(Requisition))
    PURCHASE_ORDER = register(flows.purchase_order(PurchaseOrder, supplier_model=Supplier))
    INVOICE = register(flows.invoice(Invoice, doa=[(10_000, "budget_holder"), (None, "finance_director")]))

Approvals follow the delegation of authority (PROC-02): the amount decides whose
approval a request waits for, and the kernel's four-eyes rule (WF-02) keeps the
requester from approving it. `effects` attaches the application's own consequences to
a move: `effects={"approve": (services.raise_order,)}`.

The states are the standard ones (`standard.STATES`), which the data model's status
columns list in their comments and the demonstration data uses.
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

from ..kernel.workflow import Transition, Workflow
from . import rules
from .standard import STATES

Effects = dict[str, tuple[Callable[..., Any], ...]]

LABELS = {
    "draft": "Draft", "submitted": "Awaiting approval", "approved": "Approved", "rejected": "Rejected",
    "ordered": "Ordered", "cancelled": "Cancelled", "pending_approval": "Awaiting approval", "sent": "Sent to supplier",
    "partially_received": "Partly received", "received": "Received", "closed": "Closed",
    "matched": "Matched", "exception": "Exception", "scheduled": "Scheduled for payment", "paid": "Paid",
    "proposed": "Proposed", "released": "Released", "completed": "Completed", "failed": "Failed",
    "prospective": "Prospective", "under_review": "Under review", "active": "Active", "suspended": "Suspended",
    "retired": "Retired", "in_negotiation": "In negotiation", "signed": "Signed", "expiring": "Expiring",
    "expired": "Expired", "terminated": "Terminated", "applied": "Applied", "identified": "Identified",
    "in_progress": "In progress", "realised": "Realised",
}


def states(entity: str) -> dict[str, str]:
    return {s: LABELS.get(s, s.replace("_", " ").capitalize()) for s in STATES[entity]}


class ByAmount:
    """The approver a record's amount calls for, under a delegation of authority.

    The kernel asks it for a role when an approval is requested; `roles` lists every role
    it can answer with, so the policy can be checked to define them all."""

    def __init__(self, matrix: Sequence[tuple[Any, str]] | None = None, amount: str = "amount") -> None:
        # Without a matrix of its own it follows the organisation's (fin.configure(doa=…)), as it is
        # when it is asked: the application sets it once, where its rules are.
        self._matrix = None if matrix is None else tuple((limit, role) for limit, role in matrix)
        self.amount = amount

    @property
    def matrix(self) -> tuple[tuple[Any, str], ...]:
        return rules.POLICY.doa if self._matrix is None else self._matrix

    @property
    def roles(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(role for _, role in self.matrix))

    def __call__(self, record: Any, ctx: Any = None) -> str:
        return rules.approver_for(rules.get(record, self.amount, 0), self.matrix)

    def __str__(self) -> str:
        return "by amount: " + ", ".join(
            f"{role.replace('_', ' ')} up to {limit:,}" if limit is not None else f"{role.replace('_', ' ')} above"
            for limit, role in self.matrix)

    __repr__ = __str__


def _approval(doa: Any, amount: str) -> Any:
    """A fixed role, or the delegation of authority over the record's amount."""
    if isinstance(doa, str) or callable(doa):
        return doa
    return ByAmount(doa, amount)          # None: by the organisation's delegation of authority


def _has_amount(amount: str) -> Callable[[Any, Any], Any]:
    def guard(record: Any, ctx: Any) -> Any:
        if rules.D(rules.get(record, amount, 0)) <= 0:
            return "Enter an amount greater than zero before sending it for approval"
        return None
    return guard


def _own(model: type, *names: str) -> tuple[str, ...]:
    """The columns among `names` the application's table has: a move sets those, and an
    application that left one out (no `discount_taken`) still gets the lifecycle."""
    table = getattr(model, "__table__", None)
    return tuple(n for n in names if table is None or n in table.columns)


def _hours(value: float | None, setting: str) -> float:
    """The hours a lifecycle was given, or the organisation's own (fin.configure(approval_hours=…))."""
    return float(getattr(rules.POLICY, setting) if value is None else value)


def _told(role: str | None) -> str | None:
    return rules.POLICY.escalate_to if role is None else role


def _fx(effects: Effects | None, name: str) -> tuple[Callable[..., Any], ...]:
    return tuple((effects or {}).get(name, ()))


# --------------------------------------------------------------------------- requisition

def requisition(model: type, *, requester: Sequence[str] = ("requester",), buyer: Sequence[str] = ("buyer",),
                doa: Any = None, amount: str = "amount", field: str = "status",
                escalate_to: str | None = None, approval_hours: float | None = None, effects: Effects | None = None,
                name: str = "requisition") -> Workflow:
    """Draft → awaiting approval → approved → ordered, with rejection and cancellation."""
    approval = _approval(doa, amount)
    escalate_to, approval_hours = _told(escalate_to), _hours(approval_hours, "approval_hours")

    def can_submit(record: Any, ctx: Any) -> Any:
        said = _has_amount(amount)(record, ctx)
        if said:
            return said
        if getattr(ctx, "db", None) is not None:
            from . import operations
            operations.within_budget(ctx.db, record, rules.get(record, amount, 0))      # FIN-02, where it blocks
        return None

    flow = Workflow(
        name, model, field=field, title="Purchase requisition", states=states("requisition"), initial="draft",
        transitions=[
            Transition("submit", "draft", "approved", label="Submit for approval", roles=tuple(requester),
                       approval=approval, pending="submitted", on_reject="rejected", guard=can_submit,
                       rule="PROC-02", effects=_fx(effects, "submit"), tone="ok"),
            Transition("revise", "rejected", "draft", label="Revise", roles=tuple(requester),
                       effects=_fx(effects, "revise")),
            Transition("order", "approved", "ordered", label="Raise the order", roles=tuple(buyer),
                       fields=_own(model, "purchase_order_id"), effects=_fx(effects, "order"), tone="ok"),
            Transition("cancel", ("draft", "submitted", "approved"), "cancelled", label="Cancel",
                       roles=tuple(requester) + tuple(buyer), requires_reason=True, effects=_fx(effects, "cancel"),
                       tone="warn"),
        ],
        sla={"submitted": approval_hours, "__approval__": approval_hours},
        escalate={"submitted": escalate_to} if escalate_to else {},
    )
    return flow


# ------------------------------------------------------------------------ purchase order

def purchase_order(model: type, *, buyer: Sequence[str] = ("buyer",), receiver: Sequence[str] = ("requester", "buyer"),
                   doa: Any = None, amount: str = "amount", field: str = "status",
                   supplier_model: type | None = None, escalate_to: str | None = None,
                   approval_hours: float | None = None, effects: Effects | None = None,
                   name: str = "purchase_order") -> Workflow:
    """Draft → awaiting approval → approved → sent → (partly) received → closed."""
    escalate_to, approval_hours = _told(escalate_to), _hours(approval_hours, "approval_hours")

    def can_order(record: Any, ctx: Any) -> Any:
        said = _has_amount(amount)(record, ctx)
        if said:
            return said
        if supplier_model is not None and getattr(ctx, "db", None) is not None and rules.get(record, "supplier_id"):
            supplier = ctx.db.get(supplier_model, rules.get(record, "supplier_id"))
            if supplier is not None:
                rules.check_supplier(supplier)          # PROC-09
        return None

    def from_a_request(record: Any, ctx: Any) -> Any:
        # An order raised from a requisition was approved as that requisition: it is not approved twice.
        if not rules.get(record, "requisition_id"):
            return "Only an order raised from an approved requisition is released without an approval of its own"
        return can_order(record, ctx)

    return Workflow(
        name, model, field=field, title="Purchase order", states=states("purchase_order"), initial="draft",
        transitions=[
            Transition("submit", "draft", "approved", label="Submit for approval", roles=tuple(buyer),
                       approval=_approval(doa, amount), pending="pending_approval", on_reject="draft", guard=can_order,
                       rule="PROC-02", effects=_fx(effects, "submit"), tone="ok"),
            Transition("release", "draft", "approved", label="Release (approved as a requisition)", roles=tuple(buyer),
                       guard=from_a_request, rule="PROC-02", effects=_fx(effects, "release"), tone="ok"),
            Transition("send", "approved", "sent", label="Send to supplier", roles=tuple(buyer),
                       effects=_fx(effects, "send"), tone="ok"),
            Transition("receive_part", ("sent", "partially_received"), "partially_received", label="Receive part",
                       roles=tuple(receiver), fields=_own(model, "received_amount"), effects=_fx(effects, "receive_part")),
            Transition("receive", ("sent", "partially_received"), "received", label="Receive in full",
                       roles=tuple(receiver), fields=_own(model, "received_amount", "delivered_at"),
                       effects=_fx(effects, "receive"), tone="ok"),
            Transition("close", ("received", "partially_received"), "closed", label="Close", roles=tuple(buyer),
                       effects=_fx(effects, "close")),
            Transition("cancel", ("draft", "pending_approval", "approved", "sent"), "cancelled", label="Cancel",
                       roles=tuple(buyer), requires_reason=True, effects=_fx(effects, "cancel"), tone="warn"),
        ],
        sla={"pending_approval": approval_hours, "__approval__": approval_hours},
        escalate={"pending_approval": escalate_to} if escalate_to else {},
    )


# ------------------------------------------------------------------------------ invoice

def invoice(model: type, *, clerk: Sequence[str] = ("ap_clerk",), payer: Sequence[str] = ("treasury",),
            doa: Any = "budget_holder", amount: str = "amount", field: str = "status",
            escalate_to: str | None = None, exception_hours: float | None = None,
            approval_hours: float | None = None, effects: Effects | None = None, name: str = "invoice") -> Workflow:
    """Received → matched or exception → approved → scheduled → paid. `doa` is the role
    that approves a matched invoice, or a delegation of authority by amount."""
    escalate_to = _told(escalate_to)
    exception_hours = _hours(exception_hours, "exception_hours")
    approval_hours = _hours(approval_hours, "approval_hours")
    return Workflow(
        name, model, field=field, title="Supplier invoice", states=states("invoice"), initial="received",
        transitions=[
            Transition("match", "received", "matched", label="Match", roles=tuple(clerk), fields=_own(model, "match_status"),
                       rule="PROC-01", effects=_fx(effects, "match"), tone="ok"),
            Transition("flag", "received", "exception", label="Raise an exception", roles=tuple(clerk),
                       fields=_own(model, "match_status", "exception_reason"), rule="PROC-01", effects=_fx(effects, "flag"),
                       tone="warn"),
            Transition("resolve", "exception", "matched", label="Resolve the exception", roles=tuple(clerk),
                       requires_reason=True, fields=_own(model, "match_status"), effects=_fx(effects, "resolve"), tone="ok"),
            Transition("approve", "matched", "approved", label="Approve for payment", roles=tuple(clerk),
                       approval=_approval(doa, amount), on_reject="exception", rule="PROC-02",
                       fields=_own(model, "approver_name", "approved_at"), effects=_fx(effects, "approve"), tone="ok"),
            Transition("schedule", "approved", "scheduled", label="Schedule payment", roles=tuple(clerk) + tuple(payer),
                       fields=_own(model, "payment_id"), effects=_fx(effects, "schedule")),
            Transition("pay", "scheduled", "paid", label="Mark as paid", roles=tuple(payer),
                       fields=_own(model, "paid_at", "payment_id", "discount_taken"), effects=_fx(effects, "pay"), tone="ok"),
            Transition("reject", ("received", "exception", "matched"), "rejected", label="Reject", roles=tuple(clerk),
                       requires_reason=True, effects=_fx(effects, "reject"), tone="down"),
        ],
        sla={"exception": exception_hours, "matched": approval_hours, "__approval__": approval_hours},
        escalate=({"exception": escalate_to, "matched": escalate_to} if escalate_to else {}),
    )


# -------------------------------------------------------------------------- payment run

def payment_run(model: type, *, proposer: Sequence[str] = ("ap_clerk",), releaser: Sequence[str] = ("treasury",),
                approver: str = "finance_controller", field: str = "status", effects: Effects | None = None,
                name: str = "payment_run") -> Workflow:
    """Proposed → approved → released → completed. The proposer never approves (FIN-01)."""
    return Workflow(
        name, model, field=field, title="Payment run", states=states("payment_run"), initial="proposed",
        transitions=[
            Transition("approve", "proposed", "approved", label="Approve the run", roles=tuple(proposer),
                       approval=approver, rule="FIN-01", fields=_own(model, "approved_by"), effects=_fx(effects, "approve"),
                       tone="ok"),
            Transition("release", "approved", "released", label="Release to the bank", roles=tuple(releaser),
                       effects=_fx(effects, "release"), tone="ok"),
            Transition("complete", "released", "completed", label="Confirm completed", roles=tuple(releaser),
                       effects=_fx(effects, "complete"), tone="ok"),
        ],
        sla={"proposed": 24, "__approval__": 24},
    )


# ------------------------------------------------------------------------------ supplier

def supplier(model: type, *, owner: Sequence[str] = ("buyer",), approver: str = "procurement_manager",
             field: str = "status", effects: Effects | None = None, name: str = "supplier") -> Workflow:
    """Prospective → under review → approved → active, and suspension and retirement."""
    return Workflow(
        name, model, field=field, title="Supplier", states=states("supplier"), initial="prospective",
        transitions=[
            Transition("submit", "prospective", "approved", label="Submit for onboarding", roles=tuple(owner),
                       approval=approver, pending="under_review", on_reject="prospective", rule="PROC-09",
                       effects=_fx(effects, "submit"), tone="ok"),
            Transition("activate", "approved", "active", label="Activate", roles=tuple(owner),
                       effects=_fx(effects, "activate"), tone="ok"),
            Transition("suspend", ("approved", "active"), "suspended", label="Suspend", roles=tuple(owner) + (approver,),
                       requires_reason=True, effects=_fx(effects, "suspend"), tone="warn"),
            Transition("reinstate", "suspended", "active", label="Reinstate", roles=tuple(owner), approval=approver,
                       requires_reason=True, effects=_fx(effects, "reinstate")),
            Transition("retire", ("active", "suspended", "approved"), "retired", label="Retire", roles=(approver,),
                       requires_reason=True, effects=_fx(effects, "retire"), tone="down"),
        ],
        sla={"under_review": 120, "__approval__": 120},
    )


# ------------------------------------------------------------------------------ contract

def contract(model: type, *, owner: Sequence[str] = ("buyer",), doa: Any = "procurement_manager",
             amount: str = "value", field: str = "status", effects: Effects | None = None,
             name: str = "contract") -> Workflow:
    """Draft → in negotiation → signed → active → expiring → expired, renewal and termination."""
    return Workflow(
        name, model, field=field, title="Contract", states=states("contract"), initial="draft",
        transitions=[
            Transition("negotiate", "draft", "in_negotiation", label="Start negotiation", roles=tuple(owner),
                       effects=_fx(effects, "negotiate")),
            Transition("sign", "in_negotiation", "signed", label="Sign", roles=tuple(owner),
                       approval=_approval(doa, amount), on_reject="in_negotiation", rule="PROC-02",
                       effects=_fx(effects, "sign"), tone="ok"),
            Transition("activate", "signed", "active", label="Activate", roles=tuple(owner),
                       effects=_fx(effects, "activate"), tone="ok"),
            Transition("flag_expiring", "active", "expiring", label="Mark as expiring", roles=tuple(owner),
                       rule="PROC-07", effects=_fx(effects, "flag_expiring"), tone="warn"),
            Transition("renew", ("active", "expiring"), "active", label="Renew", roles=tuple(owner),
                       approval=_approval(doa, amount), fields=_own(model, "end_date", "value", "annual_value"),
                       requires_reason=True, effects=_fx(effects, "renew"), tone="ok"),
            Transition("expire", ("active", "expiring"), "expired", label="Let it expire", roles=tuple(owner),
                       effects=_fx(effects, "expire")),
            Transition("terminate", ("signed", "active", "expiring"), "terminated", label="Terminate",
                       roles=tuple(owner), requires_reason=True, approval=_approval(doa, amount),
                       effects=_fx(effects, "terminate"), tone="down"),
        ],
        sla={"in_negotiation": 720, "__approval__": 72},
    )


# ------------------------------------------------------------------------- budget change

def budget_change(model: type, *, requester: Sequence[str] = ("budget_holder",), approver: str = "finance_controller",
                  field: str = "status", effects: Effects | None = None, name: str = "budget_change") -> Workflow:
    """Proposed → approved → applied; a rejected proposal ends there."""
    return Workflow(
        name, model, field=field, title="Budget change", states=states("budget_change"), initial="proposed",
        transitions=[
            Transition("approve", "proposed", "approved", label="Send for approval", roles=tuple(requester),
                       approval=approver, on_reject="rejected", requires_reason=True, rule="FIN-02",
                       fields=_own(model, "decided_at"), effects=_fx(effects, "approve"), tone="ok"),
            Transition("apply", "approved", "applied", label="Apply to the budget", roles=(approver,),
                       effects=_fx(effects, "apply"), tone="ok"),
        ],
        sla={"proposed": 72, "__approval__": 72},
    )


FACTORIES = {"requisition": requisition, "purchase_order": purchase_order, "invoice": invoice,
             "payment_run": payment_run, "supplier": supplier, "contract": contract, "budget_change": budget_change}
