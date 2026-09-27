"""The standard entities of finance and procurement. Written by Poiesis, and read-only.

One definition, used four ways: the Foundation Developer is shown it, so a purchase
order is called `purchase_order` and its total `amount` in every application; the
platform checks a data model against it; `demo.py` fills these tables with a
coherent year of demonstration data; and the analytics and the dashboard kit read
these column names without being told.

An application uses the entities its brief needs and adds columns of its own. Nothing
here is imported by the application at run time except by `demo.py`; it depends on
nothing but the standard library, so the platform can read it from the template.

A column is (name, type, required, note). Types: str:<n>, text, int, float, money
(stored as DOUBLE PRECISION, computed with `finance.money`), bool, date, datetime,
ref:<table> (an INTEGER named <table>_id unless the column says otherwise).
`core` columns are the ones the library's data, analytics and workflows rely on.
"""
from __future__ import annotations

from typing import Any

Column = tuple[str, str, bool, str]

STATES: dict[str, list[str]] = {
    "requisition": ["draft", "submitted", "approved", "rejected", "ordered", "cancelled"],
    "purchase_order": ["draft", "pending_approval", "approved", "sent", "partially_received", "received",
                       "closed", "cancelled"],
    "invoice": ["received", "matched", "exception", "approved", "scheduled", "paid", "rejected"],
    "payment_run": ["proposed", "approved", "released", "completed"],
    "payment": ["proposed", "approved", "released", "completed", "failed"],
    "supplier": ["prospective", "under_review", "approved", "active", "suspended", "retired"],
    "contract": ["draft", "in_negotiation", "signed", "active", "expiring", "expired", "terminated"],
    "budget_change": ["proposed", "approved", "rejected", "applied"],
    "savings_initiative": ["identified", "in_progress", "realised", "cancelled"],
}
MATCH_STATES = ["matched", "price_variance", "quantity_variance", "no_po", "no_receipt", "duplicate_suspect"]


def _states(entity: str) -> str:
    return "|".join(STATES[entity])


