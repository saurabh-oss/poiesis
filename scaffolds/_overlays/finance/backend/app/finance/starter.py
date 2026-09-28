"""A finance domain to start from. Written by Poiesis, and read-only.

Given the tables a data model has, this writes the business logic layer every finance
application begins with: the roles of the function and a persona for each, permissions
over the tables that exist, the library's lifecycle for every standard record, the
library's rules, and the operations stories call. It imports and passes its checks as
written; the application's own rules, from its brief, are then added to it.

    files = starter.domain({"invoice": ["id", "reference", …], "supplier": […]},
                           {"invoice": "Invoice", "supplier": "Supplier"})
    files["backend/app/domain/workflows.py"]    ->    the text of the file

The platform calls it after the data model is written and before the business logic is
designed. It depends on nothing but the standard library and the two modules beside it.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

try:
    from . import personas, standard
except ImportError:  # loaded on its own, from its directory
    import personas  # type: ignore[no-redef]
    import standard  # type: ignore[no-redef]

# The roles a record brings with it: who raises it, who moves it, who approves it.
ROLES_FOR: dict[str, tuple[str, ...]] = {
    "requisition": ("requester", "budget_holder", "head_of_department", "buyer", "finance_director", "cfo"),
    "purchase_order": ("buyer", "procurement_manager", "requester", "budget_holder", "head_of_department",
                       "finance_director", "cfo"),
    "goods_receipt": ("requester",),
    "invoice": ("ap_clerk", "budget_holder", "finance_controller"),
    "payment_run": ("ap_clerk", "treasury", "finance_controller"),
    "payment": ("treasury", "ap_clerk"),
    "supplier": ("buyer", "procurement_manager"),
    "contract": ("buyer", "procurement_manager"),
    "savings_initiative": ("buyer", "procurement_manager"),
    "budget_line": ("budget_holder", "finance_controller"),
    "budget_change": ("budget_holder", "finance_controller"),
}
ALWAYS = ("finance_director", "auditor", "admin")
# What a lifecycle cannot do without: its status, and the amount an approval is decided on.
NEEDS: dict[str, tuple[str, ...]] = {
    "requisition": ("status", "amount"), "purchase_order": ("status", "amount"), "invoice": ("status", "amount"),
    "payment_run": ("status",), "supplier": ("status",), "contract": ("status", "value"), "budget_change": ("status",),
}
PLATFORM = ("audit", "rules", "integrations", "users", "*")
FILES = ("backend/app/domain/policy.py", "backend/app/domain/rules.py", "backend/app/domain/workflows.py",
         "backend/app/domain/services.py", "tests/test_rules.py")


def lifecycles(tables: dict[str, Iterable[str]]) -> list[str]:
    """The standard records among `tables` that can have the library's lifecycle."""
    have = {str(t).lower(): {str(c).lower() for c in cols} for t, cols in tables.items()}
    return [name for name, needs in NEEDS.items() if name in have and set(needs) <= have[name]]


def roles(tables: dict[str, Iterable[str]]) -> dict[str, str]:
    have = {str(t).lower() for t in tables}
    wanted = set(ALWAYS)
    for table, names in ROLES_FOR.items():
        if table in have:
            wanted |= set(names)
    return {k: v for k, v in personas.ROLES.items() if k in wanted}


def permissions(role_names: Iterable[str], tables: dict[str, Iterable[str]]) -> dict[str, list[str]]:
    """The library's grants, kept to the tables this application has."""
    have = {str(t).lower() for t in tables}
    out = {}
    for role, grants in personas.permissions(role_names).items():
        out[role] = [g for g in grants if g == "*" or g.split(":", 1)[0] in have or g.split(":", 1)[0] in PLATFORM]
    return out


def _literal(value: Any, indent: int = 0) -> str:
    """Python source for plain data, one entry a line, double-quoted."""
    pad, inner = " " * indent, " " * (indent + 4)
    if isinstance(value, dict):
        if not value:
            return "{}"
        rows = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {_literal(v, indent + 4)}," for k, v in value.items()]
        return "{\n" + "\n".join(rows) + f"\n{pad}}}"
    if isinstance(value, (list, tuple)):
        if all(not isinstance(v, (dict, list, tuple)) for v in value):
            line = "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
            if len(line) + indent <= 112:
                return line
            rows, row = [], inner
            for v in value:
                piece = json.dumps(v, ensure_ascii=False) + ", "
                if len(row) + len(piece) > 112:
                    rows.append(row.rstrip())
                    row = inner
                row += piece
            rows.append(row.rstrip())
            return "[\n" + "\n".join(rows) + f"\n{pad}]"
        return "[\n" + "\n".join(f"{inner}{_literal(v, indent + 4)}," for v in value) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def _person(p: dict[str, Any]) -> str:
    return "{" + ", ".join(f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in p.items()) + "}"


