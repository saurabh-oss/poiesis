"""What procurement and finance do to their records. Written by Poiesis, and read-only.

The rules decide (rules.py); these operations read the records a decision needs, apply
the rule, move the record through its workflow and say why in the audit trail. They work
on the standard entities (standard.py) whichever model classes the application gave them.

    from ..finance import operations as ops

    ops.match_invoice(db, invoice_id)                  three-way match, duplicates, no order no pay; moves the invoice
    ops.receive_goods(db, order_id, amount=1200)       posts a receipt, moves the order, says whether it was on time
    ops.propose_payment_run(db, due_by=date)           gathers approved invoices into a run, taking discounts worth taking
    ops.budget_position(db, cost_center_id, requested=5000)      what is left of the year's budget (FIN-02)
    ops.check_request(db, requisition)                 what to tell a requester before they submit
    ops.create_requisition(db, {"title": …, "amount": 1800, "cost_center_id": 7})     a draft, with its reference
    ops.raise_order(db, requisition_id, supplier_id=12)          the order of an approved requisition (PROC-02, PROC-09)
    ops.send_order(db, order_id)                       to the supplier, and into the ERP
    ops.waiting(db)                                    the approvals waiting, and whether I may decide each

Also served, for the person signed in, under /api/finance/ (api.py):

    POST /api/finance/invoices/{id}/match
    POST /api/finance/purchase-orders/{id}/receive     {"amount": 1200, "quantity": 10, "received_by": "Goods In"}
    POST /api/finance/payment-runs/propose             {"due_by": "2026-10-09", "run_date": "2026-10-01"}
    GET  /api/finance/budget/position?cost_center_id=3&requested=5000
    GET  /api/finance/requisitions/{id}/advice
    POST /api/finance/requisitions                     {"title": "Label printers", "amount": 1800, "cost_center_id": 7}
    POST /api/finance/requisitions/{id}/order          {"supplier_id": 12, "expected_delivery": "2026-10-20"}
    POST /api/finance/purchase-orders/{id}/send
    GET  /api/finance/approvals

Every move goes through the record's workflow when the application registered one, so
roles, approvals and the audit trail apply; without one, the status is set as it stands.
"""
from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Base
from ..kernel import record, transition, violation
from ..kernel.workflow import for_model
from . import money
from . import rules as fin
from .money import D
from .periods import FiscalCalendar, as_date
from .rules import get

OPEN_ORDER = ("approved", "sent", "partially_received", "received")


def model(table: str) -> type | None:
    """The application's model class for a table, whatever it is called."""
    for mapper in Base.registry.mappers:
        if getattr(mapper.class_, "__tablename__", None) == table:
            return mapper.class_
    return None


def columns(table: str) -> set[str]:
    cls = model(table)
    return {c.key for c in cls.__table__.columns} if cls is not None else set()


def need(table: str) -> type:
    cls = model(table)
    if cls is None:
        raise HTTPException(status_code=404, detail=f"this application has no {table.replace('_', ' ')} table")
    return cls


def row(db: Session, table: str, ref: Any) -> Any:
    """A record from its id, or the record itself."""
    if ref is None or not isinstance(ref, (int, str)):
        return ref
    found = db.get(need(table), int(ref))
    if found is None:
        raise HTTPException(status_code=404, detail=f"{table.replace('_', ' ')} {ref} not found")
    return found


def base_currency() -> str:
    return (os.getenv("BASE_CURRENCY", "GBP") or "GBP").upper()


def calendar() -> FiscalCalendar:
    try:
        return FiscalCalendar(int(os.getenv("FISCAL_YEAR_START_MONTH", "4") or 4))
    except ValueError:
        return FiscalCalendar(4)


def today() -> dt.date:
    try:
        return as_date(os.getenv("FINANCE_AS_OF", "")) or dt.date.today()
    except ValueError:
        return dt.date.today()


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _session(db: Any, operation: str) -> None:
    if not hasattr(db, "execute") or not hasattr(db, "get"):
        raise TypeError(f"ops.{operation}(db, …): the first argument is the database session the router was "
                        f"given (`db: Session = Depends(get_session)`), then the record; it was given {type(db).__name__}")