ENTITIES: dict[str, dict[str, Any]] = {
    "cost_center": {
        "title": "Cost centre", "about": "Who spends: a department or project with a budget and an owner",
        "core": ["code", "name"],
        "columns": [
            ("code", "str:20", True, "CC-1200"), ("name", "str:120", True, ""),
            ("department", "str:80", False, ""), ("owner_name", "str:120", False, "the budget holder"),
            ("region", "str:40", False, ""), ("is_active", "bool", False, ""),
        ]},
    "gl_account": {
        "title": "GL account", "about": "Where spend is booked in the general ledger",
        "core": ["code", "name"],
        "columns": [
            ("code", "str:20", True, "6100"), ("name", "str:120", True, ""),
            ("account_type", "str:20", False, "expense|capex|revenue|liability"),
        ]},
    "spend_category": {
        "title": "Spend category", "about": "What is bought: the category taxonomy, two levels",
        "core": ["code", "name", "family"],
        "columns": [
            ("code", "str:20", True, "IT-SW"), ("name", "str:120", True, "Software & SaaS"),
            ("family", "str:80", True, "level 1: IT, Facilities, Professional services…"),
            ("is_direct", "bool", False, "direct (goes into what is sold) or indirect"),
            ("manager_name", "str:120", False, "the category manager"),
        ]},
    "supplier": {
        "title": "Supplier", "about": "Who is bought from, with status, risk and performance",
        "core": ["code", "name", "status"],
        "columns": [
            ("code", "str:20", True, "SUP-00417"), ("name", "str:200", True, ""),
            ("spend_category_id", "ref:spend_category", False, "its main category"),
            ("country", "str:60", False, ""), ("city", "str:80", False, ""),
            ("status", "str:30", True, _states("supplier")),
            ("risk_rating", "str:10", False, "low|medium|high"), ("risk_score", "float", False, "0-100, PROC-05"),
            ("payment_terms", "str:20", False, "NET30|NET45|NET60|2/10NET30|EOM30"),
            ("currency", "str:3", False, "GBP"), ("is_preferred", "bool", False, ""),
            ("is_contracted", "bool", False, "has an active contract"),
            ("otif_pct", "float", False, "on time, in full: 0-100"), ("quality_pct", "float", False, "0-100"),
            ("tax_id", "str:40", False, ""), ("email", "str:200", False, ""),
            ("onboarded_at", "date", False, ""),
        ]},
    "budget_line": {
        "title": "Budget line", "about": "The budget of one cost centre and category family for one fiscal period",
        "core": ["fiscal_year", "period", "cost_center_id", "amount"],
        "columns": [
            ("fiscal_year", "int", True, "the year the fiscal year ends in"), ("period", "int", True, "1-12 within it"),
            ("period_start", "date", False, "first day of the period"),
            ("cost_center_id", "ref:cost_center", True, ""), ("spend_category_id", "ref:spend_category", False, ""),
            ("gl_account_id", "ref:gl_account", False, ""),
            ("amount", "money", True, "budget for the period"), ("currency", "str:3", False, "GBP"),
        ]},
    "requisition": {
        "title": "Purchase requisition", "about": "A request to buy, approved under the delegation of authority",
        "core": ["reference", "amount", "status", "cost_center_id", "created_at"],
        "columns": [
            ("reference", "str:30", True, "PR-104512"), ("title", "str:200", True, ""),
            ("justification", "text", False, ""),
            ("requester_name", "str:120", True, ""), ("cost_center_id", "ref:cost_center", True, ""),
            ("spend_category_id", "ref:spend_category", False, ""), ("supplier_id", "ref:supplier", False, "suggested"),
            ("amount", "money", True, ""), ("currency", "str:3", False, "GBP"),
            ("status", "str:30", True, _states("requisition")),
            ("needed_by", "date", False, ""), ("created_at", "datetime", True, ""),
            ("submitted_at", "datetime", False, ""), ("approved_at", "datetime", False, ""),
            ("approver_name", "str:120", False, ""), ("purchase_order_id", "ref:purchase_order", False, ""),
        ]},
    "purchase_order": {
        "title": "Purchase order", "about": "The commitment to a supplier",
        "core": ["reference", "supplier_id", "amount", "status", "order_date", "cost_center_id"],
        "columns": [
            ("reference", "str:30", True, "PO-4500012345"), ("supplier_id", "ref:supplier", True, ""),
            ("requisition_id", "ref:requisition", False, ""), ("contract_id", "ref:contract", False, ""),
            ("cost_center_id", "ref:cost_center", True, ""), ("spend_category_id", "ref:spend_category", False, ""),
            ("buyer_name", "str:120", False, ""), ("status", "str:30", True, _states("purchase_order")),
            ("amount", "money", True, "order total, net"), ("currency", "str:3", False, "GBP"),
            ("received_amount", "money", False, "value receipted so far"),
            ("invoiced_amount", "money", False, "value invoiced so far"),
            ("order_date", "date", True, ""), ("expected_delivery", "date", False, ""),
            ("delivered_at", "date", False, ""), ("payment_terms", "str:20", False, ""),
            ("created_at", "datetime", True, ""),
        ]},
    "purchase_order_line": {
        "title": "Purchase order line", "about": "One item of an order: quantity, price, what was received and invoiced",
        "core": ["purchase_order_id", "quantity", "unit_price", "amount"],
        "columns": [
            ("purchase_order_id", "ref:purchase_order", True, ""), ("line_no", "int", True, ""),
            ("description", "str:300", True, ""), ("quantity", "float", True, ""), ("unit", "str:20", False, "each, hour, day, licence, tonne…"),
            ("unit_price", "money", True, ""), ("standard_price", "money", False, "the baseline for purchase price variance"),
            ("amount", "money", True, "quantity × unit price"),
            ("received_quantity", "float", False, ""), ("invoiced_quantity", "float", False, ""),
            ("spend_category_id", "ref:spend_category", False, ""), ("gl_account_id", "ref:gl_account", False, ""),
        ]},
    "goods_receipt": {
        "title": "Goods receipt", "about": "What arrived against an order, and whether on time and in full",
        "core": ["purchase_order_id", "received_at", "amount"],
        "columns": [
            ("reference", "str:30", True, "GR-5000123"), ("purchase_order_id", "ref:purchase_order", True, ""),
            ("received_by", "str:120", False, ""), ("received_at", "datetime", True, ""),
            ("quantity", "float", False, ""), ("amount", "money", True, "value receipted"),
            ("status", "str:20", False, "posted|reversed"),
            ("on_time", "bool", False, ""), ("in_full", "bool", False, ""), ("quality_ok", "bool", False, ""),
        ]},
    "invoice": {
        "title": "Supplier invoice", "about": "What the supplier asks to be paid, matched to the order and the receipt",
        "core": ["reference", "supplier_id", "amount", "status", "invoice_date", "due_date"],
        "columns": [
            ("reference", "str:30", True, "INV-260914-0042"), ("supplier_invoice_number", "str:60", True, "the supplier's own number"),
            ("supplier_id", "ref:supplier", True, ""), ("purchase_order_id", "ref:purchase_order", False, ""),
            ("cost_center_id", "ref:cost_center", False, ""), ("spend_category_id", "ref:spend_category", False, ""),
            ("net_amount", "money", True, ""), ("tax_amount", "money", False, ""),
            ("amount", "money", True, "gross: net + tax"), ("currency", "str:3", False, "GBP"),
            ("invoice_date", "date", True, ""), ("received_at", "datetime", False, ""), ("due_date", "date", True, ""),
            ("payment_terms", "str:20", False, ""),
            ("status", "str:30", True, _states("invoice")),
            ("match_status", "str:30", False, "|".join(MATCH_STATES)),
            ("exception_reason", "str:300", False, ""),
            ("approver_name", "str:120", False, ""), ("approved_at", "datetime", False, ""),
            ("paid_at", "datetime", False, ""), ("payment_id", "ref:payment", False, ""),
            ("discount_available", "money", False, "early payment discount on offer"),
            ("discount_taken", "money", False, ""),
        ]},
    "payment_run": {
        "title": "Payment run", "about": "A batch of payments proposed, approved and released together",
        "core": ["reference", "status", "run_date", "total_amount"],
        "columns": [
            ("reference", "str:30", True, "RUN-2026-38"), ("status", "str:20", True, _states("payment_run")),
            ("run_date", "date", True, ""), ("total_amount", "money", True, ""), ("payment_count", "int", False, ""),
            ("currency", "str:3", False, "GBP"), ("created_by", "str:120", False, ""), ("approved_by", "str:120", False, ""),
        ]},
    "payment": {
        "title": "Payment", "about": "Money sent to a supplier for one or more invoices",
        "core": ["reference", "supplier_id", "amount", "status"],
        "columns": [
            ("reference", "str:30", True, "PAY-0098123"), ("supplier_id", "ref:supplier", True, ""),
            ("payment_run_id", "ref:payment_run", False, ""),
            ("amount", "money", True, ""), ("currency", "str:3", False, "GBP"),
            ("method", "str:20", False, "bacs|faster_payment|chaps|sepa|wire|card"),
            ("status", "str:20", True, _states("payment")),
            ("scheduled_for", "date", False, ""), ("paid_at", "datetime", False, ""),
            ("discount_taken", "money", False, ""),
        ]},
    "contract": {
        "title": "Contract", "about": "The agreement behind the spend: value, term, renewal and notice",
        "core": ["reference", "supplier_id", "status", "start_date", "end_date", "value"],
        "columns": [
            ("reference", "str:30", True, "CTR-2025-0113"), ("title", "str:200", True, ""),
            ("supplier_id", "ref:supplier", True, ""), ("spend_category_id", "ref:spend_category", False, ""),
            ("owner_name", "str:120", False, ""), ("status", "str:20", True, _states("contract")),
            ("start_date", "date", True, ""), ("end_date", "date", True, ""),
            ("value", "money", True, "total contract value"), ("annual_value", "money", False, ""),
            ("currency", "str:3", False, "GBP"), ("notice_days", "int", False, "notice needed before the end date"),
            ("auto_renew", "bool", False, ""),
        ]},
    "savings_initiative": {
        "title": "Savings initiative", "about": "A saving identified and tracked until it is realised",
        "core": ["title", "status", "identified_saving"],
        "columns": [
            ("title", "str:200", True, ""), ("spend_category_id", "ref:spend_category", False, ""),
            ("supplier_id", "ref:supplier", False, ""), ("owner_name", "str:120", False, ""),
            ("saving_type", "str:30", False, "negotiation|consolidation|demand|specification|process"),
            ("status", "str:20", True, _states("savings_initiative")),
            ("baseline_amount", "money", False, ""), ("negotiated_amount", "money", False, ""),
            ("identified_saving", "money", True, ""), ("realised_saving", "money", False, ""),
            ("fiscal_year", "int", False, ""), ("created_at", "datetime", False, ""),
        ]},
    "budget_change": {
        "title": "Budget change", "about": "A proposed move or increase of budget, applied once approved",
        "core": ["cost_center_id", "amount_delta", "status"],
        "columns": [
            ("cost_center_id", "ref:cost_center", True, ""), ("spend_category_id", "ref:spend_category", False, ""),
            ("fiscal_year", "int", True, ""), ("amount_delta", "money", True, "positive adds budget"),
            ("reason", "text", False, ""), ("requested_by", "str:120", False, ""),
            ("status", "str:20", True, _states("budget_change")),
            ("created_at", "datetime", False, ""), ("decided_at", "datetime", False, ""),
        ]},
    "exchange_rate": {
        "title": "Exchange rate", "about": "Units of a currency per one unit of the base currency, by date",
        "core": ["base_currency", "currency", "rate", "rate_date"],
        "columns": [
            ("base_currency", "str:3", True, "GBP"), ("currency", "str:3", True, "EUR"),
            ("rate", "float", True, "1 base = rate × currency"), ("rate_date", "date", True, ""),
        ]},
}