def policy(tables: dict[str, Iterable[str]]) -> str:
    chosen = roles(tables)
    people = personas.people(chosen)
    grants = permissions(chosen, tables)
    return (
        '"""Who may do what. It starts from the finance library\'s roles, personas and segregation of duties\n'
        "(backend/app/finance/personas.py): requesting, approving, ordering, receiving, matching and paying are\n"
        "different people. Change it to the roles the brief names.\n\n"
        "Permissions are `<table>:<action>`: read, create, update, delete for the generic data API; a\n"
        "transition's name for a workflow. `<table>:*` is every action on it, `*:read` reading everything.\n"
        '"""\n\n'
        f"ROLES = {_literal(chosen)}\n\n"
        "# Offered on the sign-in screen, one click each while AUTH_PERSONAS is on.\n"
        "PERSONAS = [\n" + "\n".join(f"    {_person(p)}," for p in people) + "\n]\n\n"
        f"PERMISSIONS = {_literal(grants)}\n\n"
        "# Which roles see which screen (screen id -> roles). Screens not listed are for everyone.\n"
        "SCREENS: dict[str, list[str]] = {}\n\n"
        "# Which notification kinds also go out through connectors (in-app always happens).\n"
        f"CHANNELS = {_literal(personas.CHANNELS)}\n"
    )


def workflows(tables: dict[str, Iterable[str]], classes: dict[str, str]) -> str:
    flows = [name for name in lifecycles(tables) if classes.get(name)]
    needed = sorted({classes[name] for name in flows}
                    | ({classes["supplier"]} if "purchase_order" in flows and classes.get("supplier") else set()))
    lines = [
        '"""Each record\'s lifecycle, from the finance library (backend/app/finance/workflows.py).',
        "",
        "A factory takes the application's model and returns the lifecycle: who may move the record, which",
        "moves wait for an approval and whose, what a refusal does. Approval by amount follows the delegation",
        "of authority set in rules.py (`fin.configure(doa=…)`). Say what else the brief says differently by",
        "passing it: the roles (`requester=(\"employee\",)`, `buyer=(\"procurement_officer\",)`), one approver",
        "whatever the amount (`doa=\"finance_controller\"`), the hours an approval may wait (`approval_hours=24`),",
        "who is told when it waits too long (`escalate_to=\"head_of_department\"`), and what else a move does",
        "(`effects={\"approve\": (fn,)}`). A record the library has no lifecycle for gets its own",
        "`Workflow(...)`, registered the same way.",
        '"""',
        "from ..finance import workflows as flows",
        "from ..kernel import register",
    ]
    if needed:
        lines.append(f"from ..models import {', '.join(needed)}")
    lines.append("")
    for name in flows:
        extra = f", supplier_model={classes['supplier']}" if name == "purchase_order" and classes.get("supplier") else ""
        lines.append(f"{name.upper()} = register(flows.{name}({classes[name]}{extra}))")
    if not flows:
        lines.append("# No standard record with a status here yet: register the application's own lifecycles below.")
    return "\n".join(lines) + "\n"


RULES_HEAD = '''"""Every business rule, once.

The finance library's rules are registered by importing it (backend/app/finance/rules.py: FIN-01 to
FIN-11, PROC-01 to PROC-11), each with its tests in tests/test_finance_library.py. The numbers this
organisation works to are set once, below, from its brief; the library's rules, lifecycles, operations
and dashboards all read them from there. The rules the brief states follow, under the brief's own ids:

    @rule("BR-01", "A requisition is approved by amount", source="BRD 4", kind="authorisation")
    def approver(requisition) -> str:
        return fin.approver_for(getattr(requisition, "amount", 0))          # by the matrix configured below

    @rule("BR-05", "An invoice matches within 1% and 25", source="BRD 4", kind="validation")
    def match(order, receipts, invoice):
        return fin.three_way_match(order, receipts, invoice)                # within the tolerance configured below
"""
from ..finance import money, periods  # noqa: F401 — amounts and the fiscal calendar
from ..finance import rules as fin  # importing it registers the library's rules
from ..kernel import check, rule  # noqa: F401

# The numbers this organisation works to. Change each to what the brief states, and name the brief's rule.
fin.configure(
'''

