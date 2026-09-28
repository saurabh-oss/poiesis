"""What the finance library tells the people who use the application. Written by Poiesis, and read-only.

The application's guide (kernel/guide.py, served at /api/platform/guide and shown on the Guide
screen) is assembled from what the application is: its roles, its people, its lifecycles. A
department library adds what only it knows: the process its records are part of, step by step, and
the numbers the organisation set. Who performs a step is read from the lifecycle the application
registered, so a brief that names its roles differently gets a guide in its own words.

    process(flows)   the steps of purchase to pay, for the records this application has
    numbers()        the limits and tolerances this organisation works to (fin.configure)
    USES             how a screen says which of the library's screens it is
    BOARDS           what each dashboard is for
"""
from __future__ import annotations

from typing import Any

from . import money
from . import rules as fin

from .screens import USES  # noqa: F401 — how a screen says which of the library's screens it is

# step: (key, title, what happens, the record, the moves that are the step, the library screens that
#        serve it, the rules that decide it, how it is done, what it leaves behind)
STEPS: list[dict[str, Any]] = [
    {"key": "request", "title": "Raise a requisition", "entity": "requisition", "moves": ["submit"],
     "uses": ["worklist:requisitions"], "rules": ["PROC-02", "FIN-02", "PROC-10", "PROC-11"],
     "what": "Someone who needs something says what, how much and for which cost centre.",
     "how": ["Choose New requisition and say what is needed, the amount and the cost centre.",
             "As you type, the form shows who will have to approve it and what it leaves of the year's budget.",
             "Save it as a draft. Open it to see what the rules say: quotes needed, a supplier that cannot be ordered "
             "from, a request that looks like one purchase split in two.",
             "Submit it. It waits for its approver, and you are told when it is decided."],
     "leaves": "A requisition waiting for approval"},
    {"key": "approve", "title": "Approve or reject it", "entity": "requisition", "moves": ["submit"], "decides": True,
     "uses": ["worklist:approvals"], "rules": ["PROC-02", "FIN-01", "WF-02"],
     "what": "The person the amount calls for decides. Nobody decides their own request.",
     "how": ["What waits for you is listed oldest first, with its value.",
             "Open a request to see who asked and why, what it leaves of the budget, and what the rules flagged.",
             "Approve it, or reject it with the reason: the requester is told either way, and can revise a rejected request."],
     "leaves": "An approved requisition"},
    {"key": "order", "title": "Raise and send the order", "entity": "purchase_order", "moves": ["release", "send"],
     "uses": ["worklist:ordering"], "rules": ["PROC-09", "PROC-02"],
     "what": "A buyer turns the approved request into a purchase order with an approved supplier, and sends it.",
     "how": ["Approved requisitions wait under To order. Choose Raise the order and the supplier.",
             "Only an approved or active supplier can be ordered from. The order is approved as its requisition was.",
             "Under To send, send it: it goes to the supplier and is created in the ERP."],
     "leaves": "A purchase order with the supplier, and a commitment against the budget"},
    {"key": "receive", "title": "Receive the goods", "entity": "purchase_order", "moves": ["receive", "receive_part"],
     "uses": ["worklist:receiving"], "rules": ["PROC-01"],
     "what": "Whoever takes delivery records what arrived, in part or in full.",
     "how": ["Orders on their way are under To receive; the ones past their date under Late.",
             "Choose Receive and confirm the value that arrived. What is still to come is offered.",
             "A part delivery keeps the order open for the rest."],
     "leaves": "A goods receipt; the order is received, or partly received"},
    {"key": "match", "title": "Match the invoice", "entity": "invoice", "moves": ["match", "flag", "resolve"],
     "uses": ["worklist:invoices"], "rules": ["PROC-01", "PROC-03", "PROC-06"],
     "what": "Accounts payable sets the supplier's invoice against the order and what was received.",
     "how": ["Invoices that arrived are under To match. Choose Match to see what matching would find.",
             "Within the tolerance it is matched. Otherwise it is held as an exception with the reason: a price or "
             "quantity variance, no receipt, no order, a possible duplicate.",
             "A held invoice is resolved with a reason once the difference is explained, or rejected."],
     "leaves": "A matched invoice, or one held with its reason"},
    {"key": "approve_invoice", "title": "Approve it for payment", "entity": "invoice", "moves": ["approve"], "decides": True,
     "uses": ["worklist:approvals", "worklist:invoices"], "rules": ["PROC-02", "FIN-01"],
     "what": "A matched invoice is approved for payment by the person its amount calls for.",
     "how": ["Accounts payable asks for the approval from the matched invoice.",
             "The approver decides it in the approval queue, as a requisition is decided."],
     "leaves": "An invoice approved to pay"},
    {"key": "pay", "title": "Pay", "entity": "payment_run", "moves": ["approve", "release", "complete"],
     "uses": ["worklist:paymentRuns"], "rules": ["FIN-03", "FIN-04", "FIN-01"],
     "what": "Approved invoices are gathered into a payment run, approved, and released to the bank.",
     "how": ["Due to pay lists what a run proposed now would pay, with the discounts worth taking.",
             "Propose a payment run for what is due by a date. It holds one payment per supplier.",
             "The run is approved by someone other than its proposer, then released."],
     "leaves": "Paid invoices, and payments sent"},
]