# Tables in an order every reference can be resolved in (a table comes after the ones
# it must refer to; the references between orders, invoices and payments that point
# "forward" are nullable and filled afterwards).
ORDER = ["cost_center", "gl_account", "spend_category", "supplier", "exchange_rate", "budget_line", "contract",
         "requisition", "purchase_order", "purchase_order_line", "goods_receipt", "payment_run", "payment",
         "invoice", "savings_initiative", "budget_change"]

_SQL = {"text": "TEXT", "int": "INTEGER", "float": "DOUBLE PRECISION", "money": "DOUBLE PRECISION",
        "bool": "BOOLEAN", "date": "DATE", "datetime": "TIMESTAMPTZ"}
_PY = {"text": ("str", "Text"), "int": ("int", "Integer"), "float": ("float", "Float"), "money": ("float", "Float"),
       "bool": ("bool", "Boolean"), "date": ("dt.date", "Date"), "datetime": ("dt.datetime", "DateTime(timezone=True)")}


# How a brief speaks of each entity: a word of it in the brief, the backlog or the
# architecture means the application needs the table.
WORDS: dict[str, tuple[str, ...]] = {
    "cost_center": ("cost centre", "cost center", "cost centres", "cost centers"),
    "gl_account": ("gl account", "general ledger", "ledger account", "chart of accounts", "gl code"),
    "spend_category": ("spend category", "spend categories", "category", "categories", "commodity", "commodities"),
    "supplier": ("supplier", "suppliers", "vendor", "vendors"),
    "exchange_rate": ("exchange rate", "exchange rates", "fx rate", "multi-currency", "foreign currency"),
    "budget_line": ("budget", "budgets"),
    "contract": ("contract", "contracts"),
    "requisition": ("requisition", "requisitions", "purchase request", "purchase requests"),
    "purchase_order": ("purchase order", "purchase orders", "po", "pos"),
    "purchase_order_line": ("order line", "order lines", "line item", "line items", "price variance"),
    "goods_receipt": ("goods receipt", "goods receipts", "goods received", "grn", "receipt of goods", "three-way match",
                      "3-way match", "three way match"),
    "payment_run": ("payment run", "payment runs", "payment batch", "payment batches"),
    "payment": ("payment", "payments"),
    "invoice": ("invoice", "invoices"),
    "savings_initiative": ("saving", "savings"),
    "budget_change": ("budget change", "budget changes", "budget transfer", "virement", "budget adjustment"),
}