def _put(obj: Any, **values: Any) -> None:
    """Set the columns the record has; an application may have left some out."""
    have = {c.key for c in type(obj).__table__.columns}
    for name, value in values.items():
        if name in have:
            setattr(obj, name, value)


def _move(db: Session, obj: Any, name: str, *, reason: str = "", fields: dict[str, Any] | None = None,
          rule: str | None = None, status: str = "") -> dict[str, Any]:
    """Through the workflow when there is one; otherwise the status as it stands."""
    if for_model(type(obj)):
        return transition(db, obj, name, reason=reason, fields=fields or {}, rule=rule, commit=False)
    _put(obj, **(fields or {}))
    if status:
        _put(obj, status=status)
    return {"status": "done", "state": status}


def _next_reference(db: Session, cls: type, prefix: str, start: int) -> str:
    last = db.execute(select(cls.id).order_by(cls.id.desc()).limit(1)).scalar() or 0
    return f"{prefix}{start + last + 1}"


# ----------------------------------------------------------------------- requesting and ordering

def create_requisition(db: Session, values: dict[str, Any], *, commit: bool = True) -> Any:
    """A draft requisition from what a requester filled in: its reference, who asked and when are
    the application's to say, not the form's."""
    from ..kernel import current
    _session(db, "create_requisition")
    cls = need("requisition")
    fin.check(D(values.get("amount") or 0) > 0, "PROC-02", "Enter the amount: it must be more than zero")
    fin.check(bool(str(values.get("title") or "").strip()), "PROC-02", "Say what is being bought: the title is empty")
    actor = current()
    req = cls()
    have = columns("requisition")
    _put(req, **{k: v for k, v in values.items() if k in have and k not in ("id", "status", "reference", "approver_name",
                                                                               "approved_at", "submitted_at", "purchase_order_id")})
    for name in ("needed_by",):
        if isinstance(get(req, name), str):
            _put(req, **{name: as_date(get(req, name))})
    _put(req, reference=_next_reference(db, cls, "PR-", 110_000), status="draft", created_at=now(),
         requester_name=str(values.get("requester_name") or actor.name), currency=values.get("currency") or base_currency())
    db.add(req)
    db.flush()
    if commit:
        db.commit()
    return req


def raise_order(db: Session, requisition: Any, *, supplier_id: Any = None, expected_delivery: Any = None,
                commit: bool = True) -> dict[str, Any]:
    """The purchase order of an approved requisition: with an approved supplier (PROC-09), released
    without a second approval because it was approved as a requisition (PROC-02), and the requisition
    marked ordered."""
    from ..kernel import current
    _session(db, "raise_order")
    req = row(db, "requisition", requisition)
    if get(req, "status", "") != "approved":
        raise violation("PROC-02", f"{get(req, 'reference', 'This requisition')} is "
                                   f"{str(get(req, 'status', '')).replace('_', ' ')}: an order is raised once it is approved")
    orders = need("purchase_order")
    chosen = supplier_id or get(req, "supplier_id")
    fin.check(bool(chosen), "PROC-09", "Choose the supplier the order goes to")
    supplier = db.get(need("supplier"), int(chosen)) if model("supplier") is not None else None
    if model("supplier") is not None:
        fin.check(supplier is not None, "PROC-09", "Choose a supplier that exists")
        fin.check_supplier(supplier)
    po = orders()
    day = today()
    _put(po, reference=_next_reference(db, orders, "PO-46", 10_000_000), supplier_id=int(chosen), requisition_id=req.id,
         cost_center_id=get(req, "cost_center_id"), spend_category_id=get(req, "spend_category_id"),
         buyer_name=current().name, status="draft", amount=float(D(get(req, "amount", 0))),
         currency=get(req, "currency", base_currency()), received_amount=0.0, invoiced_amount=0.0, order_date=day,
         expected_delivery=as_date(expected_delivery) or get(req, "needed_by"),
         payment_terms=get(supplier, "payment_terms", "NET30") or "NET30", created_at=now())
    db.add(po)
    db.flush()
    lines = model("purchase_order_line")
    if lines is not None:
        line = lines()
        _put(line, purchase_order_id=po.id, line_no=1, description=str(get(req, "title", ""))[:300], quantity=1.0, unit="each",
             unit_price=get(po, "amount"), amount=get(po, "amount"), received_quantity=0.0, invoiced_quantity=0.0,
             spend_category_id=get(req, "spend_category_id"))
        db.add(line)
    _move(db, po, "release", rule="PROC-02", status="approved",
          reason=f"Approved as requisition {get(req, 'reference', req.id)}")
    _move(db, req, "order", fields={"purchase_order_id": po.id}, status="ordered")
    _put(req, purchase_order_id=po.id)
    if commit:
        db.commit()
    return {"purchase_order_id": po.id, "reference": get(po, "reference", ""), "status": get(po, "status"),
            "requisition_id": req.id, "requisition_status": get(req, "status"), "supplier": get(supplier, "name", ""),
            "amount": get(po, "amount")}


