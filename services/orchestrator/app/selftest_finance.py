"""Self-test for the finance overlay: what the platform does with it, and the library inside an application.

No model calls, no internet, no Docker. It composes applications the way a run does (the
scaffold, the enterprise overlay, the finance overlay), merges the standard entities into a
Developer's reply, loads the library's demonstration data, starts the business logic from
the library's domain and checks it with the domain stage's own check, reads the contracts a
Developer is shown, and runs the library's API and operations as the people of the function.

    docker compose exec orchestrator python -m app.selftest_finance

The library's own rule tests (tests/test_finance_library.py) run when pytest is installed,
and the dashboard kit is parsed when node is; both are reported as skipped otherwise. The
kit in a real browser is tools/finance/browse.py.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .config import scaffold_root
from .graph.nodes import domain as domain_stage
from .graph.nodes import scaffold as scaffold_stage
from .workspace import checks as ws_checks
from .workspace import interface as ws_interface
from .workspace import overlays, standards
from .workspace import repo as ws_repo
from .workspace.checks import _table_columns
from .workspace.seeding import fill_required, quality_issues, rows_to_sql, strip_seed_section
from .workspace.seedspec import expand_spec

PASSED: list[str] = []
FAILED: list[str] = []
SKIPPED: list[str] = []
NAMES = ["enterprise", "finance"]
TODAY = "2026-09-25"
HERE = Path(__file__).parent

BRIEF = """Northwind Logistics needs a procure-to-pay workbench. Requesters raise purchase requisitions
against their cost centre's budget; a requisition up to 2,000 is approved by the budget holder, up to
20,000 by the head of department and above that by the CFO. Buyers turn approved requisitions into
purchase orders with approved suppliers. Goods receipts are posted against orders, and supplier invoices
are matched three-way within 1% and 25. Expense claims above 500 need a receipt attached.
Accounts payable proposes a weekly payment run. Contracts are reviewed 90 days before they end."""

# What a Foundation Developer returns under the finance pack: the brief's own entity, and a
# standard one written only to add a column to it.
REPLY = {
    "backend/app/models.py": '''"""ORM models."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Example(Base):
    __tablename__ = "example"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="open")
    owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))


class ExpenseClaim(Base):
    __tablename__ = "expense_claim"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reference: Mapped[str] = mapped_column(String(30))
    claimant_name: Mapped[str] = mapped_column(String(120))
    cost_center_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[float] = mapped_column(Float, default=0)
    has_receipt: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="draft")  # draft|submitted|approved|rejected|paid
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Invoice(Base):
    __tablename__ = "invoice"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    dispute_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
''',
    "db/init.sql": '''-- Schema.