def needed(text: str) -> list[str]:
    """The standard entities a brief speaks of, and the ones those cannot do without, in ORDER."""
    import re
    low = " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()) + " "
    found = {table for table, words in WORDS.items()
             if any(f" {re.sub(r'[^a-z0-9]+', ' ', w)} " in low for w in words)}
    grew = True
    while grew:
        grew = False
        for table in list(found):
            for _, kind, required, _ in ENTITIES[table]["columns"]:
                if kind.startswith("ref:") and required and kind[4:] not in found:
                    found.add(kind[4:])
                    grew = True
    return [t for t in ORDER if t in found]


def column_names(table: str) -> list[str]:
    return ["id"] + [c[0] for c in ENTITIES[table]["columns"]]


def class_name(table: str) -> str:
    return "".join(p.capitalize() for p in table.split("_"))


def allowed_values(note: str) -> list[str]:
    """The values a status-like column takes, when its note lists them (`a|b|c`)."""
    return [v for v in note.split("|")] if "|" in note and " " not in note.strip() else []


def sql_column(col: Column) -> tuple[str, str]:
    name, kind, required, note = col
    if kind.startswith("str:"):
        sql = f"VARCHAR({kind[4:]})"
    elif kind.startswith("ref:"):
        sql = "INTEGER"
    else:
        sql = _SQL[kind]
    values = allowed_values(note)
    default = ""
    if values and required:
        default = f" DEFAULT '{values[0]}'"
    elif name == "created_at":
        default = " DEFAULT now()"
    elif kind == "bool":
        default = " DEFAULT FALSE"
    elif name == "currency" or name == "base_currency":
        default = " DEFAULT 'GBP'"
    line = f"    {name} {sql}{' NOT NULL' if required else ''}{default}"
    return line, (f"  -- {note}" if values else "")