def send_order(db: Session, order: Any, *, commit: bool = True) -> dict[str, Any]:
    """Send an approved order to the supplier, and create it in the ERP (in its sandbox until the
    ERP's credentials are set). Sending it twice creates it once. The move is committed before the
    ERP is called, whatever `commit` says: an order the ERP holds is an order that was sent."""
    from .. import connectors
    _session(db, "send_order")
    po = row(db, "purchase_order", order)
    supplier = db.get(model("supplier"), po.supplier_id) if model("supplier") is not None and get(po, "supplier_id") else None
    _move(db, po, "send", status="sent")
    result = None
    if "erp" in getattr(connectors, "CONNECTORS", {}):
        db.commit()              # the connector keeps its outbox in a session of its own: the order is sent first
        lines = []
        if model("purchase_order_line") is not None:
            cls = model("purchase_order_line")
            lines = [{"description": get(ln, "description", ""), "quantity": get(ln, "quantity", 1), "unit_price": get(ln, "unit_price", 0),
                      "amount": get(ln, "amount", 0)}
                     for ln in db.execute(select(cls).where(cls.purchase_order_id == po.id)).scalars().all()]
        centre = db.get(model("cost_center"), po.cost_center_id) if model("cost_center") is not None and get(po, "cost_center_id") else None
        result = connectors.get("erp").create_purchase_order(
            get(po, "reference", ""), get(supplier, "code", str(get(po, "supplier_id", ""))), get(po, "amount", 0), lines=lines,
            cost_center=get(centre, "code", ""), currency=get(po, "currency", base_currency()),
            idempotency_key=f"po-{get(po, 'reference', po.id)}", ref=f"purchase_order:{po.id}")
        record(db, "connector", f"{get(po, 'reference', 'Order')} created in the ERP as {result.key} ({result.mode})" if result.ok
               else f"{get(po, 'reference', 'Order')} could not be created in the ERP: {result.error}",
               entity="purchase_order", entity_id=po.id)
    if commit:
        db.commit()
    return {"purchase_order_id": po.id, "reference": get(po, "reference", ""), "status": get(po, "status"),
            "erp": result.as_dict() if result is not None else None}