ALONGSIDE: list[dict[str, Any]] = [
    {"key": "suppliers", "title": "Suppliers", "entity": "supplier", "moves": ["submit", "activate", "suspend"],
     "uses": ["worklist:suppliers", "dashboard:suppliers"], "rules": ["PROC-09", "PROC-05"],
     "what": "A supplier is reviewed and approved before anything can be ordered from it, and can be suspended."},
    {"key": "contracts", "title": "Contracts", "entity": "contract", "moves": ["sign", "renew", "terminate"],
     "uses": ["worklist:contracts"], "rules": ["PROC-07"],
     "what": "A contract is decided on before its notice date: renewed, renegotiated or ended."},
    {"key": "budget", "title": "The budget", "entity": "budget_line", "moves": [],
     "uses": ["dashboard:budget", "dashboard:executive"], "rules": ["FIN-02", "FIN-07"],
     "what": "Budget holders see what is spent, what is committed and what is left, for the period and for the year."},
]

BOARDS: dict[str, str] = {
    "executive": "The figures that matter, the budget, what is owed and who the money goes to.",
    "spend": "Spend by time, category, supplier and cost centre, down to the invoice.",
    "budget": "Who is over budget, what is left of the year, and where the variance comes from.",
    "payables": "What is owed and overdue, what is held, how quickly invoices are approved and paid.",
    "procureToPay": "How requests become orders, receipts, invoices and payments, and where they wait.",
    "suppliers": "Supplier concentration, risk, delivery and the contracts coming up.",
    "controls": "What the rules found: duplicates, splits, invoices with no order, unapproved suppliers.",
    "savings": "What procurement found and what has landed.",
}
WORKLISTS: dict[str, str] = {
    "requisitions": "Raise a requisition, submit it and follow it to the order.",
    "approvals": "What waits for a decision, with the budget and the rules beside it.",
    "ordering": "Approved requests to turn into orders, orders to send, orders with suppliers.",
    "receiving": "What is expected, what is late, what has arrived.",
    "invoices": "Invoices to match, held, to approve and to pay.",
    "paymentRuns": "What is due, a run proposed from it, and the run's way to the bank.",
    "suppliers": "Suppliers in onboarding, approved, suspended.",
    "contracts": "Contracts to decide on, in force, in negotiation, ended.",
}


def _of(flow: dict[str, Any] | None, moves: list[str], decides: bool = False) -> tuple[list[str], list[str]]:
    """(the roles that make these moves, the roles that approve them), in the order they appear."""
    does: list[str] = []
    approves: list[str] = []
    for t in (flow or {}).get("transitions", []):
        if t.get("name") not in moves:
            continue
        for role in t.get("approvers") or []:
            if role not in approves:
                approves.append(role)
        if not decides:
            for role in t.get("roles") or []:
                if role not in does:
                    does.append(role)
    return (approves, []) if decides else (does, approves)