def create_table(table: str, extra: list[str] | tuple[str, ...] = ()) -> str:
    """The CREATE TABLE of a standard entity, in the platform's init.sql conventions.
    `extra` are column definitions an application adds ("dispute_reason VARCHAR(300)")."""
    cols = [sql_column(c) for c in ENTITIES[table]["columns"]]
    lines = ["    id SERIAL PRIMARY KEY"] + [c for c, _ in cols] + [f"    {e.strip().rstrip(',')}" for e in extra]
    notes = [""] + [n for _, n in cols] + ["" for _ in extra]
    body = []
    for i, (line, note) in enumerate(zip(lines, notes)):
        body.append(line + ("," if i < len(lines) - 1 else "") + note)
    return f"CREATE TABLE IF NOT EXISTS {table} (\n" + "\n".join(body) + "\n);"


def model_class(table: str, extra_lines: list[str] | tuple[str, ...] = ()) -> str:
    """The SQLAlchemy class of a standard entity, in the platform's models.py conventions.
    `extra_lines` are attribute lines an application adds, as it wrote them."""
    e = ENTITIES[table]
    out = [f"class {class_name(table)}(Base):", f'    """{e["title"]}: {e["about"]}."""', "",
           f'    __tablename__ = "{table}"', "",
           "    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)"]
    for name, kind, required, note in ENTITIES[table]["columns"]:
        if kind.startswith("str:"):
            py, sa = "str", f"String({kind[4:]})"
        elif kind.startswith("ref:"):
            py, sa = "int", "Integer"
        else:
            py, sa = _PY[kind]
        values = allowed_values(note)
        extra = ""
        if values and required:
            extra = f', default="{values[0]}"'
        elif name == "created_at":
            extra = ", default=_now"
        elif kind == "bool":
            extra = ", default=False"
        elif name in ("currency", "base_currency"):
            extra = ', default="GBP"'
        nullable = "" if required or extra else ", nullable=True"
        hint = py if required or extra else f"{py} | None"
        comment = f"  # {note}" if values else ""
        out.append(f"    {name}: Mapped[{hint}] = mapped_column({sa}{nullable}{extra}){comment}")
    return "\n".join(out + [f"    {line.strip()}" for line in extra_lines])