def waiting(db: Session, entity: str = "") -> list[dict[str, Any]]:
    """The approvals that are waiting, each with the record it is about and whether the person
    asking may decide it (their role, and not their own request: four eyes)."""
    from ..kernel import current
    from ..kernel.models import Approval, aware, utcnow
    from ..kernel.policy import policy
    _session(db, "waiting")
    actor = current()
    q = db.query(Approval).filter(Approval.status == "pending")
    if entity:
        q = q.filter(Approval.entity == entity)
    out = []
    labels = policy().roles
    for a in q.order_by(Approval.id).all():
        cls = model(a.entity)
        rec = db.get(cls, a.entity_id) if cls is not None else None
        if rec is None:
            continue
        mine = actor.has_role(a.approver_role) or actor.kind in ("system", "service")
        out.append({"approval_id": a.id, "entity": a.entity, "entity_id": a.entity_id, "transition": a.transition,
                    "title": a.title, "approver_role": a.approver_role, "approver": labels.get(a.approver_role, a.approver_role),
                    "requested_by": a.requested_by_name, "requested_at": a.requested_at, "reason": a.reason,
                    "due_at": a.due_at, "overdue": bool(a.due_at and aware(a.due_at) < utcnow()),
                    "can_decide": bool(mine and a.requested_by_id != actor.id), "record": rec})

    def since(item: dict[str, Any]) -> str:
        # A queue is worked oldest first, by when the record was raised: the request for its
        # approval may be younger than it (a record that arrived already waiting).
        for name in ("created_at", "submitted_at", "order_date", "invoice_date", "run_date"):
            value = get(item["record"], name)
            if value:
                return str(value.isoformat() if hasattr(value, "isoformat") else value)
        return str(item["requested_at"].isoformat() if item["requested_at"] else "")
    return sorted(out, key=lambda item: (since(item), item["approval_id"]))


# ------------------------------------------------------------------------------ matching

def match_invoice(db: Session, invoice: Any, *, tolerance: fin.Tolerance | None = None, move: bool = True,
                  commit: bool = True) -> dict[str, Any]:
    """Match an invoice to its order and receipts (PROC-01), after checking that it is not a
    duplicate (PROC-03) and that it names an order where one is needed (PROC-06).

    A received invoice is moved to matched or to exception, with the reason. Returns the
    match: status, ok, ordered, received, invoiced, discrepancies and the rule that decided."""
    _session(db, "match_invoice")
    inv = row(db, "invoice", invoice)
    cls = type(inv)
    currency = get(inv, "currency", base_currency())
    others = db.execute(select(cls).where(cls.supplier_id == inv.supplier_id, cls.id != inv.id)).scalars().all() \
        if "supplier_id" in columns("invoice") else []
    live = [o for o in others if get(o, "status", "") != "rejected"]
    rule, status, notes = "PROC-01", "matched", []
    ordered = received = Decimal(0)
    invoiced = money.quantize(get(inv, "net_amount", None) or get(inv, "amount", 0), currency)

    twins = fin.duplicate_invoices(inv, live) if "supplier_invoice_number" in columns("invoice") else []
    exact = [t for t in twins if t["confidence"] == "exact"]
    order = db.get(model("purchase_order"), inv.purchase_order_id) \
        if model("purchase_order") is not None and get(inv, "purchase_order_id") else None
    if exact:
        rule, status = "PROC-03", "duplicate_suspect"
        notes = [f"looks like {get(t['invoice'], 'reference', 'an earlier invoice')}: {t['reason']}" for t in exact]
    elif order is None:
        category = db.get(model("spend_category"), inv.spend_category_id) \
            if model("spend_category") is not None and get(inv, "spend_category_id") else None
        exempt = fin.exempt_from_order(category)
        if fin.po_required(get(inv, "amount", 0), exempt=exempt):
            rule, status = "PROC-06", "no_po"
            notes = [f"an invoice above {money.fmt(fin.POLICY.po_required_above, currency)} must name a purchase order"]
        else:
            rule, status = "PROC-06", "matched"
    else:
        receipts_cls = model("goods_receipt")
        receipts = db.execute(select(receipts_cls).where(receipts_cls.purchase_order_id == order.id)).scalars().all() \
            if receipts_cls is not None else []
        if receipts_cls is None and D(get(order, "received_amount", 0)) > 0:
            receipts = [{"amount": get(order, "received_amount", 0), "status": "posted"}]
        taken = sum((D(get(o, "net_amount", None) or get(o, "amount", 0)) for o in live
                     if get(o, "purchase_order_id") == order.id and get(o, "status", "") != "exception"), Decimal(0))
        m = fin.three_way_match(order, receipts, inv, tolerance, currency, already_invoiced=taken)
        status, notes, ordered, received = m.status, list(m.discrepancies), m.ordered, m.received
    ok = status == "matched"
    reason = "; ".join(notes)[:300]
    out = {"invoice_id": inv.id, "reference": get(inv, "reference", ""), "status": status, "ok": ok, "rule": rule,
           "ordered": float(ordered), "received": float(received), "invoiced": float(invoiced),
           "discrepancies": notes, "possible_duplicates": [
               {"id": t["invoice"].id, "reference": get(t["invoice"], "reference", ""), "confidence": t["confidence"]}
               for t in twins], "moved": None}
    if move and get(inv, "status", "") == "received":
        if ok:
            _move(db, inv, "match", fields={"match_status": status}, rule=rule, status="matched")
        else:
            _move(db, inv, "flag", reason=reason, fields={"match_status": status, "exception_reason": reason},
                  rule=rule, status="exception")
        out["moved"] = get(inv, "status")
        if order is not None and ok:
            _put(order, invoiced_amount=float(money.quantize(D(get(order, "invoiced_amount", 0)) + invoiced, currency)))
    elif move:
        _put(inv, match_status=status)
    record(db, "rule", (f"{get(inv, 'reference', 'Invoice')} matched its order and receipt" if ok and order is not None
                        else f"{get(inv, 'reference', 'Invoice')} needs no order" if ok
                        else f"{get(inv, 'reference', 'Invoice')} held: {reason}"),
           entity="invoice", entity_id=inv.id, rule_id=rule)
    if commit:
        db.commit()
    return out