CREATE TABLE IF NOT EXISTS example (
    id          SERIAL PRIMARY KEY,
    label       VARCHAR(200) NOT NULL,
    status      VARCHAR(40) NOT NULL DEFAULT 'open',   -- open|in_progress|review|done
    owner       VARCHAR(120),
    amount      DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS expense_claim (
    id SERIAL PRIMARY KEY,
    reference VARCHAR(30) NOT NULL,
    claimant_name VARCHAR(120) NOT NULL,
    cost_center_id INTEGER NOT NULL,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    has_receipt BOOLEAN DEFAULT FALSE,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',  -- draft|submitted|approved|rejected|paid
    submitted_at TIMESTAMPTZ
);

-- the invoice, with why it is disputed
CREATE TABLE IF NOT EXISTS invoice (
    id SERIAL PRIMARY KEY,
    amount DOUBLE PRECISION NOT NULL DEFAULT 0,
    dispute_reason VARCHAR(300)
);
''',
    "backend/app/schemas.py": '''"""Schemas."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class ExampleCreate(BaseModel):
    label: str
    status: str = "open"
    owner: str | None = None
    amount: float = 0


class ExampleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    status: str
    owner: str | None = None
    amount: float
    created_at: dt.datetime


class ExpenseClaimCreate(BaseModel):
    reference: str
    claimant_name: str
    cost_center_id: int
    amount: float = 0


class ExpenseClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reference: str
    claimant_name: str
    cost_center_id: int
    amount: float
    status: str


class InvoiceCreate(BaseModel):
    amount: float = 0
    dispute_reason: str | None = None


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: float
    dispute_reason: str | None = None
''',
}

SPEC = {"tables": [{"table": "expense_claim", "count": 40, "columns": {
    "reference": {"kind": "sequence", "prefix": "EXP-2026-", "start": 400},
    "claimant_name": {"kind": "person_name"},
    "cost_center_id": {"kind": "ref", "table": "cost_center"},
    "amount": {"kind": "float", "min": 12, "max": 1800, "decimals": 2},
    "has_receipt": {"kind": "bool", "true_share": 0.8},
    "status": {"kind": "choices", "choices": {"draft": 2, "submitted": 4, "approved": 3, "rejected": 1, "paid": 5}},
    "submitted_at": {"kind": "time", "days_back": 60, "only_when": {"column": "status", "in": ["submitted", "approved", "rejected", "paid"]}},
}}]}


def expect(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    print(("  ok   " if condition else "  FAIL ") + label + (f"  -- {detail}" if detail and not condition else ""))


def skip(label: str, why: str) -> None:
    SKIPPED.append(label)
    print(f"  skip {label}  -- {why}")


def compose(root: Path, tables: list[str] | None = None, reply: dict[str, str] | None = None) -> Path:
    """An application as a run has it after the scaffold stage; with `tables`, as after the
    foundation's data model and the library's starting domain."""
    values = {"project_name": "Finance Self-test", "project_slug": "finance-selftest", "description": "A self-test."}
    scaffold_stage.materialise(scaffold_root() / "web-app", root, values)
    for name in NAMES:
        scaffold_stage.materialise(overlays.root(name), root, values, skip=overlays.is_meta)
    if tables is not None:
        files = reply or {rel: (root / rel).read_text(encoding="utf-8") for rel in (standards.MODELS, standards.SQL, standards.SCHEMAS)}
        files[standards.SQL] = strip_seed_section(files[standards.SQL])
        merged, _ = standards.merge(files, tables, overlays.module("finance", "standard"), "finance")
        for rel, body in merged.items():
            (root / rel).write_text(body, encoding="utf-8", newline="\n")
        have = {t: list(cols) for t, cols in _table_columns((root / standards.SQL).read_text(encoding="utf-8")).items()}
        classes = standards.class_names((root / standards.MODELS).read_text(encoding="utf-8"))
        for rel, body in overlays.module("finance", "starter").domain(have, classes).items():
            (root / rel).write_text(body, encoding="utf-8", newline="\n")
    return root


def run(root: Path, *argv: str, env: dict[str, str] | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    full = {**os.environ, "PYTHONPATH": "backend", "DATABASE_URL": "sqlite://", "JOB_SECONDS": "3600",
            "FINANCE_AS_OF": TODAY, "POIESIS_LLM_PROFILE": "local", **(env or {})}
    for key in ("ERP_BASE_URL", "JIRA_BASE_URL", "SMTP_HOST", "FISCAL_YEAR_START_MONTH", "BASE_CURRENCY"):
        full.pop(key, None)
    return subprocess.run([sys.executable, *argv], cwd=root, capture_output=True, text=True, env=full, timeout=timeout)


def domain_report(root: Path) -> dict[str, Any]:
    (root / ".poiesis").mkdir(exist_ok=True)
    (root / ".poiesis" / "domain_check.py").write_text(domain_stage.CHECK_SCRIPT, encoding="utf-8")
    out = run(root, ".poiesis/domain_check.py", env={"PYTHONPATH": ""})
    try:
        # From the file, as the domain stage reads it: the sandbox keeps only the tail of what is
        # printed, and a finance domain describes itself in more than that.
        return json.loads((root / ".poiesis" / "domain_report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": (out.stderr or out.stdout)[-1500:], "problems": [], "rules": [], "workflows": []}


# ---- the overlay, as the platform reads it ----------------------------------------------

def test_overlay(tmp: Path) -> None:
    print("the overlay")
    pack = yaml.safe_load((Path("packs/finance.yaml") if Path("packs/finance.yaml").is_file()
                           else HERE.parent / "packs" / "finance.yaml").read_text(encoding="utf-8"))
    expect("the finance pack lays the enterprise overlay, then the finance one, and builds a domain",
           pack["build"]["overlays"] == NAMES and pack["build"]["domain"] and pack["build"]["foundation"], str(pack["build"]))
    m = overlays.manifest("finance")
    expect("its manifest names what it owns, says and brings",
           m.get("requires") == ["enterprise"] and set(m.get("prompts") or {}) == {"architect", "foundation", "domain", "data", "developer"}
           and all(overlays.module("finance", k) is not None for k in ("standard", "demo", "starter")), str(m)[:300])
    expect("the library and the kit are platform-owned, a story's own files are not",
           overlays.owned("backend/app/finance/rules.py", NAMES) and overlays.owned("frontend/finance.js", NAMES)
           and overlays.owned("backend/app/connectors/erp.py", NAMES) and overlays.owned("backend/app/kernel/auth.py", NAMES)
           and overlays.owned("./tests/test_finance_library.py", NAMES)
           and not overlays.owned("frontend/screens/spend.js", NAMES) and not overlays.owned("backend/app/domain/rules.py", NAMES))
    for slot in ("architect", "foundation", "domain", "data", "developer"):
        text = overlays.prompt(slot, NAMES)
        expect(f"it has something to tell the {slot}", len(text) > 300 and "{{" not in text, text[:120])
    expect("the Developer's note names the kit, the insight API and the operations",
           all(w in overlays.prompt("developer", NAMES) for w in ('import fin from "../finance.js"', "fin.dashboard(", "fin.data(api)",
                                                                   "data.match(", "blueprints")), "")
    expect("without the overlay nothing is added", overlays.prompt("developer", ["enterprise"]) == ""
           and overlays.components(["enterprise"]) == "" and not overlays.standards(["enterprise"]))
    expect("the Architect is told what every application of the pack has", "dashboard kit" in overlays.components(NAMES)
           and "insight API" in overlays.components(NAMES))
    expect("its settings reach a deployed application", set(overlays.settings_prefixes(NAMES)) == {"ERP_", "FISCAL_", "FINANCE_", "BASE_CURRENCY"})
    expect("its worked example is shown to the Developer", overlays.references(NAMES) == [("frontend/screens/example_finance.js", 3400)])
    expect("example screens are told from story screens by name",
           overlays.is_example_screen("example.js") and overlays.is_example_screen("example_finance.js")
           and not overlays.is_example_screen("examples_of_spend.js") and not overlays.is_example_screen("spend.js"))

    root = compose(tmp / "bare")
    files = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    expect("an application gets the library, the kit, the connector and their tests",
           {"backend/app/finance/rules.py", "backend/app/finance/api.py", "backend/app/finance/operations.py",
            "backend/app/finance/demo.py", "backend/app/connectors/erp.py", "frontend/finance.js", "frontend/finance.css",
            "frontend/screens/example_finance.js", "tests/test_finance_library.py", "backend/app/kernel/workflow.py"} <= files,
           str(sorted(f for f in files if "finance" in f))[:400])
    expect("and none of what is about the overlay", not any(f.endswith("overlay.yaml") or f.startswith("prompts/") for f in files),
           str([f for f in files if "overlay" in f or f.startswith("prompts")]))
    expect("nothing is left to fill in", not [f for f in files if f.endswith((".py", ".js", ".css", ".html", ".yml"))
                                              and "{{project_" in (root / f).read_text(encoding="utf-8", errors="replace")])


# ---- standard entities --------------------------------------------------------------------

def test_standards(tmp: Path) -> dict[str, Any]:
    print("standard entities")
    chosen = standards.wanted(BRIEF, NAMES)
    expect("the brief's words say which standard entities it needs, and those bring the ones they refer to",
           chosen == {"finance": ["cost_center", "supplier", "budget_line", "contract", "requisition", "purchase_order",
                                  "goods_receipt", "payment_run", "payment", "invoice"]}, str(chosen))
    expect("a brief about something else needs none", standards.wanted("A helpdesk where agents triage tickets.", NAMES) == {})
    told = standards.describe(chosen)
    expect("the Developer is told the platform writes them, with their columns",
           "THE PLATFORM WRITES THESE TABLES ITSELF" in told and "- invoice (Supplier invoice" in told
           and "match_status? String(30) [matched|price_variance" in told and "- gl_account" not in told, told[:300])

    merged, notes = standards.apply(dict(REPLY), chosen)
    models, sql, schemas = (merged[k] for k in (standards.MODELS, standards.SQL, standards.SCHEMAS))
    tables = _table_columns(sql)
    expect("the reply's own entity stays, the standard ones are added, in all three files",
           set(tables) == {"example", "expense_claim", *chosen["finance"]}
           and set(standards.class_names(models)) == set(tables)
           and all(f"class {n}Create(BaseModel)" in schemas for n in ("ExpenseClaim", "Invoice", "PurchaseOrder", "CostCenter")),
           str(sorted(tables)))
    expect("a standard entity the reply wrote is the platform's, with the reply's own column kept",
           models.count("class Invoice(Base)") == 1 and sql.lower().count("create table if not exists invoice (") == 1
           and "dispute_reason" in tables["invoice"] and {"reference", "supplier_id", "due_date", "match_status"} <= set(tables["invoice"])
           and "dispute_reason: Mapped[str | None]" in models and schemas.count("dispute_reason: str | None = None") == 2
           and any("dispute_reason" in n for n in notes), str(notes))
    expect("required columns are required, optional ones are not",
           tables["invoice"]["supplier_id"] and tables["invoice"]["due_date"] and not tables["invoice"]["dispute_reason"]
           and not tables["invoice"]["purchase_order_id"], str(tables["invoice"]))
    again, _ = standards.apply(dict(merged), chosen)
    expect("merging twice changes nothing", again == merged,
           next((k for k in merged if again[k] != merged[k]), ""))
    expect("the data model has every column the library reads", standards.gaps(tables, NAMES) == [], str(standards.gaps(tables, NAMES)))
    expect("and one that lacks them is told which", "due_date" in " ".join(standards.gaps({"invoice": ["id", "reference"]}, NAMES)))

    root = compose(tmp / "merged", chosen["finance"], dict(REPLY))
    out = run(root, "-c", "from app import models, schemas; from app.db import Base, engine; Base.metadata.create_all(engine()); "
                          "print(sorted(t for t in Base.metadata.tables if not t.startswith('sys_')))")
    expect("the merged models and schemas import, and the tables are created",
           out.returncode == 0 and "'expense_claim'" in out.stdout and "'purchase_order'" in out.stdout, (out.stderr or out.stdout)[-600:])
    return {"chosen": chosen, "tables": tables, "sql": sql, "root": root}


# ---- demonstration data ---------------------------------------------------------------------

def test_data(tmp: Path, made: dict[str, Any]) -> None:
    print("demonstration data")
    tables = made["tables"]
    rows, notes = overlays.demo_rows(tables, today=TODAY, names=NAMES)
    expect("the library brings rows for its entities and leaves the application's own alone",
           set(rows) == set(made["chosen"]["finance"]) and not notes and len(rows["invoice"]) > 300 and len(rows["supplier"]) > 40,
           str({t: len(r) for t, r in rows.items()}) + str(notes))
    expect("a column the application added is there to fill, and a table it lacks is not pointed at",
           all("dispute_reason" not in r for r in rows["invoice"]) and "purchase_order_line" not in rows
           and all(set(r) <= set(tables["invoice"]) for r in rows["invoice"][:50]))
    fill_required(rows, tables)
    sql, problems = rows_to_sql(rows, tables)
    expect("its rows fit the tables: nothing missing, nothing unknown", not problems, str(problems)[:400])
    full, problems, derived = expand_spec(SPEC, tables, preloaded=rows)
    expect("the Data Designer's table refers to the library's rows",
           not problems and len(full["expense_claim"]) == 40 and list(full)[0] == "cost_center"
           and all(1 <= r["cost_center_id"] <= len(rows["cost_center"]) for r in full["expense_claim"]), str(problems)[:300])
    expect("only the spec's rows are checked for variety", quality_issues({"expense_claim": full["expense_claim"]}, [BRIEF], tables, derived) == [],
           str(quality_issues({"expense_claim": full["expense_claim"]}, [BRIEF], tables, derived))[:300])
    _, problems, _ = expand_spec({"tables": [{"table": "supplier", "count": 3, "columns": {"name": {"kind": "company_name"}}}, *SPEC["tables"]]},
                                 tables, preloaded=rows)
    expect("a spec that writes a table the library filled is told to leave it out",
           any("supplier" in p and "leave it out" in p for p in problems), str(problems)[:300])

    seed, problems = rows_to_sql(full, tables)
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(made["sql"].replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY").replace("DEFAULT now()", "DEFAULT CURRENT_TIMESTAMP"))
        db.executescript(seed)
        counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in full}
        orphans = db.execute("SELECT count(*) FROM invoice i LEFT JOIN supplier s ON s.id = i.supplier_id WHERE s.id IS NULL").fetchone()[0]
        paid = db.execute("SELECT count(*) FROM invoice WHERE status = 'paid' AND paid_at IS NULL").fetchone()[0]
        spend = db.execute("SELECT round(sum(net_amount)) FROM invoice WHERE status <> 'rejected' AND invoice_date >= '2026-04-01'").fetchone()[0]
        expect("the rows load as SQL, every invoice has its supplier, every paid one its date",
               not problems and counts == {t: len(r) for t, r in full.items()} and orphans == 0 and paid == 0 and spend > 1_000_000,
               f"{counts} orphans {orphans} unpaid {paid} spend {spend} {problems}")
    finally:
        db.close()
    a, _ = overlays.demo_rows(tables, today=TODAY, names=NAMES)
    expect("the same day gives the same data", json.dumps(a) == json.dumps(rows) or a == overlays.demo_rows(tables, today=TODAY, names=NAMES)[0])
    later, _ = overlays.demo_rows(tables, today="2027-02-10", names=NAMES)
    newest = max(r["invoice_date"] for r in later["invoice"])
    expect("and another day gives data up to that day", "2027-01-20" <= newest <= "2027-02-10", newest)


# ---- the business logic ------------------------------------------------------------------------

def test_domain(tmp: Path, made: dict[str, Any]) -> None:
    print("the business logic to start from")
    root = made["root"]
    report = domain_report(root)
    expect("the library's domain imports and passes the domain stage's check, the application's table included",
           not report["error"] and not report["problems"], (report["error"] or str(report["problems"]))[-600:])
    flows = {w["name"]: w for w in report["workflows"]}
    expect("a lifecycle for every standard record the application has, against its own models",
           set(flows) == {"requisition", "purchase_order", "invoice", "payment_run", "supplier", "contract"}
           and flows["invoice"]["model"] == "Invoice" and [s["key"] for s in flows["invoice"]["states"]][0] == "received",
           str(sorted(flows)))
    submit = next(t for t in flows["requisition"]["transitions"] if t["name"] == "submit")
    expect("a requisition waits as submitted for the approver its amount calls for",
           submit["pending"] == "submitted" and submit["approvers"] == ["budget_holder", "head_of_department", "finance_director", "cfo"]
           and submit["rule"] == "PROC-02", str(submit))
    ids = {r["id"] for r in report["rules"]}
    expect("the library's 22 rules are in the catalogue", {f"FIN-{i:02d}" for i in range(1, 12)} | {f"PROC-{i:02d}" for i in range(1, 12)} <= ids,
           str(sorted(ids)))
    expect("the roles of the function, each with a persona, and the operations stories call",
           {"requester", "buyer", "ap_clerk", "treasury", "cfo", "admin"} <= set(report["roles"])
           and len(report["personas"]) == len(report["roles"])
           and {"match_invoice", "receive_goods", "propose_payment_run", "budget_position", "check_request"} <= set(report["services"]),
           str(report["services"]))

    few = compose(tmp / "few", ["cost_center", "budget_line", "budget_change"])
    small = domain_report(few)
    expect("an application with three of the entities gets their part of it",
           not small["error"] and not small["problems"] and [w["name"] for w in small["workflows"]] == ["budget_change"]
           and set(small["roles"]) == {"budget_holder", "finance_controller", "finance_director", "auditor", "admin"}
           and small["services"] == ["budget_position"], (small["error"] or str(small["problems"]) or str(small["roles"]))[-500:])
    starter = overlays.module("finance", "starter")
    expect("and one with none of them is left to the worked example", starter.domain({"ticket": ["id", "subject"]}, {"ticket": "Ticket"}) == {})

    rid = f"selftest-finance-{os.getpid()}"
    wroot = ws_repo.workspace_path(rid)
    try:
        shutil.copytree(root, wroot, ignore=shutil.ignore_patterns("__pycache__", "*.db"))
        (wroot / ".poiesis").mkdir(exist_ok=True)
        (wroot / ".poiesis" / "domain.json").write_text(json.dumps({"workflows": report["workflows"]}), encoding="utf-8")
        governed = ws_checks.governed_columns(rid)
        expect("the checks know which columns the library's lifecycles govern",
               governed.get("Invoice") == ("status", "invoice") and governed.get("PurchaseOrder") == ("status", "purchase_order"),
               str(governed))
        moves = ws_checks.workflow_transitions(rid)
        expect("and the moves that reach each state", ("match", ["received"], "matched") in moves.get("invoice", []), str(moves.get("invoice"))[:300])
        (wroot / "backend" / "app" / "routers" / "invoices.py").write_text('''from fastapi import APIRouter, Depends
from ..db import get_session
from ..models import Invoice
router = APIRouter()

@router.post("/invoices/{invoice_id}/approve")
def approve(invoice_id: int, db=Depends(get_session)):
    inv = db.get(Invoice, invoice_id)
    inv.status = "approved"
    db.commit()
    return {"ok": True}
''', encoding="utf-8")
        found = ws_checks.enterprise_issues(rid)
        expect("a router that writes an invoice's status directly is flagged, with the move to use",
               any("governs" in f and "invoices.py" in f and "approve" in f for f in found), str(found)[:500])
        (wroot / "backend" / "app" / "routers" / "invoices.py").unlink()

        contract = ws_interface.import_contract(rid)
        expect("the import contract lists the library and the ERP connector",
               "from ..finance import" in contract and "operations" in contract and "analytics" in contract
               and "from ..connectors import" in contract and "erp" in contract.split("from ..connectors import", 1)[1].splitlines()[0],
               contract[-700:])
        routes = {(r["method"], r["path"]) for r in ws_interface.declared_routes(rid)}
        expect("the verified routes list the insight API and the operations",
               {("GET", "/api/finance/kpis"), ("GET", "/api/finance/breakdown"), ("GET", "/api/finance/documents"),
                ("POST", "/api/finance/invoices/{invoice_id}/match"), ("GET", "/api/finance/suppliers/{supplier_id}/scorecard"),
                ("GET", "/api/invoices")} <= routes, str(sorted(p for _, p in routes if "finance" in p))[:500])
        overlays_before = overlays.active
        overlays.active = lambda: NAMES          # the pack of this process may be another
        try:
            shown = ws_interface.reference(rid)
            command = domain_stage.command(rid)
            begun = domain_stage.starter(rid)
        finally:
            overlays.active = overlays_before
        expect("the Developer is shown the finance example beside the scaffold's", "### frontend/screens/example_finance.js" in shown
               and "fin.dashboard(root, ctx, fin.blueprints.executive(" in shown and "### frontend/screens/example.js" in shown, shown[:200])
        expect("the rule tests run with the library's own", "tests/test_rules.py tests/test_finance_library.py" in command, command[-200:])
        expect("the domain stage starts from the library's domain for this application's tables",
               set(begun) == set(domain_stage.FILES) and "register(flows.invoice(Invoice))" in begun["backend/app/domain/workflows.py"]
               and "BudgetChange" not in begun["backend/app/domain/workflows.py"], str(sorted(begun)))
        (wroot / "frontend" / "screens" / "spend.js").write_text(
            'import fin from "../finance.js";\nexport default { title: "Spend", story: "S1", async render(root, ctx) { '
            'await fin.dashboard(root, ctx, fin.blueprints.spend()); } };\n', encoding="utf-8")
        listed = ws_checks.regenerate_registry(rid)
        registry = (wroot / "frontend" / "screens" / "index.js").read_text(encoding="utf-8")
        expect("once a story has a screen, neither example is listed",
               '"spend"' in registry and "example_finance" not in registry and "example.js" not in registry, registry[:300])
        (wroot / "frontend" / "screens" / "spend.js").unlink()
        ws_checks.regenerate_registry(rid)
        registry = (wroot / "frontend" / "screens" / "index.js").read_text(encoding="utf-8")
        expect("until then both are, as examples", registry.count("example: true") == 2 and '"example_finance"' in registry, registry[:400])
    finally:
        shutil.rmtree(wroot, ignore_errors=True)


# ---- the library inside an application -----------------------------------------------------------

def test_library(tmp: Path) -> None:
    print("the library inside an application")
    mod = overlays.module("finance", "standard")
    root = compose(tmp / "whole", list(mod.ORDER))
    for name in ("finance_app_check.py", "finance_sparse_check.py"):
        shutil.copyfile(HERE / "selftest_data" / name, root / name)
    out = run(root, "finance_app_check.py", env={"FIN_DB": str(tmp / "whole.db")})
    lines = [line for line in out.stdout.splitlines() if line.startswith("  FAIL") or " passed, " in line]
    expect("the insight API and the operations, as the people of the function, over the demonstration data",
           out.returncode == 0 and any(" passed, 0 failed" in line for line in lines), "\n".join(lines[-8:]) or (out.stderr or out.stdout)[-1500:])
    for label, tables in (("with every standard entity", None), ("with only invoices and suppliers", ["cost_center", "supplier", "invoice"]),
                          ("with none of them", [])):
        app = root if tables is None else compose(tmp / f"sparse{len(tables)}", tables) if tables else compose(tmp / "sparse-none")
        shutil.copyfile(HERE / "selftest_data" / "finance_sparse_check.py", app / "finance_sparse_check.py")
        got = run(app, "finance_sparse_check.py", env={"FIN_DB": str(tmp / f"sparse-{len(tables or [1])}.db")})
        expect(f"every GET answers without an error {label}", got.returncode == 0 and "0 answered with an error" in got.stdout,
               (got.stdout or got.stderr)[-700:])
    try:
        import pytest  # noqa: F401
    except ImportError:
        skip("the library's rule tests", "pytest is not installed here; the domain stage runs them in its sandbox")
    else:
        got = run(root, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest", "--tb=line",
                  "tests/test_finance_library.py", "tests/test_rules.py")
        tail = (got.stdout or got.stderr).strip().splitlines()[-1:] or [""]
        expect("the library's rule tests pass in the application", got.returncode == 0 and " passed" in tail[0] and "failed" not in tail[0],
               (got.stdout or got.stderr)[-900:])
    node = shutil.which("node")
    if not node:
        skip("the dashboard kit parses and loads", "node is not installed here; the build's frontend check runs it in its sandbox")
    else:
        fe = tmp / "fe"
        shutil.copytree(root / "frontend", fe)
        (fe / "package.json").write_text('{"type":"module"}', encoding="utf-8")
        script = ("const fin = (await import('./finance.js')).default; const s = (await import('./screens/example_finance.js')).default;"
                  "const cal = fin.calendar(4);"
                  "console.log(JSON.stringify({ parts: Object.keys(fin).length, blueprints: Object.keys(fin.blueprints), widgets: Object.keys(fin.WIDGETS),"
                  " screen: [s.title, typeof s.render], money: [fin.money(1234567.5), fin.money(1234567.5, { compact: true }), fin.money(null), fin.money(NaN)],"
                  " fy: [cal.fiscalYear('2026-09-25'), cal.quarter('2026-09-25'), cal.bounds('quarter', '2026-09-25'), cal.label('quarter', '2026-09-25')],"
                  " variance: fin.variance(104999, 100000), date: fin.date('2026-09-25T10:00:00Z'), spec: fin.blueprints.spend({ remove: ['pivot'] }).widgets.length }))")
        got = subprocess.run([node, "--input-type=module", "-e", script], cwd=fe, capture_output=True, text=True, timeout=120)
        try:
            seen = json.loads(got.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            seen = {}
        expect("the dashboard kit loads where there is no page, as the platform's frontend check loads a screen",
               got.returncode == 0 and seen.get("screen") == ["Finance overview", "function"] and len(seen.get("blueprints", [])) == 8
               and len(seen.get("widgets", [])) >= 15, (got.stderr or got.stdout)[-600:])
        expect("it writes amounts, fiscal periods and dates the way the library does",
               seen.get("money") == ["£1,234,567.50", "£1.23M", "—", "—"] and seen.get("date") == "25 Sep 2026"
               and seen.get("fy") == [2027, 2, ["2026-07-01", "2026-09-30"], "Q2 FY2027"]
               and seen.get("variance", {}).get("material") is False and seen.get("spec") == 5, json.dumps(seen)[:500])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="poiesis-finance-"))
    started = dt.datetime.now()
    try:
        test_overlay(tmp)
        made = test_standards(tmp)
        test_data(tmp, made)
        test_domain(tmp, made)
        test_library(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    took = (dt.datetime.now() - started).total_seconds()
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed, {len(SKIPPED)} skipped in {took:.0f}s")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