_SCHEMA = {"text": "str", "int": "int", "float": "float", "money": "float", "bool": "bool", "date": "dt.date",
           "datetime": "dt.datetime"}


def schema_classes(table: str, extra: list[str] | tuple[str, ...] = ()) -> str:
    """<Entity>Create and <Entity>Out, in the platform's schemas.py conventions.
    `extra` are field lines an application adds to both ("dispute_reason: str | None = None")."""
    name = class_name(table)
    create, out = [f"class {name}Create(BaseModel):"], [f"class {name}Out(BaseModel):",
                                                        "    model_config = ConfigDict(from_attributes=True)", "",
                                                        "    id: int"]
    for column, kind, required, note in ENTITIES[table]["columns"]:
        py = "str" if kind.startswith("str:") else "int" if kind.startswith("ref:") else _SCHEMA[kind]
        values = allowed_values(note)
        given = bool(values and required) or column == "created_at" or kind == "bool" or column in ("currency", "base_currency")
        if required and not given:
            create.append(f"    {column}: {py}")
        elif values and required:
            create.append(f'    {column}: {py} = "{values[0]}"')
        else:
            create.append(f"    {column}: {py} | None = None")
        out.append(f"    {column}: {py} | None = None")
    tail = [f"    {line.strip()}" for line in extra]
    return "\n".join(create + tail) + "\n\n\n" + "\n".join(out + tail)


def summary(tables: list[str] | None = None) -> str:
    """The entities as one line each, for a prompt: name, what it is, columns with types."""
    lines = []
    for table in tables or ORDER:
        e = ENTITIES[table]
        cols = []
        for name, kind, required, note in e["columns"]:
            values = allowed_values(note)
            shown = {"money": "Float", "float": "Float", "int": "Integer", "bool": "Boolean", "text": "Text",
                     "date": "Date", "datetime": "DateTime"}.get(kind) or (
                f"String({kind[4:]})" if kind.startswith("str:") else "Integer")
            cols.append(f"{name}{'' if required else '?'} {shown}" + (f" [{note}]" if values else ""))
        lines.append(f"- {table} ({e['title']}: {e['about']}): " + ", ".join(cols))
    return "\n".join(lines)


def gaps(tables: dict[str, Any]) -> list[str]:
    """For every standard entity a data model has, the core columns it lacks.

    `tables` maps table name to its column names (any iterable)."""
    out = []
    for table, cols in tables.items():
        e = ENTITIES.get(str(table).lower())
        if not e:
            continue
        have = {str(c).lower() for c in cols}
        missing = [c for c in e["core"] if c not in have]
        if missing:
            spec = {c[0]: c for c in e["columns"]}
            out.append(f"`{table}` is a standard finance entity but lacks its column(s) "
                       + ", ".join(f"`{m}` ({spec[m][1].replace('money', 'Float')})" for m in missing)
                       + ": the library's demonstration data, analytics and workflows read them")
    return out