# ------------------------------------------------------------------------------ receiving

def receive_goods(db: Session, order: Any, amount: Any, *, quantity: Any = None, received_by: str = "",
                  received_at: dt.datetime | None = None, quality_ok: bool = True, commit: bool = True) -> dict[str, Any]:
    """Post a receipt against an order: the receipt, the order's received value, and the
    order's move to partly received or received. Says whether it came on time and in full."""
    _session(db, "receive_goods")
    po = row(db, "purchase_order", order)
    currency = get(po, "currency", base_currency())
    value = money.quantize(amount, currency)
    fin.check(value > 0, "PROC-01", "Enter the value received: it must be more than zero")
    if get(po, "status", "") not in ("sent", "partially_received"):
        raise violation("PROC-01", f"{get(po, 'reference', 'This order')} is {str(get(po, 'status', '')).replace('_', ' ')}: "
                                   "goods are received against an order that has been sent to the supplier")
    when = received_at or now()
    before = D(get(po, "received_amount", 0))
    total = money.quantize(before + value, currency)
    ordered = D(get(po, "amount", 0))
    in_full = total >= ordered
    expected = get(po, "expected_delivery")
    on_time = None if expected is None else as_date(when) <= as_date(expected)
    receipt_id = None
    cls = model("goods_receipt")
    if cls is not None:
        receipt = cls()
        _put(receipt, reference=_next_reference(db, cls, "GR-", 5_100_000), purchase_order_id=po.id,
             received_by=received_by or "", received_at=when, quantity=float(D(quantity)) if quantity is not None else None,
             amount=float(value), status="posted", on_time=bool(on_time) if on_time is not None else None,
             in_full=in_full, quality_ok=bool(quality_ok))
        db.add(receipt)
        db.flush()
        receipt_id = receipt.id
    fields = {"received_amount": float(total)}
    if in_full:
        fields["delivered_at"] = as_date(when)
    _move(db, po, "receive" if in_full else "receive_part", fields=fields, rule="PROC-01",
          status="received" if in_full else "partially_received")
    if commit:
        db.commit()
    return {"purchase_order_id": po.id, "reference": get(po, "reference", ""), "goods_receipt_id": receipt_id,
            "received": float(value), "received_so_far": float(total), "ordered": float(ordered), "in_full": in_full,
            "on_time": on_time, "status": get(po, "status")}