SETTINGS = (
    ("doa", ("requisition", "purchase_order"),
     '[(5_000, "budget_holder"), (25_000, "head_of_department"), (100_000, "finance_director"), (None, "cfo")]',
     "who approves up to which amount"),
    ("tolerance", ("invoice",), "fin.Tolerance(price_pct=2, quantity_pct=0, amount_abs=50)",
     "an invoice still matches within 2% and 50"),
    ("po_required_above", ("invoice",), "1_000", "an invoice above this must name a purchase order"),
    ("budget_warning_pct", ("budget_line",), "90", "the share of the year's budget at which a request warns"),
    ("budget_control", ("budget_line",), '"warn"', 'above the year\'s budget a request is flagged ("warn") or cannot be submitted ("block")'),
    ("material_pct", ("budget_line",), "5", "a variance of this share of budget, and at least 1,000, is material"),
    ("expiring_days", ("contract",), "90", "a contract is flagged this many days before it ends"),
    ("approval_hours", ("requisition", "purchase_order"), "48", "an approval may wait this long before it is escalated"),
    ("exception_hours", ("invoice",), "72", "a held invoice may wait this long before it is escalated"),
    ("escalate_to", ("requisition", "purchase_order", "invoice"), '"finance_director"',
     "the role told when an approval or an exception waits too long"),
)


def rules(tables: dict[str, Iterable[str]]) -> str:
    have = {str(t).lower() for t in tables}
    lines = [f"    # {about}\n    {name}={value}," for name, needs, value, about in SETTINGS if have & set(needs)]
    return RULES_HEAD + "\n".join(lines) + ("\n" if lines else "") + ")\n"


SERVICES_HEAD = '''"""Operations over the database that stories call. The library's operations
(backend/app/finance/operations.py) do the reading, apply the rule, move the record through its
workflow and write the audit trail; a story adds its own here, calling the rules, never restating them.
"""
from sqlalchemy.orm import Session

from ..finance import operations as ops
'''

SERVICES = {
    "invoice": '''

def match_invoice(db: Session, invoice_id: int) -> dict:
    """Three-way match, duplicates and no order, no pay; moves the invoice to matched or to exception."""
    return ops.match_invoice(db, invoice_id)
''',
    "purchase_order": '''

def receive_goods(db: Session, order_id: int, amount: float, received_by: str = "") -> dict:
    """Post a receipt against an order and move the order to partly received or received."""
    return ops.receive_goods(db, order_id, amount, received_by=received_by)
''',
    "payment_run": '''

def propose_payment_run(db: Session, due_by: str | None = None) -> dict:
    """Gather the approved invoices that are due into a proposed run, one payment per supplier."""
    return ops.propose_payment_run(db, due_by=due_by)
''',
    "budget_line": '''

def budget_position(db: Session, cost_center_id: int, requested: float = 0) -> dict:
    """What is left of a cost centre's budget for the year, and what a request would leave (FIN-02)."""
    return ops.budget_position(db, cost_center_id, requested=requested)
''',
    "requisition": '''

def check_request(db: Session, requisition_id: int) -> dict:
    """What to tell a requester before they submit: approver, budget, quotes, supplier, splits."""
    return ops.check_request(db, requisition_id)
''',
}

TESTS = '''"""Tests of the rules the brief states, named after the rule they prove (test_br_03_…).
The finance library's own rules are proven in tests/test_finance_library.py, which runs with these."""
from app.domain import rules  # noqa: F401 — importing the domain registers every rule
from app.kernel.rules import RULES


def test_the_library_rules_are_registered():
    assert {"FIN-01", "FIN-02", "PROC-01", "PROC-02", "PROC-03"} <= set(RULES)
'''


def services(tables: dict[str, Iterable[str]]) -> str:
    have = {str(t).lower() for t in tables}
    wanted = [k for k in SERVICES if k in have and (k != "payment_run" or {"payment", "invoice"} <= have)]
    return SERVICES_HEAD + "".join(SERVICES[k] for k in wanted)


def domain(tables: dict[str, Iterable[str]], classes: dict[str, str]) -> dict[str, str]:
    """The five files of a finance domain for these tables; {} when none of them is a standard entity."""
    have = {str(t).lower() for t in tables}
    if not have & set(standard.ENTITIES):
        return {}
    return {"backend/app/domain/policy.py": policy(tables), "backend/app/domain/rules.py": rules(tables),
            "backend/app/domain/workflows.py": workflows(tables, classes),
            "backend/app/domain/services.py": services(tables), "tests/test_rules.py": TESTS}