def _step(item: dict[str, Any], flows: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    flow = flows.get(item["entity"])
    if item.get("moves") and flow is None:
        return None            # the application has no such record: the step is not part of it
    roles, approvers = _of(flow, item.get("moves", []), bool(item.get("decides")))
    if item.get("decides") and not roles:
        return None            # nothing about this record waits for anyone's approval
    return {"key": item["key"], "title": item["title"], "what": item["what"], "entity": item["entity"],
            "roles": roles, "approvers": approvers, "uses": list(item.get("uses", [])), "rules": list(item.get("rules", [])),
            "how": list(item.get("how", [])), "leaves": item.get("leaves", ""), "decides": bool(item.get("decides"))}


def process(flows: dict[str, dict[str, Any]], tables: set[str] | None = None) -> list[dict[str, Any]]:
    """Purchase to pay for the records this application has. `flows` is each registered lifecycle,
    described, by the record it governs; `tables` the tables the application has."""
    steps = [s for s in (_step(item, flows) for item in STEPS) if s]
    beside = []
    for item in ALONGSIDE:
        if tables is not None and item["entity"] not in tables:
            continue
        roles, approvers = _of(flows.get(item["entity"]), item.get("moves", []))
        beside.append({"key": item["key"], "title": item["title"], "what": item["what"], "entity": item["entity"],
                       "roles": roles, "approvers": approvers, "uses": list(item["uses"]), "rules": list(item["rules"])})
    if not steps:
        return []
    return [{"key": "purchase_to_pay", "title": "Purchase to pay", "library": "finance",
             "about": "From someone needing something to the supplier being paid. Each step is a different person's: "
                      "requesting, approving, ordering, receiving, matching and paying are kept apart.",
             "steps": steps, "alongside": beside}]


def screens() -> dict[str, str]:
    """What each of the library's screens is for, by how a screen names it (USES)."""
    return {**{f"worklist:{k}": v for k, v in WORKLISTS.items()}, **{f"dashboard:{k}": v for k, v in BOARDS.items()}}


def numbers(roles: dict[str, str] | None = None, currency: str = "") -> list[dict[str, Any]]:
    """The numbers this organisation set (fin.configure), in words."""
    import os
    p = fin.POLICY
    unit = (currency or os.getenv("BASE_CURRENCY", "GBP") or "GBP").upper()
    names = roles or {}

    def amount(value: Any) -> str:
        return money.fmt(value, unit).replace(".00", "")

    def role(key: str) -> str:
        return names.get(key, str(key).replace("_", " ").capitalize())
    out: list[dict[str, Any]] = []
    below = None
    limits = []
    for limit, key in p.doa:
        limits.append(f"{role(key)}: " + (f"up to {amount(limit)}" if limit is not None
                                          else (f"above {amount(below)}" if below is not None else "any amount")))
        below = limit if limit is not None else below
    out.append({"key": "doa", "label": "Who approves", "value": "; ".join(limits), "rule": "PROC-02"})
    t = p.tolerance
    out.append({"key": "tolerance", "label": "An invoice still matches", "rule": "PROC-01",
                "value": f"within {t.price_pct:g}% of what was received, and {amount(t.amount_abs)} at most"})
    out.append({"key": "po_required_above", "label": "An invoice must name a purchase order", "rule": "PROC-06",
                "value": f"above {amount(p.po_required_above)}"
                         + (", unless its category is " + ", ".join(str(c) for c in p.po_exempt_categories)
                            if p.po_exempt_categories else "")})
    out.append({"key": "budget", "label": "The budget", "rule": "FIN-02",
                "value": f"warns at {p.budget_warning_pct:g}% of the year's budget; above 100% a request "
                         + ("cannot be submitted until a budget change is approved" if p.budget_control == "block"
                            else "is flagged to its approver")})
    quotes = []
    floor = None
    for limit, count, tender in p.quote_bands:
        if count > 1 or tender:
            quotes.append((f"above {amount(floor)}" if floor is not None else "any amount")
                          + f": {count} quotes" + (" and a tender" if tender else ""))
        floor = limit
    if quotes:
        out.append({"key": "quotes", "label": "Quotes needed", "value": "; ".join(quotes), "rule": "PROC-10"})
    out.append({"key": "waiting", "label": "How long a decision may wait", "rule": "",
                "value": f"an approval {p.approval_hours:g} hours, a held invoice {p.exception_hours:g} hours"
                         + (f", then {role(p.escalate_to)} is told" if p.escalate_to else "")})
    return out