# --------------------------------------------------------------------------------- paying

def payable(db: Session, *, due_by: Any = None, as_of: Any = None, take_discounts: bool = True) -> list[dict[str, Any]]:
    """The approved invoices a payment run would pay: those due by `due_by`, and those whose
    early payment discount can still be taken and is worth taking (FIN-04)."""
    _session(db, "payable")
    cls = need("invoice")
    day = as_date(as_of) or today()
    limit = as_date(due_by) or day + dt.timedelta(days=7)
    out = []
    for inv in db.execute(select(cls).where(cls.status == "approved")).scalars().all():
        if get(inv, "payment_id"):
            continue
        currency = get(inv, "currency", base_currency())
        amount = money.quantize(get(inv, "amount", 0), currency)
        discount = fin.early_payment_discount(amount, get(inv, "invoice_date") or day, get(inv, "payment_terms", ""), day, currency) \
            if take_discounts and get(inv, "invoice_date") else None
        early = bool(discount and discount.available and discount.amount > 0)
        due = as_date(get(inv, "due_date"))
        if not early and (due is None or due > limit):
            continue
        out.append({"invoice": inv, "invoice_id": inv.id, "reference": get(inv, "reference", ""),
                    "supplier_id": get(inv, "supplier_id"), "amount": float(amount), "due_date": due,
                    "discount": float(discount.amount) if early else 0.0,
                    "pay": float(discount.pay) if early else float(amount), "currency": currency,
                    "why": "early payment discount" if early and (due is None or due > limit) else "due"})
    return sorted(out, key=lambda r: (r["due_date"] or limit, r["reference"]))


def propose_payment_run(db: Session, *, run_date: Any = None, due_by: Any = None, take_discounts: bool = True,
                        created_by: str = "", method: str = "bacs", commit: bool = True) -> dict[str, Any]:
    """Gather what is payable into a proposed run with one payment per supplier, and schedule
    the invoices. The run then waits for approval and release by other people (FIN-01)."""
    from ..kernel import current
    items = payable(db, due_by=due_by, as_of=run_date, take_discounts=take_discounts)
    if not items:
        raise violation("FIN-03", "Nothing is payable: no approved invoice is due by then or has a discount to take")
    runs, payments = need("payment_run"), need("payment")
    day = as_date(run_date) or today()
    week = day.isocalendar()
    actor = current()
    run = runs()
    _put(run, reference=f"RUN-{week[0]}-{week[1]:02d}-{(db.execute(select(runs.id).order_by(runs.id.desc()).limit(1)).scalar() or 0) + 1}",
         status="proposed", run_date=day, total_amount=float(money.total(i["pay"] for i in items)),
         payment_count=len({i["supplier_id"] for i in items}), currency=base_currency(),
         created_by=created_by or actor.name, approved_by=None)
    db.add(run)
    db.flush()
    by_supplier: dict[Any, list[dict[str, Any]]] = {}
    for item in items:
        by_supplier.setdefault(item["supplier_id"], []).append(item)
    made = []
    for supplier_id, theirs in by_supplier.items():
        pay = payments()
        _put(pay, reference=_next_reference(db, payments, "PAY-", 9_900_000), supplier_id=supplier_id, payment_run_id=run.id,
             amount=float(money.total(i["pay"] for i in theirs)), currency=theirs[0]["currency"], method=method,
             status="proposed", scheduled_for=day, discount_taken=float(money.total(i["discount"] for i in theirs)))
        db.add(pay)
        db.flush()
        for item in theirs:
            _move(db, item["invoice"], "schedule", fields={"payment_id": pay.id}, rule="FIN-03", status="scheduled")
        made.append({"payment_id": pay.id, "reference": get(pay, "reference", ""), "supplier_id": supplier_id,
                     "amount": get(pay, "amount"), "invoices": [i["reference"] for i in theirs],
                     "discount_taken": get(pay, "discount_taken", 0.0)})
    record(db, "rule", f"{get(run, 'reference', 'Payment run')} proposed: {len(items)} invoices to {len(made)} suppliers, "
                       f"{money.fmt(get(run, 'total_amount', 0), base_currency())}",
           entity="payment_run", entity_id=run.id, rule_id="FIN-03")
    if commit:
        db.commit()
    return {"payment_run_id": run.id, "reference": get(run, "reference", ""), "run_date": day, "status": "proposed",
            "total_amount": get(run, "total_amount"), "invoices": len(items),
            "discounts_taken": float(money.total(i["discount"] for i in items)), "payments": made}


# -------------------------------------------------------------------------------- budget

def within_budget(db: Session, record: Any, amount: Any) -> None:
    """Refuse (FIN-02) a request that takes its cost centre above the year's budget, where the
    organisation set `budget_control="block"`. A budget change that was approved and applied is in
    the budget already, so it is what lets the request through. Without a cost centre, a budget
    table or a budget for the year there is nothing to hold the request to, and it passes."""
    if fin.POLICY.budget_control != "block" or not get(record, "cost_center_id") or model("budget_line") is None:
        return
    position = budget_position(db, get(record, "cost_center_id"), requested=amount, on=get(record, "created_at") or today())
    fin.check(not (position["budget"] > 0 and position["status"] == "exceeded"), "FIN-02",
              position["message"] + ". It cannot be submitted until a budget change is approved",
              cost_center_id=position["cost_center_id"], remaining=position["remaining"])


def budget_position(db: Session, cost_center_id: Any, *, requested: Any = 0, on: Any = None,
                    spend_category_id: Any = None) -> dict[str, Any]:
    """What is left of a cost centre's budget for the fiscal year `on` falls in (FIN-02): the
    year's budget, less what is invoiced so far, less what is ordered and not yet invoiced."""
    _session(db, "budget_position")
    day = as_date(on) or today()
    cal = calendar()
    first, last = cal.bounds("year", day)
    wanted = int(cost_center_id)

    def mine(r: Any) -> bool:
        return get(r, "cost_center_id") == wanted and (spend_category_id is None
                                                       or get(r, "spend_category_id") == int(spend_category_id))
    budget = actual = committed = Decimal(0)
    lines = model("budget_line")
    if lines is not None:
        for line in db.execute(select(lines).where(lines.cost_center_id == wanted)).scalars().all():
            start = get(line, "period_start")
            inside = first <= as_date(start) <= last if start else get(line, "fiscal_year") == cal.fiscal_year(day)
            if inside and (spend_category_id is None or get(line, "spend_category_id") == int(spend_category_id)):
                budget += D(get(line, "amount", 0))
    invoices = model("invoice")
    if invoices is not None and "cost_center_id" in columns("invoice"):
        for inv in db.execute(select(invoices).where(invoices.cost_center_id == wanted)).scalars().all():
            if mine(inv) and get(inv, "status", "") != "rejected" and get(inv, "invoice_date") \
                    and first <= as_date(inv.invoice_date) <= min(day, last):
                actual += D(get(inv, "net_amount", None) or get(inv, "amount", 0))
    orders = model("purchase_order")
    if orders is not None and "cost_center_id" in columns("purchase_order"):
        for po in db.execute(select(orders).where(orders.cost_center_id == wanted)).scalars().all():
            if mine(po) and get(po, "status", "") in OPEN_ORDER:
                committed += max(Decimal(0), D(get(po, "amount", 0)) - D(get(po, "invoiced_amount", 0)))
    p = fin.budget_position(budget, actual, committed, requested)
    centre = db.get(model("cost_center"), wanted) if model("cost_center") is not None else None
    currency = base_currency()
    said = {"ok": f"{money.fmt(p.remaining, currency)} would be left of {money.fmt(p.budget, currency)}",
            "warning": f"This takes {cal.label('year', day)} to {p.utilisation_pct}% of budget: "
                       f"{money.fmt(p.remaining, currency)} would be left",
            "exceeded": (f"This is {money.fmt(-p.remaining, currency)} more than is left: "
                         f"{money.fmt(p.available, currency)} is available of {money.fmt(p.budget, currency)}"
                         if p.available >= 0 else
                         f"The budget of {money.fmt(p.budget, currency)} is already overcommitted by "
                         f"{money.fmt(-p.available, currency)}; this would add {money.fmt(p.requested, currency)}")}[p.status]
    return {"cost_center_id": wanted, "cost_center": get(centre, "name", ""), "fiscal_year": cal.label("year", day),
            "budget": float(p.budget), "actual": float(p.actual), "committed": float(p.committed),
            "requested": float(p.requested), "available": float(p.available), "remaining": float(p.remaining),
            "utilisation_pct": p.utilisation_pct, "status": p.status, "rule": "FIN-02", "message": said}


def check_request(db: Session, requisition: Any) -> dict[str, Any]:
    """What to tell a requester before they submit: who will approve it (PROC-02), whether the
    budget covers it (FIN-02), how many quotes it needs (PROC-10), whether the supplier can be
    ordered from (PROC-09), and whether it looks like part of a split (PROC-11)."""
    _session(db, "check_request")
    req = row(db, "requisition", requisition)
    currency = get(req, "currency", base_currency())
    amount = D(get(req, "amount", 0))
    findings: list[dict[str, Any]] = []

    def say(rule: str, level: str, text: str) -> None:
        findings.append({"rule": rule, "level": level, "message": text})

    approver = fin.approver_for(amount)
    say("PROC-02", "info", f"{money.fmt(amount, currency)} is approved by the {approver.replace('_', ' ')}")
    position = None
    if get(req, "cost_center_id") and model("budget_line") is not None:
        position = budget_position(db, req.cost_center_id, requested=amount, on=get(req, "created_at") or today())
        if position["budget"] > 0:
            stops = position["status"] == "exceeded" and fin.POLICY.budget_control == "block"
            say("FIN-02", {"ok": "ok", "warning": "warn", "exceeded": "down"}[position["status"]],
                position["message"] + (". It cannot be submitted until a budget change is approved" if stops else ""))
    quotes = fin.quotes_needed(amount)
    if quotes["quotes"] > 1:
        say("PROC-10", "info", f"{quotes['quotes']} quotes are needed at this value"
                               + (", and a tender" if quotes["tender"] else "")
                               + ", or a single-source justification")
    supplier = db.get(model("supplier"), req.supplier_id) if model("supplier") is not None and get(req, "supplier_id") else None
    if supplier is not None and str(get(supplier, "status", "")).lower() not in fin.POLICY.orderable:
        say("PROC-09", "down", f"{get(supplier, 'name', 'The supplier')} is "
                               f"{str(get(supplier, 'status', '')).replace('_', ' ')}: it cannot be ordered from yet")
    cls = type(req)
    near = db.execute(select(cls).where(cls.id != req.id)).scalars().all() if get(req, "requester_name") else []
    same = [r for r in near if get(r, "requester_name") == req.requester_name and get(r, "supplier_id") == get(req, "supplier_id")]
    split = fin.split_orders([req, *same]) if get(req, "supplier_id") else []
    if any(req in s["requests"] for s in split):
        say("PROC-11", "warn", "Together with another recent request to the same supplier this is above the first "
                               "approval limit: it may be read as one purchase split in two")
    worst = "down" if any(f["level"] == "down" for f in findings) else "warn" if any(f["level"] == "warn" for f in findings) else "ok"
    return {"requisition_id": req.id, "reference": get(req, "reference", ""), "amount": float(amount), "approver": approver,
            "approval_chain": fin.approval_chain(amount), "quotes": quotes, "budget": position, "level": worst,
            "findings": findings}
