"""The insight API: the numbers a finance dashboard asks for. Written by Poiesis, and read-only.

Served under /api/finance/ in every application built with the finance pack, over
whichever standard entities (finance/standard.py) its data model has. No story writes
these; a screen asks for them through `fin.data(api)` in frontend/finance.js, or directly:

    GET /api/finance/calendar        today, the fiscal year, the period presets, which entities exist
    GET /api/finance/dimensions      cost centres, categories, families, suppliers… for the filters
    GET /api/finance/kpis            every headline figure, against the comparison period, with a trend
    GET /api/finance/breakdown       ?measure=spend&by=supplier&top=10      a measure by a dimension
    GET /api/finance/trend           ?measure=spend&kind=month&periods=12   with budget and last year
    GET /api/finance/budget          ?by=cost_center                        budget, actual, committed, left
    GET /api/finance/waterfall       ?by=cost_center                        from budget to actual, step by step
    GET /api/finance/aging           open payables by how overdue, and who is owed
    GET /api/finance/funnel          requested → approved → ordered → received → invoiced → paid
    GET /api/finance/pivot           ?measure=spend&rows=cost_center&columns=month
    GET /api/finance/concentration   ?measure=spend&by=supplier             the Pareto, top-10 share, HHI
    GET /api/finance/cycle-times     how long each step of purchase-to-pay takes
    GET /api/finance/exceptions      invoices held, by reason and age
    GET /api/finance/accruals        received and not invoiced (FIN-08)
    GET /api/finance/renewals        ?within=180                            contracts to decide on (PROC-07)
    GET /api/finance/controls        duplicates, splits, no order, unapproved suppliers, self-approval
    GET /api/finance/suppliers/{id}/scorecard
    GET /api/finance/documents       ?entity=invoice&…                      the rows behind any number

and what people do to their records (operations.py), each through the record's workflow:

    POST /api/finance/invoices/{id}/match              three-way match, duplicates, no order no pay
    POST /api/finance/purchase-orders/{id}/receive     {"amount": 1200, "quantity": 10, "received_by": "Goods In"}
    POST /api/finance/payment-runs/propose             {"due_by": "2026-10-09", "run_date": "2026-10-01"}
    GET  /api/finance/payment-runs/payable             what a run proposed now would pay
    GET  /api/finance/budget/position                  ?cost_center_id=3&requested=5000   what is left (FIN-02)
    GET  /api/finance/requisitions/{id}/advice         approver, budget, quotes, supplier, splits
    POST /api/finance/requisitions                     {"title": "…", "amount": 1800, "cost_center_id": 7}   a draft
    POST /api/finance/requisitions/{id}/order          {"supplier_id": 12}   the order of an approved requisition
    POST /api/finance/purchase-orders/{id}/send        to the supplier, and into the ERP
    GET  /api/finance/approvals                        what waits for my decision (?mine=false: for anyone's)
    GET  /api/finance/worklist                         ?entity=requisition&mine=true   how many in each state

Every endpoint takes the same scope:

    ?period=fy_to_date | this_month | last_month | this_quarter | last_quarter | fiscal_year |
            last_fiscal_year | last_12_months | last_30_days | last_90_days
    ?from=2026-04-01&to=2026-09-30                 instead of a preset
    ?compare=prior_year | prior_period | none
    ?cost_center_id=3,5 &spend_category_id= &supplier_id= &family=IT &department= &region= &country= &currency=

A person sees figures only from the tables they may read: a figure that needs a table they
cannot read is left out rather than shown. An application that lacks an entity gets that
figure empty ("available": false), never an error. Amounts are in the base currency (BASE_CURRENCY,
converted with the latest exchange_rate when a document is in another one). The fiscal year
starts in FISCAL_YEAR_START_MONTH (4, April, unless set). Rows are read into memory and
summed exactly: right for a department's volumes (tens of thousands of documents).
"""
from __future__ import annotations

import copy
import datetime as dt
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import Base, get_session
from ..kernel.context import current
from ..kernel.policy import can, ensure, policy
from ..kernel.workflow import iter_workflows
from . import analytics as fa
from . import money, standard
from . import operations as ops
from . import rules as fin
from .money import D
from .operations import model
from .periods import FiscalCalendar, add_months, as_date, days_overdue
from .rules import get

router = APIRouter(prefix="/finance")

ZERO = Decimal(0)


# ------------------------------------------------------------------------------ settings

def calendar() -> FiscalCalendar:
    try:
        return FiscalCalendar(int(os.getenv("FISCAL_YEAR_START_MONTH", "4") or 4))
    except ValueError:
        return FiscalCalendar(4)


def today() -> dt.date:
    """The day the figures are as of: FINANCE_AS_OF when set (a demonstration frozen in time), else today."""
    try:
        return as_date(os.getenv("FINANCE_AS_OF", "")) or dt.date.today()
    except ValueError:
        return dt.date.today()


def base_currency() -> str:
    return (os.getenv("BASE_CURRENCY", "GBP") or "GBP").upper()


def presets(cal: FiscalCalendar, day: dt.date) -> dict[str, dict[str, Any]]:
    """The periods a person picks from, each with its dates and what it is compared like-for-like with."""
    month, quarter, year = cal.bounds("month", day), cal.bounds("quarter", day), cal.bounds("year", day)
    items: list[tuple[str, str, dt.date, dt.date, int]] = [
        ("this_month", f"This month ({cal.label('month', day)})", month[0], day, 1),
        ("last_month", f"Last month ({cal.label('month', cal.prior('month', day)[0])})", *cal.prior("month", day), 1),
        ("this_quarter", f"This quarter ({cal.label('quarter', day)})", quarter[0], day, 3),
        ("last_quarter", f"Last quarter ({cal.label('quarter', cal.prior('quarter', day)[0])})", *cal.prior("quarter", day), 3),
        ("fy_to_date", f"Year to date ({cal.label('year', day)})", year[0], day, 12),
        ("fiscal_year", f"Full year ({cal.label('year', day)})", year[0], year[1], 12),
        ("last_fiscal_year", f"Last year ({cal.label('year', cal.prior('year', day)[0])})", *cal.prior("year", day), 12),
        ("last_12_months", "Last 12 months", add_months(month[0], -11), day, 12),
        ("last_90_days", "Last 90 days", day - dt.timedelta(days=89), day, 0),
        ("last_30_days", "Last 30 days", day - dt.timedelta(days=29), day, 0),
    ]
    return {key: {"key": key, "label": label, "from": start.isoformat(), "to": end.isoformat(), "months": months}
            for key, label, start, end, months in items}


def _ids(text: str) -> set[Any]:
    out: set[Any] = set()
    for part in str(text or "").split(","):
        part = part.strip()
        if part:
            out.add(int(part) if part.lstrip("-").isdigit() else part.lower())
    return out


# Filters that are a column of the document, and those reached through one of its references.
DIRECT = ("cost_center_id", "spend_category_id", "supplier_id", "currency")
VIA = {"family": ("spend_category_id", "spend_category", "family"),
       "department": ("cost_center_id", "cost_center", "department"),
       "region": ("cost_center_id", "cost_center", "region"),
       "country": ("supplier_id", "supplier", "country")}
OWN_ID = {"cost_center": "cost_center_id", "spend_category": "spend_category_id", "supplier": "supplier_id"}


class Scope:
    """The period, the comparison and the filters of a request: one dependency for every endpoint."""

    def __init__(self, period: str = "", start: str = "", end: str = "", compare: str = "prior_year",
                 cost_center_id: str = "", spend_category_id: str = "", supplier_id: str = "", family: str = "",
                 department: str = "", region: str = "", country: str = "", currency: str = "") -> None:
        self.calendar, self.today = calendar(), today()
        options = presets(self.calendar, self.today)
        try:
            first, last = as_date(start), as_date(end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{exc}: dates are written 2026-04-01") from None
        if first or last:
            self.period, months = "custom", 0
            self.start = first or self.calendar.bounds("year", last)[0]
            self.end = last or self.today
            self.label = f"{self.start.isoformat()} to {self.end.isoformat()}"
        else:
            chosen = options.get(period or "fy_to_date")
            if chosen is None:
                raise HTTPException(status_code=422, detail=f"period is one of {', '.join(options)}; or pass from= and to=")
            self.period, months, self.label = chosen["key"], chosen["months"], chosen["label"]
            self.start, self.end = as_date(chosen["from"]), as_date(chosen["to"])
        if self.start > self.end:
            raise HTTPException(status_code=422, detail="from is after to")
        if compare not in ("prior_year", "prior_period", "none", ""):
            raise HTTPException(status_code=422, detail="compare is one of prior_year, prior_period, none")
        self.compare = compare or "none"
        self.prior: tuple[dt.date, dt.date] | None = None
        if self.compare == "prior_year":
            self.prior = self.calendar.year_ago(self.start, self.end)
        elif self.compare == "prior_period":
            if months:          # a month against the month before, to the same day; a quarter against the quarter before
                self.prior = (add_months(self.start, -months), add_months(self.end, -months))
            else:
                days = (self.end - self.start).days + 1
                self.prior = (self.start - dt.timedelta(days=days), self.start - dt.timedelta(days=1))
        self.filters: dict[str, set[Any]] = {k: _ids(v) for k, v in {
            "cost_center_id": cost_center_id, "spend_category_id": spend_category_id, "supplier_id": supplier_id,
            "family": family, "department": department, "region": region, "country": country,
            "currency": currency}.items() if _ids(v)}

    def narrowed(self, **filters: set[Any]) -> "Scope":
        """The same period and comparison, with these filters as well."""
        other = copy.copy(self)
        other.filters = {**self.filters, **filters}
        return other

    def describe(self) -> dict[str, Any]:
        return {"period": self.period, "label": self.label, "from": self.start.isoformat(), "to": self.end.isoformat(),
                "compare": self.compare,
                "prior": {"from": self.prior[0].isoformat(), "to": self.prior[1].isoformat()} if self.prior else None,
                "filters": {k: sorted(v, key=str) for k, v in self.filters.items()},
                "as_of": self.today.isoformat(), "currency": base_currency()}


def requested(period: str = "", start: str = Query("", alias="from"), end: str = Query("", alias="to"),
              compare: str = "prior_year", cost_center_id: str = "", spend_category_id: str = "",
              supplier_id: str = "", family: str = "", department: str = "", region: str = "", country: str = "",
              currency: str = "") -> Scope:
    """The scope a request asks for, read from its query string."""
    return Scope(period, start, end, compare, cost_center_id, spend_category_id, supplier_id, family, department,
                 region, country, currency)


# ------------------------------------------------------------------------------ the books

def _same(value: Any, wanted: set[Any]) -> bool:
    if value is None:
        return False
    return value in wanted or str(value).lower() in wanted


class Book:
    """The application's finance tables, each read once for a request and cut to its scope."""

    def __init__(self, db: Session, scope: Scope) -> None:
        self.db, self.scope = db, scope
        self._all: dict[tuple[str, bool], list[Any]] = {}
        self._by_id: dict[str, dict[Any, Any]] = {}
        self._rates: dict[str, Decimal] | None = None
        self.base = base_currency()

    def has(self, table: str) -> bool:
        """The table exists and this person may read it."""
        return model(table) is not None and can(f"{table}:read")

    def columns(self, table: str) -> set[str]:
        cls = model(table)
        return {c.key for c in cls.__table__.columns} if cls is not None else set()

    def all(self, table: str, scoped: bool = True) -> list[Any]:
        key = (table, scoped)
        if key not in self._all:
            if not self.has(table):
                self._all[key] = []
            elif scoped:
                self._all[key] = [r for r in self.all(table, scoped=False) if self.admits(table, r)]
            else:
                self._all[key] = list(self.db.execute(select(model(table))).scalars().all())
        return self._all[key]

    def by_id(self, table: str) -> dict[Any, Any]:
        if table not in self._by_id:
            self._by_id[table] = {r.id: r for r in self.all(table, scoped=False)}
        return self._by_id[table]

    def names(self, table: str, column: str = "name") -> dict[Any, str]:
        return {k: str(get(r, column, "") or get(r, "code", "") or k) for k, r in self.by_id(table).items()}

    def through(self, row: Any, column: str, table: str, field: str) -> Any:
        """A value reached through a reference: the family of a document's category."""
        return get(self.by_id(table).get(get(row, column)), field)

    def admits(self, table: str, row: Any) -> bool:
        have = self.columns(table)
        for name, wanted in self.scope.filters.items():
            if name in DIRECT:
                if OWN_ID.get(table) == name:
                    if not _same(row.id, wanted):
                        return False
                elif name in have and not _same(getattr(row, name), wanted):
                    return False
            else:
                column, other, field = VIA[name]
                if table == other:
                    if field in have and not _same(getattr(row, field), wanted):
                        return False
                elif column in have and not _same(self.through(row, column, other, field), wanted):
                    return False
        return True

    # -- money in the base currency ---------------------------------------------------
    def rates(self) -> dict[str, Decimal]:
        if self._rates is None:
            self._rates = {}
            if model("exchange_rate") is not None:
                latest: dict[str, Any] = {}
                for r in self.db.execute(select(model("exchange_rate"))).scalars().all():
                    if str(get(r, "base_currency", self.base)).upper() != self.base:
                        continue
                    code = str(get(r, "currency", "")).upper()
                    if code not in latest or as_date(get(r, "rate_date")) > as_date(get(latest[code], "rate_date")):
                        latest[code] = r
                self._rates = {c: D(get(r, "rate", 0)) for c, r in latest.items() if D(get(r, "rate", 0)) > 0}
        return self._rates

    def in_base(self, row: Any, amount: Any) -> Decimal:
        value = D(amount)
        code = str(get(row, "currency", self.base) or self.base).upper()
        if code != self.base and code in self.rates():
            return money.quantize(value / self.rates()[code], self.base)
        return value


# ------------------------------------------------------------------------------ measures

@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    table: str
    amount: str
    date: str
    only: tuple[str, ...] = ()              # the statuses that count; all of them when empty
    exclude: tuple[str, ...] = ()
    less: str = ""                          # a column taken off the amount (what is already invoiced)
    dated: bool = True                      # False: a position as of today, whatever the period
    about: str = ""


OPEN_INVOICE = ("received", "matched", "exception", "approved", "scheduled")
OPEN_ORDER = ("approved", "sent", "partially_received", "received")

MEASURES: dict[str, Measure] = {m.key: m for m in (
    Measure("spend", "Spend", "invoice", "net_amount", "invoice_date", exclude=("rejected",),
            about="The net value of invoices dated in the period; rejected invoices are left out"),
    Measure("invoiced", "Invoiced (gross)", "invoice", "amount", "invoice_date", exclude=("rejected",),
            about="The gross value of invoices dated in the period"),
    Measure("payables", "Open payables", "invoice", "amount", "due_date", only=OPEN_INVOICE, dated=False,
            about="Invoices received and not yet paid, gross, as of today"),
    Measure("paid", "Paid", "invoice", "amount", "paid_at", only=("paid",),
            about="The gross value of invoices paid in the period"),
    Measure("orders", "Ordered", "purchase_order", "amount", "order_date", exclude=("draft", "cancelled"),
            about="The value of purchase orders placed in the period"),
    Measure("commitments", "Open commitments", "purchase_order", "amount", "order_date", only=OPEN_ORDER,
            less="invoiced_amount", dated=False,
            about="Ordered and not yet invoiced: what is committed and still to come, as of today"),
    Measure("requisitions", "Requested", "requisition", "amount", "created_at", exclude=("draft", "cancelled"),
            about="The value of purchase requisitions raised in the period"),
    Measure("receipts", "Received", "goods_receipt", "amount", "received_at", exclude=("reversed",),
            about="The value of goods and services receipted in the period"),
    Measure("payments", "Payments", "payment", "amount", "paid_at", only=("completed",),
            about="Money sent to suppliers in the period"),
    Measure("budget", "Budget", "budget_line", "amount", "period_start",
            about="The budget of the periods that start in the range"),
    Measure("savings", "Savings identified", "savings_initiative", "identified_saving", "created_at",
            exclude=("cancelled",), about="Savings identified by initiatives raised in the period"),
    Measure("realised_savings", "Savings realised", "savings_initiative", "realised_saving", "created_at",
            exclude=("cancelled",), about="Savings realised by initiatives raised in the period"),
    Measure("contract_value", "Contract value", "contract", "annual_value", "start_date",
            exclude=("draft", "terminated"), about="The annual value of contracts starting in the period"),
)}

# The date a document is filed under, for the rows behind a number.
DATE_OF = {"invoice": "invoice_date", "purchase_order": "order_date", "requisition": "created_at",
           "goods_receipt": "received_at", "payment": "paid_at", "payment_run": "run_date", "contract": "end_date",
           "budget_line": "period_start", "savings_initiative": "created_at", "budget_change": "created_at",
           "supplier": "onboarded_at"}
# Whose a record is: the column that holds the name of the person working on it.
OWNER_OF = {"requisition": "requester_name", "purchase_order": "buyer_name", "contract": "owner_name",
            "goods_receipt": "received_by", "savings_initiative": "owner_name", "budget_change": "requested_by",
            "cost_center": "owner_name"}
AMOUNT_OF = {"invoice": "amount", "purchase_order": "amount", "requisition": "amount", "goods_receipt": "amount",
             "payment": "amount", "payment_run": "total_amount", "contract": "value", "budget_line": "amount",
             "savings_initiative": "identified_saving", "budget_change": "amount_delta"}


def allowed(table: str, what: str = "") -> bool:
    """False when the application has no such table: the figure is then empty, not an error (an
    application uses the entities its brief needs). 403 when it has and this person may not read it."""
    if model(table) is None:
        return False
    ensure(f"{table}:read", what=what or f"see {table.replace('_', ' ')} records")
    return True


def measure_of(key: str) -> Measure:
    if key not in MEASURES:
        raise HTTPException(status_code=422, detail=f"measure is one of {', '.join(MEASURES)}")
    return MEASURES[key]


def facts(book: Book, measure: Measure, start: dt.date | None = None, end: dt.date | None = None) -> list[Any]:
    """The rows a measure counts, in the scope, dated in the range (a position ignores the range)."""
    have = book.columns(measure.table)
    if measure.amount not in have:
        return []
    rows = book.all(measure.table)
    if "status" in have and (measure.only or measure.exclude):
        rows = [r for r in rows if (not measure.only or r.status in measure.only) and r.status not in measure.exclude]
    if measure.dated and start is not None and end is not None:
        if measure.date not in have:
            return []
        rows = [r for r in rows if getattr(r, measure.date) is not None and start <= as_date(getattr(r, measure.date)) <= end]
    return rows


def valuer(book: Book, measure: Measure) -> Callable[[Any], Decimal]:
    def value(row: Any) -> Decimal:
        amount = D(get(row, measure.amount, 0))
        if measure.less:
            amount = max(ZERO, amount - D(get(row, measure.less, 0)))
        return book.in_base(row, amount)
    return value


def total(book: Book, measure: Measure, start: dt.date | None = None, end: dt.date | None = None) -> Decimal:
    value = valuer(book, measure)
    return sum((value(r) for r in facts(book, measure, start, end)), ZERO)


# ---------------------------------------------------------------------------- dimensions

REFERENCES = {"supplier": ("supplier_id", "supplier"), "category": ("spend_category_id", "spend_category"),
              "cost_center": ("cost_center_id", "cost_center"), "gl_account": ("gl_account_id", "gl_account"),
              "contract": ("contract_id", "contract"), "purchase_order": ("purchase_order_id", "purchase_order")}
THROUGH = {**VIA, "risk": ("supplier_id", "supplier", "risk_rating"),
           "supplier_status": ("supplier_id", "supplier", "status"),
           "direct": ("spend_category_id", "spend_category", "is_direct")}
ALIASES = {"buyer": "buyer_name", "requester": "requester_name", "owner": "owner_name", "approver": "approver_name",
           "match": "match_status", "terms": "payment_terms", "type": "saving_type"}
TIME = ("month", "quarter", "year")


def dimension(book: Book, by: str, table: str, date: str) -> tuple[Callable[[Any], Any], dict[Any, str] | None]:
    """How to read a dimension off a row, and the names of its values when they are references."""
    have = book.columns(table)
    by = ALIASES.get(by, by)
    if by in TIME:
        cal = book.scope.calendar

        def when(row: Any) -> Any:
            d = as_date(get(row, date))
            return cal.bounds(by, d)[0].isoformat() if d else None
        return when, _PeriodNames(cal, by)
    if by in REFERENCES and REFERENCES[by][0] in have:
        column, other = REFERENCES[by]
        names = book.names(other, "reference" if other in ("contract", "purchase_order") else "name")
        return (lambda row: get(row, column)), names
    if by in OWN_ID and table == by:
        return (lambda row: row.id), book.names(table)
    if by in THROUGH:
        column, other, field = THROUGH[by]
        if table == other and field in have:
            return (lambda row: _shown(get(row, field))), None
        if column in have:
            return (lambda row: _shown(book.through(row, column, other, field))), None
    if by in have:
        return (lambda row: _shown(get(row, by))), None
    raise HTTPException(status_code=422, detail=(
        f"{table.replace('_', ' ')} cannot be read by '{by}'. Use one of: "
        + ", ".join(sorted(dimensions_of(book, table)))))


def dimensions_of(book: Book, table: str) -> list[str]:
    have = book.columns(table)
    out = [k for k, (column, _) in REFERENCES.items() if column in have]
    out += [k for k, (column, other, _) in THROUGH.items() if column in have or table == other]
    out += [c for c in ("status", "match_status", "currency", "payment_terms", "method", "saving_type", "buyer_name",
                        "requester_name", "owner_name", "country", "risk_rating") if c in have]
    if DATE_OF.get(table) in have:
        out += list(TIME)
    return sorted(set(out))


def _shown(value: Any) -> Any:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return value


class _PeriodNames(dict):
    """The label of a period from its first day: "2026-07-01" -> "Jul 2026" or "Q2 FY2027"."""

    def __init__(self, cal: FiscalCalendar, kind: str) -> None:
        super().__init__()
        self.cal, self.kind = cal, kind

    def __bool__(self) -> bool:
        return True

    def __contains__(self, key: Any) -> bool:
        return key not in (None, "")

    def __getitem__(self, key: Any) -> str:
        return self.cal.label(self.kind, as_date(key))


def _words(value: Any) -> str:
    text = str(value if value not in (None, "") else "Unassigned").replace("_", " ")
    return text[:1].upper() + text[1:] if text == text.lower() else text


def _labelled(items: list[dict[str, Any]], names: Any) -> list[dict[str, Any]]:
    """Values that are words (a status, a rating) are shown as words: "price_variance" -> "Price variance"."""
    if names is not None:
        return items
    return [{**i, "label": _words(i["key"]) if i["key"] not in (None, "") or i["label"] == "Unassigned" else i["label"]}
            for i in items]


# ------------------------------------------------------------------------------ calendar

@router.get("/calendar")
def get_calendar(scope: Scope = Depends(requested)) -> dict[str, Any]:
    cal, day = scope.calendar, scope.today
    book = Book(None, scope)            # no rows are read: only which tables exist and may be read
    return {"today": day.isoformat(), "currency": base_currency(), "symbol": money.symbol(base_currency()),
            "fiscal_year_start_month": cal.start_month, "fiscal_year": cal.fiscal_year(day),
            "fiscal_year_label": cal.label("year", day), "quarter": cal.quarter(day), "period": cal.period(day),
            "presets": list(presets(cal, day).values()), "default_period": "fy_to_date",
            "entities": {t: book.has(t) for t in standard.ORDER},
            "measures": [{"key": m.key, "label": m.label, "about": m.about, "dated": m.dated,
                          "dimensions": dimensions_of(book, m.table)} for m in MEASURES.values() if book.has(m.table)],
            "states": standard.STATES, "match_states": standard.MATCH_STATES, "roles": policy().roles,
            "workflows": sorted({w.entity for w in iter_workflows()}),
            "aging_buckets": fa.aging_buckets(), "approval_matrix": [
                {"up_to": limit, "role": role} for limit, role in fin.POLICY.doa],
            "policy": {"po_required_above": fin.POLICY.po_required_above, "budget_warning_pct": fin.POLICY.budget_warning_pct,
                       "material_pct": fin.POLICY.material_pct, "expiring_days": fin.POLICY.expiring_days,
                       "tolerance": {"price_pct": fin.POLICY.tolerance.price_pct, "quantity_pct": fin.POLICY.tolerance.quantity_pct,
                                     "amount_abs": fin.POLICY.tolerance.amount_abs}}}


@router.get("/dimensions")
def get_dimensions(db: Session = Depends(get_session)) -> dict[str, Any]:
    """What a filter bar offers: every value of each dimension, in the order people look for them."""
    book = Book(db, Scope())            # the choices themselves are never filtered
    out: dict[str, Any] = {}

    def distinct(table: str, field: str) -> list[dict[str, Any]]:
        values = sorted({str(get(r, field)) for r in book.all(table) if get(r, field) not in (None, "")})
        return [{"value": v, "label": v} for v in values]

    if book.has("cost_center"):
        out["cost_center_id"] = {"label": "Cost centre", "options": [
            {"value": r.id, "label": f"{get(r, 'code', '')} {get(r, 'name', '')}".strip(), "group": get(r, "department", "")}
            for r in sorted(book.all("cost_center"), key=lambda r: str(get(r, "code", "")))]}
        for field, label in (("department", "Department"), ("region", "Region")):
            if field in book.columns("cost_center") and distinct("cost_center", field):
                out[field] = {"label": label, "options": distinct("cost_center", field)}
    if book.has("spend_category"):
        if "family" in book.columns("spend_category"):
            out["family"] = {"label": "Category family", "options": distinct("spend_category", "family")}
        out["spend_category_id"] = {"label": "Category", "options": [
            {"value": r.id, "label": str(get(r, "name", "")), "group": get(r, "family", "")}
            for r in sorted(book.all("spend_category"), key=lambda r: (str(get(r, "family", "")), str(get(r, "name", ""))))]}
    if book.has("supplier"):
        out["supplier_id"] = {"label": "Supplier", "options": [
            {"value": r.id, "label": str(get(r, "name", "")), "group": get(r, "country", "")}
            for r in sorted(book.all("supplier"), key=lambda r: str(get(r, "name", "")).lower())]}
        if "country" in book.columns("supplier") and distinct("supplier", "country"):
            out["country"] = {"label": "Supplier country", "options": distinct("supplier", "country")}
    return {"dimensions": out}


# ---------------------------------------------------------------------------------- KPIs

class Window:
    """The books over one range of dates, with each measure's rows worked out once."""

    def __init__(self, book: Book, start: dt.date, end: dt.date) -> None:
        self.book, self.start, self.end = book, start, end
        self._facts: dict[str, list[Any]] = {}

    def rows(self, measure: str) -> list[Any]:
        if measure not in self._facts:
            self._facts[measure] = facts(self.book, MEASURES[measure], self.start, self.end)
        return self._facts[measure]

    def total(self, measure: str) -> Decimal:
        value = valuer(self.book, MEASURES[measure])
        return sum((value(r) for r in self.rows(measure)), ZERO)

    def days(self) -> int:
        return (self.end - self.start).days + 1


def _contracted(book: Book) -> set[Any]:
    """Suppliers under contract: flagged so, or with a contract that is signed or running."""
    out = {s.id for s in book.all("supplier", scoped=False) if get(s, "is_contracted", False)}
    out |= {get(c, "supplier_id") for c in book.all("contract", scoped=False)
            if get(c, "status", "") in ("signed", "active", "expiring")}
    return out


def _orders_of(w: Window) -> list[Any]:
    return w.rows("orders")


def _lines_of(w: Window) -> list[Any]:
    wanted = {o.id for o in _orders_of(w)}
    return [ln for ln in w.book.all("purchase_order_line") if get(ln, "purchase_order_id") in wanted]


def _receipts_of(w: Window) -> list[Any]:
    orders = w.book.by_id("purchase_order")
    scoped = {o.id for o in w.book.all("purchase_order")}
    return [r for r in w.rows("receipts") if not orders or get(r, "purchase_order_id") in scoped]


def _overdue(w: Window) -> Decimal:
    value = valuer(w.book, MEASURES["payables"])
    day = w.book.scope.today
    return sum((value(r) for r in w.rows("payables") if get(r, "due_date") and days_overdue(r.due_date, day) > 0), ZERO)


def _budget_used(w: Window) -> float | None:
    budget = w.total("budget")
    return money.pct(w.total("spend"), budget) if budget > 0 else None


def _year(w: Window) -> dict[str, Any]:
    """The fiscal year the window ends in: its budget, what is spent and committed, where it is heading."""
    scope = w.book.scope
    year = scope.calendar.bounds("year", w.end)
    so_far = min(w.end, scope.today, year[1])
    commitments = [o for o in facts(w.book, MEASURES["commitments"]) if get(o, "order_date") and as_date(o.order_date) <= w.end]
    value = valuer(w.book, MEASURES["commitments"])
    sums = {"budget": w.total("budget"), "actual": w.total("spend"),
            "year_budget": total(w.book, MEASURES["budget"], *year),
            "year_actual": total(w.book, MEASURES["spend"], year[0], so_far),
            "committed": sum((value(o) for o in commitments), ZERO)}
    elapsed = Decimal((so_far - year[0]).days + 1) / Decimal((year[1] - year[0]).days + 1)
    return _budget_figures(sums, elapsed)


def _expiring(w: Window) -> int:
    day = w.book.scope.today
    return sum(1 for c in w.book.all("contract")
               if get(c, "status", "") not in ("draft", "expired", "terminated") and get(c, "end_date")
               and fin.renewal(c.end_date, day, get(c, "notice_days", 0), bool(get(c, "auto_renew", False))).status
               in ("expiring", "notice_due"))


def _cycle(rows: list[Any], start: str, end: str) -> float | None:
    return fa.cycle_time(rows, start, end)["average_days"]


@dataclass(frozen=True)
class Kpi:
    key: str
    label: str
    unit: str                                # money | pct | days | count
    value: Callable[[Window], Any]
    needs: tuple[str, ...]                   # tables (and columns, "invoice.match_status") it cannot do without
    good: str = ""                           # "up" or "down": which way is better; "" when neither is
    about: str = ""
    position: bool = False                   # as of today: no comparison, no trend
    drill: tuple[tuple[str, str], ...] = ()  # the /documents query that lists what is behind it
    icon: str = ""


def _money(value: Decimal) -> float:
    return float(money.quantize(value))


KPIS: tuple[Kpi, ...] = (
    Kpi("spend", "Spend", "money", lambda w: _money(w.total("spend")), ("invoice",), icon="dollar",
        about=MEASURES["spend"].about, drill=(("entity", "invoice"),)),
    Kpi("budget_used", "Budget used", "pct", _budget_used, ("invoice", "budget_line"), good="down", icon="pie",
        about="Spend in the period as a share of the budget for the same period"),
    Kpi("budget", "Budget", "money", lambda w: _money(w.total("budget")), ("budget_line",), icon="dollar",
        about="The budget of the period"),
    Kpi("budget_variance", "Variance to budget", "money", lambda w: _year(w)["variance"], ("invoice", "budget_line"),
        good="down", icon="activity", about="Spend in the period less its budget: above zero is over budget (FIN-07)"),
    Kpi("budget_available", "Budget available", "money", lambda w: _year(w)["available"], ("invoice", "budget_line"),
        good="up", position=True, icon="layers",
        about="The fiscal year's budget less what is spent and what is committed, as of today (FIN-02)"),
    Kpi("forecast", "Year forecast", "money", lambda w: _year(w)["forecast"], ("invoice", "budget_line"), position=True,
        icon="trend-up", about="Where the fiscal year's spend is heading at the rate so far"),
    Kpi("forecast_pct", "Forecast against budget", "pct", lambda w: _year(w)["forecast_pct"], ("invoice", "budget_line"),
        good="down", position=True, icon="pie", about="The year's forecast spend as a share of the year's budget"),
    Kpi("requisitions", "Requested", "money", lambda w: _money(w.total("requisitions")), ("requisition",), icon="inbox",
        about=MEASURES["requisitions"].about, drill=(("entity", "requisition"),)),
    Kpi("awaiting_approval", "Awaiting approval", "count",
        lambda w: sum(1 for r in w.book.all("requisition") if get(r, "status", "") == "submitted"), ("requisition",),
        good="down", position=True, icon="clock", about="Requisitions submitted and not yet decided",
        drill=(("entity", "requisition"), ("status", "submitted"), ("dated", "false"))),
    Kpi("orders", "Ordered", "money", lambda w: _money(w.total("orders")), ("purchase_order",), icon="cart",
        about=MEASURES["orders"].about, drill=(("entity", "purchase_order"),)),
    Kpi("commitments", "Open commitments", "money", lambda w: _money(w.total("commitments")), ("purchase_order",),
        position=True, icon="layers", about=MEASURES["commitments"].about,
        drill=(("entity", "purchase_order"), ("status", ",".join(OPEN_ORDER)), ("dated", "false"))),
    Kpi("payables", "Open payables", "money", lambda w: _money(w.total("payables")), ("invoice",), position=True,
        icon="inbox", about=MEASURES["payables"].about,
        drill=(("entity", "invoice"), ("status", ",".join(OPEN_INVOICE)), ("dated", "false"))),
    Kpi("overdue", "Overdue payables", "money", lambda w: _money(_overdue(w)), ("invoice",), good="down", position=True,
        icon="alert", about="Open invoices past their due date, gross, as of today",
        drill=(("entity", "invoice"), ("overdue", "true"), ("dated", "false"))),
    Kpi("po_coverage", "Spend on a purchase order", "pct", lambda w: fa.po_coverage(w.rows("invoiced")),
        ("invoice.purchase_order_id",), good="up", icon="check-circle",
        about="The share of invoiced value that names a purchase order (no order, no pay: PROC-06)"),
    Kpi("first_time_match", "First-time match", "pct", lambda w: fa.first_time_match_rate(w.rows("invoiced")),
        ("invoice.match_status",), good="up", icon="check",
        about="The share of invoices that matched their order and receipt without an exception (PROC-01)"),
    Kpi("contracted_spend", "Spend under contract", "pct",
        lambda w: fa.contracted_spend(w.rows("spend"), _contracted(w.book)), ("invoice", "supplier"), good="up",
        icon="shield", about="The share of spend with suppliers that have a contract in force"),
    Kpi("maverick_spend", "Maverick spend", "pct",
        lambda w: fa.maverick_spend(w.rows("spend"), _contracted(w.book)), ("invoice.purchase_order_id", "supplier"),
        good="down", icon="flag", about="The share of spend bought without an order or outside a contracted supplier"),
    Kpi("on_time_payment", "Paid on time", "pct", lambda w: fa.on_time_payment(w.rows("paid")), ("invoice.paid_at",),
        good="up", icon="clock", about="The share of invoices paid in the period that were paid by their due date"),
    Kpi("dpo", "Days payable outstanding", "days",
        lambda w: fa.days_payable_outstanding(w.total("payables"), w.total("invoiced"), w.days()), ("invoice",),
        icon="calendar", about="Open payables ÷ invoiced value in the period × the days in the period"),
    Kpi("discount_capture", "Discounts captured", "pct",
        lambda w: fa.discount_capture(w.rows("paid"))["capture_pct"], ("invoice.discount_available",), good="up",
        icon="tag", about="Early payment discounts taken as a share of those on offer, on invoices paid in the period (FIN-04)"),
    Kpi("discounts_missed", "Discounts missed", "money",
        lambda w: fa.discount_capture(w.rows("paid"))["missed"], ("invoice.discount_available",), good="down",
        icon="tag", about="Early payment discounts on offer that were not taken, on invoices paid in the period"),
    Kpi("invoice_cycle", "Invoice approval time", "days",
        lambda w: _cycle(w.rows("invoiced"), "received_at", "approved_at"), ("invoice.approved_at", "invoice.received_at"),
        good="down", icon="history", about="Average days from an invoice arriving to its approval"),
    Kpi("requisition_cycle", "Requisition approval time", "days",
        lambda w: _cycle(w.rows("requisitions"), "submitted_at", "approved_at"),
        ("requisition.approved_at", "requisition.submitted_at"), good="down", icon="history",
        about="Average days from a requisition being submitted to its approval"),
    Kpi("otif", "On time, in full", "pct", lambda w: fa.otif(_receipts_of(w)), ("goods_receipt.on_time",), good="up",
        icon="truck", about="The share of receipts in the period that arrived on time and complete"),
    Kpi("price_variance", "Purchase price variance", "money",
        lambda w: fa.price_variance_total(_lines_of(w))["variance"], ("purchase_order_line.standard_price", "purchase_order"),
        good="down", icon="activity", about="(Price paid − standard price) × quantity, on orders placed in the period (PROC-08)"),
    Kpi("savings_identified", "Savings identified", "money", lambda w: _money(w.total("savings")),
        ("savings_initiative",), good="up", icon="sparkles", about=MEASURES["savings"].about),
    Kpi("savings_realised", "Savings realised", "money", lambda w: _money(w.total("realised_savings")),
        ("savings_initiative.realised_saving",), good="up", icon="check-circle", about=MEASURES["realised_savings"].about),
    Kpi("exceptions", "Invoices held", "count",
        lambda w: sum(1 for r in w.rows("payables") if r.status == "exception"), ("invoice",), good="down",
        position=True, icon="alert", about="Invoices in exception, waiting for someone to resolve them",
        drill=(("entity", "invoice"), ("status", "exception"), ("dated", "false"))),
    Kpi("suppliers", "Active suppliers", "count",
        lambda w: len({get(r, "supplier_id") for r in w.rows("spend")}), ("invoice",), icon="building",
        about="Suppliers invoiced in the period"),
    Kpi("high_risk", "High-risk suppliers", "count",
        lambda w: sum(1 for s in w.book.all("supplier") if get(s, "risk_rating", "") == "high"
                      and get(s, "status", "") not in ("retired", "prospective")),
        ("supplier.risk_rating",), good="down", position=True, icon="shield",
        about="Suppliers rated high risk (PROC-05) that are not retired"),
    Kpi("expiring", "Contracts to decide on", "count", _expiring, ("contract",), good="down", position=True,
        icon="file", about="Contracts ending within 90 days or past their notice date (PROC-07)"),
)


# Other names people give the same figures.
KPI_ALIASES = {
    "variance": "budget_variance", "budget_vs_actual": "budget_variance", "available": "budget_available",
    "remaining": "budget_available", "budget_remaining": "budget_available", "utilisation": "budget_used",
    "utilization": "budget_used", "budget_utilisation": "budget_used", "budget_utilization": "budget_used",
    "open_payables": "payables", "accounts_payable": "payables", "overdue_payables": "overdue",
    "open_commitments": "commitments", "committed": "commitments", "ordered": "orders", "total_spend": "spend",
    "match_rate": "first_time_match", "first_time_match_rate": "first_time_match", "exception_rate": "exceptions",
    "invoices_held": "exceptions", "held": "exceptions", "on_time": "on_time_payment", "paid_on_time": "on_time_payment",
    "days_payable_outstanding": "dpo", "discounts": "discount_capture", "discounts_captured": "discount_capture",
    "missed_discounts": "discounts_missed", "spend_under_contract": "contracted_spend", "maverick": "maverick_spend",
    "active_suppliers": "suppliers", "supplier_count": "suppliers", "high_risk_suppliers": "high_risk",
    "contracts_expiring": "expiring", "expiring_contracts": "expiring", "renewals": "expiring",
    "savings": "savings_identified", "realised_savings": "savings_realised", "ppv": "price_variance",
    "pending_approvals": "awaiting_approval", "pending": "awaiting_approval", "approval_time": "requisition_cycle",
    "cycle_time": "invoice_cycle", "on_time_in_full": "otif",
}


def _available(book: Book, needs: tuple[str, ...]) -> bool:
    for need in needs:
        table, _, column = need.partition(".")
        if not book.has(table) or (column and column not in book.columns(table)):
            return False
    return True


def _favourable(kpi: Kpi, change: float | None) -> bool | None:
    if not kpi.good or change is None or change == 0:
        return None
    return (change > 0) == (kpi.good == "up")


@router.get("/kpis")
def get_kpis(keys: str = "", spark: int = 6, db: Session = Depends(get_session),
             scope: Scope = Depends(requested)) -> dict[str, Any]:
    """Every headline figure the data allows, or the ones named in ?keys=spend,po_coverage."""
    book = Book(db, scope)
    known = {k.key: k for k in KPIS}
    asked = [k.strip() for k in keys.split(",") if k.strip()]
    wanted = list(dict.fromkeys(KPI_ALIASES.get(k.lower(), k.lower()) for k in asked))
    # A figure the library does not have is left out and named, so a dashboard that asks for
    # one too many still shows the rest.
    unknown = [k for k in wanted if k not in known]
    wanted = [k for k in wanted if k in known]
    now = Window(book, scope.start, scope.end)
    before = Window(book, *scope.prior) if scope.prior else None
    months = [Window(book, a, min(b, scope.end)) for a, b in scope.calendar.last("month", max(0, min(spark, 24)), scope.end)] \
        if spark else []
    out = []
    for kpi in ([known[k] for k in wanted] if wanted else KPIS):
        if not _available(book, kpi.needs):
            continue
        value = kpi.value(now)
        item: dict[str, Any] = {"key": kpi.key, "label": kpi.label, "unit": kpi.unit, "value": value, "good": kpi.good,
                                "about": kpi.about, "icon": kpi.icon, "position": kpi.position,
                                "drill": dict(kpi.drill) or None, "prior": None, "change": None, "change_pct": None,
                                "favourable": None, "spark": []}
        if not kpi.position:
            if before is not None:
                prior = kpi.value(before)
                item["prior"] = prior
                if value is not None and prior is not None:
                    change = round(float(value) - float(prior), 2)
                    item["change"] = change
                    # A percentage moves in points; an amount moves by a share of what it was.
                    item["change_pct"] = round(change, 1) if kpi.unit == "pct" else money.pct(change, abs(D(prior)))
                    item["favourable"] = _favourable(kpi, change)
            item["spark"] = [{"label": scope.calendar.label("month", w.start), "value": kpi.value(w)} for w in months]
        out.append(item)
    return {"scope": scope.describe(), "kpis": out, "unknown": unknown, "known": list(known) if unknown else []}


# ----------------------------------------------------------------- breakdowns and trends

@router.get("/breakdown")
def get_breakdown(measure: str = "spend", by: str = "supplier", top: int = 0, db: Session = Depends(get_session),
                  scope: Scope = Depends(requested)) -> dict[str, Any]:
    """A measure by a dimension, largest first (periods in order), each with its share and the comparison."""
    book, m = Book(db, scope), measure_of(measure)
    if not allowed(m.table, f"see {m.label.lower()}"):
        return {"scope": scope.describe(), "available": False, "measure": m.key, "label": m.label, "by": by,
                "total": 0.0, "count": 0, "items": []}
    key, names = dimension(book, by, m.table, m.date)
    value = valuer(book, m)
    items = _labelled(fa.group_sum(facts(book, m, scope.start, scope.end), key, value, names=names), names)
    if m.dated and scope.prior:
        prior = {i["key"]: i["value"] for i in fa.group_sum(facts(book, m, *scope.prior), key, value, names=names)}
        if by in TIME:
            prior = {}                      # a period has no earlier self; the trend compares periods
        for i in items:
            i["prior"] = prior.get(i["key"])
            i["change_pct"] = money.pct(D(i["value"]) - D(i["prior"]), D(i["prior"])) if i["prior"] else None
    if by in TIME:
        items.sort(key=lambda i: str(i["key"]))
    elif top and len(items) > top:
        rest = items[top:]
        items = items[:top] + [{"key": None, "label": f"Other ({len(rest)})", "other": True,
                                "value": _money(sum((D(r["value"]) for r in rest), ZERO)),
                                "count": sum(r["count"] for r in rest),
                                "share_pct": round(sum((r["share_pct"] or 0) for r in rest), 1),
                                "prior": None, "change_pct": None}]
    whole = sum((D(i["value"]) for i in items), ZERO)
    return {"scope": scope.describe(), "measure": m.key, "label": m.label, "by": by, "total": _money(whole),
            "count": sum(i["count"] for i in items), "items": items}


@router.get("/concentration")
def get_concentration(measure: str = "spend", by: str = "supplier", db: Session = Depends(get_session),
                      scope: Scope = Depends(requested)) -> dict[str, Any]:
    book, m = Book(db, scope), measure_of(measure)
    if not allowed(m.table, f"see {m.label.lower()}"):
        return {"scope": scope.describe(), "available": False, "measure": m.key, "label": m.label, "by": by,
                **fa.concentration([], "id")}
    key, names = dimension(book, by, m.table, m.date)
    out = fa.concentration(facts(book, m, scope.start, scope.end), key, valuer(book, m), names=names)
    out["items"] = _labelled(out["items"], names)
    return {"scope": scope.describe(), "measure": m.key, "label": m.label, "by": by, **out}


@router.get("/trend")
def get_trend(measure: str = "spend", kind: str = "month", periods: int = 12, span: str = "",
              db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """A measure per month, quarter or fiscal year, with the budget and the same period a year before.
    The `periods` ending at the scope's last day, or (?span=range) exactly the periods of the scope."""
    if kind not in TIME:
        raise HTTPException(status_code=422, detail="kind is one of month, quarter, year")
    book, m = Book(db, scope), measure_of(measure)
    if not allowed(m.table, f"see {m.label.lower()}"):
        return {"scope": scope.describe(), "available": False, "measure": m.key, "label": m.label, "kind": kind,
                "points": [], "total": 0.0, "has_budget": False}
    cal = scope.calendar
    ranges = cal.periods(kind, scope.start, scope.end) if span == "range" \
        else cal.last(kind, max(1, min(periods, 60)), scope.end)
    value = valuer(book, m)
    budget = MEASURES["budget"] if m.key in ("spend", "invoiced", "orders") and book.has("budget_line") else None
    points, running, running_budget = [], ZERO, ZERO
    for start, end in ranges:
        rows = facts(book, m, start, end)
        amount = sum((value(r) for r in rows), ZERO)
        running += amount
        point: dict[str, Any] = {"label": cal.label(kind, start), "start": start.isoformat(), "end": end.isoformat(),
                                 "value": _money(amount), "count": len(rows), "cumulative": _money(running),
                                 "partial": end > scope.today >= start, "future": start > scope.today}
        point["prior"] = _money(total(book, m, *cal.year_ago(start, end)))
        if budget is not None:
            planned = total(book, budget, start, end)
            running_budget += planned
            point["budget"] = _money(planned)
            point["cumulative_budget"] = _money(running_budget)
        points.append(point)
    return {"scope": scope.describe(), "measure": m.key, "label": m.label, "kind": kind, "points": points,
            "total": _money(running), "has_budget": budget is not None}


@router.get("/pivot")
def get_pivot(measure: str = "spend", rows: str = "cost_center", columns: str = "month", top: int = 12,
              db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    book, m = Book(db, scope), measure_of(measure)
    if not allowed(m.table, f"see {m.label.lower()}"):
        return {"scope": scope.describe(), "available": False, "measure": m.key, "label": m.label, "row_by": rows,
                "column_by": columns, "columns": [], "rows": [], "totals": [], "total": 0.0}
    row_key, row_names = dimension(book, rows, m.table, m.date)
    col_key, col_names = dimension(book, columns, m.table, m.date)
    data = facts(book, m, scope.start, scope.end)
    order = None
    if columns in TIME:
        order = [a.isoformat() for a, _ in scope.calendar.periods(columns, scope.start, scope.end)]
    out = fa.pivot(data, row_key, col_key, valuer(book, m), row_names=row_names, column_names=col_names, column_order=order)
    out["rows"] = _labelled(out["rows"], row_names)[: max(1, top)] if top else _labelled(out["rows"], row_names)
    out["columns"] = _labelled(out["columns"], col_names)
    return {"scope": scope.describe(), "measure": m.key, "label": m.label, "row_by": rows, "column_by": columns, **out}


# -------------------------------------------------------------------------------- budget

BUDGET_BY = ("cost_center", "family", "department", "region", "category", "gl_account")


def _budget_rows(book: Book, by: str, scope: Scope) -> list[dict[str, Any]]:
    """Two questions per group. For the period: what was spent against its budget (the variance,
    FIN-07). For the fiscal year: what is left of the year's budget once what is spent and what
    is committed are taken off (the position, FIN-02), and where the year is heading."""
    if by not in BUDGET_BY:
        raise HTTPException(status_code=422, detail=f"a budget is read by one of {', '.join(BUDGET_BY)}")
    if not book.has("budget_line"):
        return []
    budget, spend, open_ = MEASURES["budget"], MEASURES["spend"], MEASURES["commitments"]
    b_key, names = dimension(book, by, "budget_line", "period_start")
    a_key = dimension(book, by, "invoice", "invoice_date")[0] if book.has("invoice") else None
    c_key = dimension(book, by, "purchase_order", "order_date")[0] if book.has("purchase_order") else None
    year = scope.calendar.bounds("year", scope.end)
    so_far = min(scope.end, scope.today, year[1])
    commitments = [o for o in facts(book, open_) if get(o, "order_date") and as_date(o.order_date) <= scope.end]
    # One pass per source, each keyed its own way, then brought together by the key they share.
    sums: dict[str, dict[Any, Decimal]] = {n: {} for n in ("budget", "actual", "year_budget", "year_actual", "committed")}
    for name, data, key, value in (
            ("budget", facts(book, budget, scope.start, scope.end), b_key, valuer(book, budget)),
            ("year_budget", facts(book, budget, *year), b_key, valuer(book, budget)),
            ("actual", facts(book, spend, scope.start, scope.end) if a_key else [], a_key, valuer(book, spend)),
            ("year_actual", facts(book, spend, year[0], so_far) if a_key else [], a_key, valuer(book, spend)),
            ("committed", commitments if c_key else [], c_key, valuer(book, open_))):
        for r in data:
            k = key(r)
            sums[name][k] = sums[name].get(k, ZERO) + value(r)
    elapsed = Decimal((so_far - year[0]).days + 1) / Decimal((year[1] - year[0]).days + 1)
    rows = []
    for k in set().union(*(set(v) for v in sums.values())):
        label = names[k] if names is not None and k in names else _words(k)
        rows.append({"key": k, "label": label,
                     **_budget_figures({n: v.get(k, ZERO) for n, v in sums.items()}, elapsed)})
    order = {"over": 0, "unbudgeted": 1, "watch": 2, "on_track": 3}
    return sorted(rows, key=lambda r: (order[r["status"]], -(r["variance"] or 0), str(r["label"])))


def _budget_figures(s: dict[str, Decimal], elapsed: Decimal) -> dict[str, Any]:
    v = fin.variance(s["actual"], s["budget"], "cost")
    position = fin.budget_position(s["year_budget"], s["year_actual"], s["committed"])
    forecast = money.quantize(s["year_actual"] / elapsed) if elapsed > 0 else None
    if s["budget"] <= 0 and s["actual"] > 0:
        status = "unbudgeted"
    elif v.amount > 0:
        status = "over" if v.material else "watch"
    else:
        status = "on_track"
    return {"budget": _money(s["budget"]), "actual": _money(s["actual"]), "variance": _money(v.amount),
            "variance_pct": v.pct, "favourable": v.favourable, "material": v.material,
            "used_pct": money.pct(s["actual"], s["budget"]), "status": status,
            "year_budget": _money(s["year_budget"]), "year_actual": _money(s["year_actual"]),
            "committed": _money(s["committed"]), "available": _money(position.remaining),
            "utilisation_pct": position.utilisation_pct, "position": position.status,
            "forecast": _money(forecast) if forecast is not None else None,
            "forecast_variance": _money(forecast - s["year_budget"]) if forecast is not None else None,
            "forecast_pct": money.pct(forecast, s["year_budget"]) if forecast is not None else None}


def _budget_totals(rows: list[dict[str, Any]], scope: Scope) -> dict[str, Any]:
    year = scope.calendar.bounds("year", scope.end)
    so_far = min(scope.end, scope.today, year[1])
    elapsed = Decimal((so_far - year[0]).days + 1) / Decimal((year[1] - year[0]).days + 1)
    sums = {n: sum((D(r[n]) for r in rows), ZERO) for n in ("budget", "actual", "year_budget", "year_actual", "committed")}
    return {**_budget_figures(sums, elapsed), "groups": len(rows), "elapsed_pct": round(float(elapsed) * 100, 1),
            "fiscal_year": scope.calendar.label("year", scope.end),
            "over": sum(1 for r in rows if r["status"] == "over"), "watch": sum(1 for r in rows if r["status"] == "watch"),
            "unbudgeted": sum(1 for r in rows if r["status"] == "unbudgeted"),
            "exceeded": sum(1 for r in rows if r["position"] == "exceeded")}


@router.get("/budget")
def get_budget(by: str = "cost_center", db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """Budget against actual. Per group, for the period: budget, actual, variance and whether it is
    over (adverse and material), to watch (adverse) or on track (FIN-07). For the fiscal year: the
    year's budget, spend so far, what is committed, what is left (FIN-02) and the run-rate forecast."""
    book = Book(db, scope)
    available = allowed("budget_line", "see the budget")
    rows = _budget_rows(book, by, scope)
    return {"scope": scope.describe(), "available": available, "by": by, "rows": rows, "totals": _budget_totals(rows, scope)}


@router.get("/waterfall")
def get_waterfall(by: str = "cost_center", top: int = 6, db: Session = Depends(get_session),
                  scope: Scope = Depends(requested)) -> dict[str, Any]:
    """The walk from budget to actual: the largest variances one by one, the rest together."""
    book = Book(db, scope)
    available = allowed("budget_line", "see the budget")
    rows = sorted(_budget_rows(book, by, scope), key=lambda r: (-abs(r["variance"]), str(r["label"])))
    totals = _budget_totals(rows, scope)
    steps = [{"key": r["key"], "label": r["label"], "value": r["variance"], "favourable": r["variance"] <= 0}
             for r in rows[:top] if r["variance"]]
    rest = sum((D(r["variance"]) for r in rows[top:]), ZERO)
    if rest:
        steps.append({"key": None, "label": f"Other ({len(rows[top:])})", "value": _money(rest), "favourable": rest <= 0})
    return {"scope": scope.describe(), "available": available, "by": by, "start": {"label": "Budget", "value": totals["budget"]},
            "steps": steps, "end": {"label": "Actual", "value": totals["actual"]}, "totals": totals}


# ---------------------------------------------------------------------- payables and flow

@router.get("/aging")
def get_aging(top: int = 8, db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """Open payables by how overdue they are, and the suppliers owed the most overdue."""
    book = Book(db, scope)
    available = allowed("invoice", "see what is owed")
    m = MEASURES["payables"]
    value, day = valuer(book, m), scope.today
    rows = [r for r in facts(book, m) if get(r, "due_date")]
    buckets = fa.aging(rows, amount=value, as_of=day)
    names = book.names("supplier")
    owed: dict[Any, dict[str, Any]] = {}
    for r in rows:
        bucket = fa.aging_bucket(r.due_date, day)
        entry = owed.setdefault(get(r, "supplier_id"), {"key": get(r, "supplier_id"), "count": 0, "total": ZERO,
                                                        "overdue": ZERO, "oldest_days": 0,
                                                        **{b: ZERO for b in fa.aging_buckets()}})
        entry["label"] = names.get(entry["key"], "Unassigned")
        entry[bucket] += value(r)
        entry["total"] += value(r)
        entry["count"] += 1
        if bucket != "Not due":
            entry["overdue"] += value(r)
            entry["oldest_days"] = max(entry["oldest_days"], days_overdue(r.due_date, day))
    suppliers = sorted(owed.values(), key=lambda e: (-e["overdue"], -e["total"]))[: max(1, top)]
    whole = sum((value(r) for r in rows), ZERO)
    late = sum((D(b["value"]) for b in buckets if b["overdue"]), ZERO)
    return {"scope": scope.describe(), "available": available, "as_of": day.isoformat(), "buckets": buckets, "total": _money(whole),
            "overdue": _money(late), "overdue_pct": money.pct(late, whole), "count": len(rows),
            "suppliers": [{k: (_money(v) if isinstance(v, Decimal) else v) for k, v in e.items()} for e in suppliers]}


@router.get("/funnel")
def get_funnel(db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """Purchase-to-pay, for what was requested (or, without requisitions, ordered) in the period."""
    book = Book(db, scope)
    stages: list[tuple[str, list[Any]]] = []
    orders: list[Any]
    if book.has("requisition"):
        raised = facts(book, MEASURES["requisitions"], scope.start, scope.end)
        approved = [r for r in raised if r.status in ("approved", "ordered")]
        ordered = [r for r in raised if r.status == "ordered" or get(r, "purchase_order_id")]
        stages += [("Requested", raised), ("Approved", approved), ("Ordered", ordered)]
        linked = {get(r, "purchase_order_id") for r in ordered if get(r, "purchase_order_id")}
        orders = [o for o in book.all("purchase_order") if o.id in linked]
        value = "amount"
    elif book.has("purchase_order"):
        orders = facts(book, MEASURES["orders"], scope.start, scope.end)
        stages.append(("Ordered", orders))
        value = "amount"
    else:
        return {"scope": scope.describe(), "available": False, "stages": []}
    if book.has("purchase_order") and (orders or not book.has("requisition")):
        invoices = [i for i in book.all("invoice") if get(i, "status", "") != "rejected"] if book.has("invoice") else []
        invoiced = {get(i, "purchase_order_id") for i in invoices}
        paid = {get(i, "purchase_order_id") for i in invoices if i.status == "paid"}
        stages.append(("Received", [o for o in orders if o.status in ("partially_received", "received", "closed")
                                    or D(get(o, "received_amount", 0)) > 0]))
        if book.has("invoice"):
            stages.append(("Invoiced", [o for o in orders if o.id in invoiced]))
            stages.append(("Paid", [o for o in orders if o.id in paid]))
    out = fa.funnel(stages, value)
    for i, stage in enumerate(out):
        before = out[i - 1]["count"] if i else None
        stage["of_previous_pct"] = round(100 * stage["count"] / before, 1) if before else None
    return {"scope": scope.describe(), "stages": out}


CYCLES = (
    ("requisition", "Requisition: submitted to approved", "submitted_at", "approved_at", "requisitions"),
    ("purchase_order", "Order: placed to delivered", "order_date", "delivered_at", "orders"),
    ("invoice", "Invoice: received to approved", "received_at", "approved_at", "invoiced"),
    ("invoice", "Invoice: approved to paid", "approved_at", "paid_at", "invoiced"),
    ("invoice", "Invoice: dated to paid", "invoice_date", "paid_at", "invoiced"),
)


@router.get("/cycle-times")
def get_cycle_times(db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    book = Book(db, scope)
    steps = []
    for table, label, start, end, measure in CYCLES:
        if not book.has(table) or not {start, end} <= book.columns(table):
            continue
        rows = facts(book, MEASURES[measure], scope.start, scope.end)
        now = fa.cycle_time(rows, start, end)
        prior = fa.cycle_time(facts(book, MEASURES[measure], *scope.prior), start, end) if scope.prior else None
        steps.append({"entity": table, "label": label, **now,
                      "prior_average_days": prior["average_days"] if prior else None})
    return {"scope": scope.describe(), "steps": steps}


# ------------------------------------------------------------------------------ worklists

def _names_for(book: Book, row: Any, out: dict[str, Any]) -> dict[str, Any]:
    for column, table, field in (("supplier_id", "supplier", "name"), ("cost_center_id", "cost_center", "name"),
                                 ("spend_category_id", "spend_category", "name"),
                                 ("purchase_order_id", "purchase_order", "reference"),
                                 ("contract_id", "contract", "reference")):
        if column in out and model(table) is not None and can(f"{table}:read"):
            out[column[:-3] + "_name" if field == "name" else column[:-3] + "_reference"] = \
                get(book.by_id(table).get(out[column]), field)
    return out


def document(book: Book, table: str, row: Any) -> dict[str, Any]:
    """A row as JSON with the names of what it refers to, and how overdue it is."""
    out = {c.key: getattr(row, c.key) for c in model(table).__table__.columns}
    _names_for(book, row, out)
    if table == "invoice" and out.get("due_date") and out.get("status") in OPEN_INVOICE:
        late = days_overdue(out["due_date"], book.scope.today)
        out["days_overdue"] = max(0, late)
        out["aging_bucket"] = fa.aging_bucket(out["due_date"], book.scope.today)
    return out


@router.get("/documents")
def get_documents(entity: str = "invoice", status: str = "", match_status: str = "", overdue: bool = False,
                  bucket: str = "", dated: bool = True, date: str = "", q: str = "", sort: str = "",
                  limit: int = 500, where: str = "", mine: bool = False, db: Session = Depends(get_session),
                  scope: Scope = Depends(requested)) -> dict[str, Any]:
    """The rows behind a number: an entity's documents in the scope, newest first.
    ?status=a,b  ?match_status=  ?overdue=true  ?bucket=31-60  ?dated=false (whatever the period)
    ?date=due_date (the date the period applies to)  ?where=buyer_name:Daniel Moreau  ?q=text  ?sort=-amount
    ?mine=true (the ones I raised, buy or own)"""
    if entity not in standard.ENTITIES:
        raise HTTPException(status_code=404, detail=f"{entity} is not one of {', '.join(standard.ORDER)}")
    if not allowed(entity):
        return {"scope": scope.describe(), "available": False, "entity": entity, "title": standard.ENTITIES[entity]["title"],
                "count": 0, "amount": None, "shown": 0, "rows": []}
    book = Book(db, scope)
    have = book.columns(entity)
    rows = book.all(entity)
    field = date or DATE_OF.get(entity, "")
    if date and date not in have:
        raise HTTPException(status_code=422, detail=f"{entity} has no column {date}")
    if dated and field in have:
        rows = [r for r in rows if getattr(r, field) is not None and scope.start <= as_date(getattr(r, field)) <= scope.end]
    for column, wanted in (("status", status), ("match_status", match_status)):
        if wanted and column in have:
            rows = [r for r in rows if _same(getattr(r, column), _ids(wanted))]
    rows = _mine(rows, entity, have) if mine else rows
    for clause in [c for c in where.split(";") if ":" in c]:
        column, _, wanted = clause.partition(":")
        key = dimension(book, column.strip(), entity, field)[0]
        rows = [r for r in rows if str(key(r) if key(r) is not None else "").lower() == wanted.strip().lower()]
    if (overdue or bucket) and "due_date" in have:
        rows = [r for r in rows if r.due_date and get(r, "status", "") in OPEN_INVOICE]
        if overdue:
            rows = [r for r in rows if days_overdue(r.due_date, scope.today) > 0]
        if bucket:
            rows = [r for r in rows if fa.aging_bucket(r.due_date, scope.today) == bucket]
    if q:
        needle = q.lower()
        names = {t: book.names(t) for t in ("supplier", "cost_center") if model(t) is not None}

        def text(r: Any) -> str:
            parts = [str(getattr(r, c)) for c in have if isinstance(getattr(r, c), str)]
            parts.append(names.get("supplier", {}).get(get(r, "supplier_id"), ""))
            return " ".join(parts).lower()
        rows = [r for r in rows if needle in text(r)]
    column = sort.lstrip("-") or (field if field in have else "id")
    if column not in have:
        raise HTTPException(status_code=422, detail=f"{entity} has no column {column} to sort by")
    known = [r for r in rows if getattr(r, column) is not None]
    numeric = all(isinstance(getattr(r, column), (int, float)) and not isinstance(getattr(r, column), bool) for r in known)
    known.sort(key=lambda r: getattr(r, column) if numeric else str(getattr(r, column)),
               reverse=sort.startswith("-") or not sort)
    rows = known + [r for r in rows if getattr(r, column) is None]
    amount = AMOUNT_OF.get(entity)
    whole = sum((book.in_base(r, get(r, amount, 0)) for r in rows), ZERO) if amount in have else None
    limit = max(1, min(limit, 5000))
    return {"scope": scope.describe(), "entity": entity, "title": standard.ENTITIES[entity]["title"],
            "count": len(rows), "amount": _money(whole) if whole is not None else None, "shown": min(limit, len(rows)),
            "rows": [document(book, entity, r) for r in rows[:limit]]}


def _mine(rows: list[Any], entity: str, have: set[str]) -> list[Any]:
    """The records of the person asking: the ones they requested, buy, received or own."""
    column = OWNER_OF.get(entity)
    if not column or column not in have:
        return rows
    me = str(current().name or "").strip().lower()
    return [r for r in rows if str(getattr(r, column) or "").strip().lower() == me]


@router.get("/worklist")
def get_worklist(entity: str = "requisition", mine: bool = False, db: Session = Depends(get_session),
                 scope: Scope = Depends(requested)) -> dict[str, Any]:
    """How many of an entity's records are in each state, whatever the period: what the tabs of a
    work screen count. ?mine=true counts only the ones I raised, buy or own."""
    if entity not in standard.ENTITIES:
        raise HTTPException(status_code=404, detail=f"{entity} is not one of {', '.join(standard.ORDER)}")
    title = standard.ENTITIES[entity]["title"]
    if not allowed(entity):
        return {"entity": entity, "title": title, "available": False, "count": 0, "amount": None, "statuses": []}
    book = Book(db, scope)
    have = book.columns(entity)
    rows = _mine(book.all(entity), entity, have) if mine else book.all(entity)
    amount = AMOUNT_OF.get(entity)
    counted: dict[str, list[Any]] = {}
    for r in rows:
        found = counted.setdefault(str(get(r, "status", "") or ""), [0, ZERO])
        found[0] += 1
        found[1] += book.in_base(r, get(r, amount, 0)) if amount in have else ZERO
    order = list(standard.STATES.get(entity, [])) + sorted(k for k in counted if k not in standard.STATES.get(entity, []))
    return {"entity": entity, "title": title, "available": True, "mine": mine, "count": len(rows),
            "amount": _money(sum((v[1] for v in counted.values()), ZERO)) if amount in have else None,
            "statuses": [{"key": k, "label": _words(k) if k else "Not set", "count": counted[k][0],
                          "amount": _money(counted[k][1]) if amount in have else None} for k in order if k in counted]}


@router.get("/exceptions")
def get_exceptions(db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """Invoices held: why, how much and for how long."""
    available = allowed("invoice", "see invoices")
    book = Book(db, scope)
    held = [r for r in book.all("invoice") if get(r, "status", "") == "exception"]
    day = scope.today
    rows = []
    for r in held:
        out = document(book, "invoice", r)
        arrived = as_date(get(r, "received_at") or get(r, "invoice_date"))
        out["days_held"] = max(0, (day - arrived).days) if arrived else None
        rows.append(out)
    rows.sort(key=lambda r: -(r["days_held"] or 0))
    reasons = _labelled(fa.group_sum(held, lambda r: get(r, "match_status") or "unmatched",
                                     lambda r: book.in_base(r, get(r, "amount", 0))), None)
    return {"scope": scope.describe(), "available": available, "count": len(rows), "amount": _money(sum((D(r["value"]) for r in reasons), ZERO)),
            "oldest_days": max([r["days_held"] or 0 for r in rows], default=0), "reasons": reasons, "rows": rows}


@router.get("/accruals")
def get_accruals(db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """Goods received and not invoiced, per open order: what is accrued at the period end (FIN-08)."""
    available = allowed("purchase_order", "see purchase orders")
    book = Book(db, scope)
    orders = book.by_id("purchase_order")
    rows = []
    for a in fin.accruals(book.all("purchase_order"), book.base):
        order = orders.get(a["purchase_order_id"])
        rows.append(_names_for(book, order, {**a, "supplier_id": get(order, "supplier_id"),
                                             "cost_center_id": get(order, "cost_center_id"),
                                             "received": get(order, "received_amount", 0),
                                             "invoiced": get(order, "invoiced_amount", 0),
                                             "order_date": get(order, "order_date"), "status": get(order, "status")}))
    return {"scope": scope.describe(), "available": available, "count": len(rows),
            "amount": _money(sum((D(r["accrual"]) for r in rows), ZERO)), "rows": rows}


@router.get("/renewals")
def get_renewals(within: int = 180, db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """Contracts ending within `within` days, the soonest decision first (PROC-07)."""
    available = allowed("contract", "see contracts")
    book = Book(db, scope)
    rows = []
    for c in book.all("contract"):
        if get(c, "status", "") in ("draft", "terminated") or not get(c, "end_date"):
            continue
        r = fin.renewal(c.end_date, scope.today, get(c, "notice_days", 0), bool(get(c, "auto_renew", False)))
        if r.days_left > within or r.days_left < -within:
            continue
        rows.append({**document(book, "contract", c), "renewal": r.status, "days_left": r.days_left,
                     "decide_by": r.decide_by, "note": r.note})
    rows.sort(key=lambda r: (r["decide_by"], r["days_left"]))
    value = sum((book.in_base(r, r.get("annual_value") or r.get("value") or 0) for r in rows), ZERO)
    return {"scope": scope.describe(), "available": available, "within_days": within, "count": len(rows), "annual_value": _money(value),
            "by_status": _labelled(fa.count_by(rows, lambda r: r["renewal"],
                                               order=["expired", "notice_due", "expiring", "active"]), None),
            "rows": rows}


@router.get("/controls")
def get_controls(days: int = 90, db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """The controls a finance team watches, over the last `days`: what each found, and the documents."""
    book = Book(db, scope)
    since = scope.today - dt.timedelta(days=max(1, days))
    out: list[dict[str, Any]] = []

    def add(key: str, rule: str, label: str, about: str, severity: str, rows: list[dict[str, Any]],
            amount: Decimal | None = None) -> None:
        out.append({"key": key, "rule": rule, "label": label, "about": about, "severity": severity if rows else "ok",
                    "count": len(rows), "amount": _money(amount) if amount is not None else None, "rows": rows[:50]})

    if book.has("invoice"):
        invoices = [i for i in book.all("invoice") if get(i, "status", "") != "rejected"]
        recent = [i for i in invoices if get(i, "invoice_date") and as_date(i.invoice_date) >= since]
        if "supplier_invoice_number" in book.columns("invoice"):
            by_supplier: dict[Any, list[Any]] = {}
            for i in invoices:
                by_supplier.setdefault(get(i, "supplier_id"), []).append(i)
            pairs, seen = [], set()
            for i in recent:
                for found in fin.duplicate_invoices(i, by_supplier.get(get(i, "supplier_id"), [])):
                    other = found["invoice"]
                    pair = tuple(sorted((i.id, other.id)))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    pairs.append({**document(book, "invoice", i), "confidence": found["confidence"],
                                  "reason": found["reason"], "other_id": other.id,
                                  "other_reference": get(other, "reference", "")})
            add("duplicates", "PROC-03", "Possible duplicate invoices",
                f"The same supplier and number, or the same supplier and amount within {fin.POLICY.duplicate_days} days",
                "down", pairs,
                sum((D(p.get("amount") or 0) for p in pairs), ZERO))
        if "purchase_order_id" in book.columns("invoice"):
            bare = [i for i in recent if not get(i, "purchase_order_id") and fin.po_required(get(i, "amount", 0))]
            add("no_order", "PROC-06", "Invoices without a purchase order",
                f"Invoices above {money.fmt(fin.POLICY.po_required_above, book.base)} that name no order", "warn",
                [document(book, "invoice", i) for i in bare], sum((D(get(i, "amount", 0)) for i in bare), ZERO))
    if book.has("requisition"):
        requests = [r for r in book.all("requisition") if get(r, "created_at") and as_date(r.created_at) >= since]
        limit = fin.first_limit()
        splits = [{"requester_name": s["requester"], "supplier_id": s["supplier_id"], "total": s["total"],
                   "count": len(s["requests"]), "references": [get(r, "reference", "") for r in s["requests"]],
                   "supplier_name": book.names("supplier").get(s["supplier_id"]) if book.has("supplier") else None}
                  for s in fin.split_orders(requests, limit)]
        add("splits", "PROC-11", "Possible split requests",
            f"Requests by one person to one supplier within {fin.POLICY.split_days} days, each under {money.fmt(limit, book.base)} and "
            "together above it", "warn", splits, sum((D(s["total"]) for s in splits), ZERO))
        if {"requester_name", "approver_name"} <= book.columns("requisition"):
            own = [r for r in requests if get(r, "approver_name") and str(r.approver_name).strip().lower()
                   == str(get(r, "requester_name", "")).strip().lower()]
            add("self_approval", "FIN-01", "Requests approved by their requester",
                "Segregation of duties: nobody approves their own request", "down",
                [document(book, "requisition", r) for r in own], sum((D(get(r, "amount", 0)) for r in own), ZERO))
    if book.has("purchase_order") and book.has("supplier"):
        suppliers = book.by_id("supplier")
        risky = [o for o in book.all("purchase_order") if get(o, "status", "") in ("pending_approval", *OPEN_ORDER)
                 and str(get(suppliers.get(get(o, "supplier_id")), "status", "")).lower() not in fin.POLICY.orderable]
        add("unapproved_supplier", "PROC-09", "Open orders with a supplier that is not approved",
            "Only approved or active suppliers can be ordered from", "down",
            [{**document(book, "purchase_order", o),
              "supplier_status": get(suppliers.get(get(o, "supplier_id")), "status")} for o in risky],
            sum((D(get(o, "amount", 0)) for o in risky), ZERO))
    if book.has("budget_line") and book.has("invoice"):
        year = Scope(period="fy_to_date", compare="none").narrowed(**scope.filters)
        over = [r for r in _budget_rows(Book(db, year), "cost_center", year) if r["status"] in ("over", "unbudgeted")]
        add("over_budget", "FIN-07", "Cost centres over budget",
            f"Spend for the year to date above its budget by {fin.POLICY.material_pct:g}% or more", "down", over,
            sum((D(r["variance"]) for r in over), ZERO))
    return {"scope": scope.describe(), "since": since.isoformat(), "controls": out,
            "findings": sum(c["count"] for c in out)}


# ------------------------------------------------------------------------------ suppliers

@router.get("/suppliers/{supplier_id}/scorecard")
def get_scorecard(supplier_id: int, db: Session = Depends(get_session), scope: Scope = Depends(requested)) -> dict[str, Any]:
    """One supplier: what is spent with it, how it delivers, what it is owed, its risk and its contracts."""
    allowed("supplier", "see suppliers")
    everyone = Book(db, scope)
    supplier = everyone.by_id("supplier").get(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail=f"supplier {supplier_id} not found")
    book = Book(db, scope.narrowed(supplier_id={supplier_id}))
    now = Window(book, scope.start, scope.end)
    spend = now.total("spend")
    category = get(supplier, "spend_category_id")
    peers = ZERO
    if category and everyone.has("invoice"):
        value = valuer(everyone, MEASURES["spend"])
        peers = sum((value(r) for r in facts(everyone, MEASURES["spend"], scope.start, scope.end)
                     if get(r, "spend_category_id") == category), ZERO)
    share = money.pct(spend, peers) if peers > 0 else None
    receipts = _receipts_of(now)
    delivered = fa.otif(receipts)
    quality = fa.share(receipts, lambda r: bool(get(r, "quality_ok", True)), amount=None) \
        if "quality_ok" in book.columns("goods_receipt") else None
    otif_pct = delivered if delivered is not None else get(supplier, "otif_pct", 100)
    quality_pct = quality if quality is not None else get(supplier, "quality_pct", 100)
    contracts = [{**document(book, "contract", c),
                  "renewal": fin.renewal(c.end_date, scope.today, get(c, "notice_days", 0),
                                         bool(get(c, "auto_renew", False))).status if get(c, "end_date") else None}
                 for c in book.all("contract")]
    under = any(c["status"] in ("signed", "active", "expiring") for c in contracts) or bool(get(supplier, "is_contracted", False))
    risk = fin.supplier_risk(otif_pct=otif_pct, quality_pct=quality_pct,
                             financial_health_pct=get(supplier, "financial_health_pct", 100),
                             compliance_pct=100 if under else 70, spend_share_pct=share or 0)
    stored = get(supplier, "risk_score")
    kpis = {k: v for k, v in {
        "spend": _money(spend), "prior_spend": _money(Window(book, *scope.prior).total("spend")) if scope.prior else None,
        "invoices": len(now.rows("spend")), "orders": _money(now.total("orders")),
        "open_payables": _money(now.total("payables")), "overdue": _money(_overdue(now)),
        "share_of_category_pct": share, "otif_pct": otif_pct, "quality_pct": quality_pct,
        "first_time_match_pct": fa.first_time_match_rate(now.rows("invoiced")),
        "on_time_payment_pct": fa.on_time_payment(now.rows("paid")),
        "po_coverage_pct": fa.po_coverage(now.rows("invoiced")),
    }.items()}
    trend = []
    value = valuer(book, MEASURES["spend"])
    for start, end in scope.calendar.last("month", 12, scope.end):
        trend.append({"label": scope.calendar.label("month", start), "start": start.isoformat(),
                      "value": _money(sum((value(r) for r in facts(book, MEASURES["spend"], start, end)), ZERO))})
    return {"scope": scope.describe(), "supplier": document(book, "supplier", supplier), "kpis": kpis,
            "risk": {"score": stored if stored is not None else risk.score,
                     "rating": get(supplier, "risk_rating") or risk.rating, "parts": risk.parts,
                     "weights": fin.RISK_WEIGHTS, "computed_score": risk.score, "computed_rating": risk.rating},
            "contracts": contracts, "trend": trend,
            "by_category": _labelled(fa.group_sum(now.rows("spend"), "spend_category_id", value,
                                                  names=book.names("spend_category")), book.names("spend_category"))}


# ----------------------------------------------------------------------------- operations

class Receipt(BaseModel):
    amount: float
    quantity: float | None = None
    received_by: str = ""
    quality_ok: bool = True


class RunRequest(BaseModel):
    run_date: str = ""
    due_by: str = ""
    take_discounts: bool = True
    method: str = "bacs"


@router.post("/invoices/{invoice_id}/match")
def post_match(invoice_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Match an invoice to its order and receipts, and move it to matched or to exception."""
    ensure("invoice:match", what="match invoices")
    return ops.match_invoice(db, invoice_id)


@router.get("/invoices/{invoice_id}/match")
def get_match(invoice_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    """What matching the invoice would find, without moving it."""
    ensure("invoice:read", what="see invoices")
    out = ops.match_invoice(db, invoice_id, move=False, commit=False)
    db.rollback()
    return out


@router.post("/purchase-orders/{order_id}/receive")
def post_receive(order_id: int, payload: Receipt, db: Session = Depends(get_session)) -> dict[str, Any]:
    ensure("goods_receipt:create", what="receive goods")
    return ops.receive_goods(db, order_id, payload.amount, quantity=payload.quantity,
                             received_by=payload.received_by or current().name, quality_ok=payload.quality_ok)


@router.get("/payment-runs/payable")
def get_payable(due_by: str = "", db: Session = Depends(get_session)) -> dict[str, Any]:
    if model("invoice") is None:
        return {"available": False, "count": 0, "amount": 0.0, "discounts": 0.0, "rows": []}
    ensure("invoice:read", what="see invoices")
    book = Book(db, Scope(compare="none"))
    items = ops.payable(db, due_by=due_by or None)
    rows = [{**{k: v for k, v in i.items() if k != "invoice"},
             "supplier_name": book.names("supplier").get(i["supplier_id"]) if book.has("supplier") else None}
            for i in items]
    return {"available": True, "count": len(rows), "amount": _money(sum((D(r["pay"]) for r in rows), ZERO)),
            "discounts": _money(sum((D(r["discount"]) for r in rows), ZERO)), "rows": rows}


@router.post("/payment-runs/propose")
def post_propose(payload: RunRequest | None = None, db: Session = Depends(get_session)) -> dict[str, Any]:
    ensure("payment_run:create", what="propose a payment run")
    payload = payload or RunRequest()
    return ops.propose_payment_run(db, run_date=payload.run_date or None, due_by=payload.due_by or None,
                                   take_discounts=payload.take_discounts, method=payload.method)


@router.get("/budget/position")
def get_position(cost_center_id: int | None = None, requested: float = 0, spend_category_id: int | None = None,
                 on: str = "", db: Session = Depends(get_session)) -> dict[str, Any]:
    """What is left of a cost centre's budget for the year, and what a request of `requested` would leave."""
    if cost_center_id is None or model("budget_line") is None:
        return {"has_budget": False, "status": "ok", "budget": 0.0, "available": 0.0, "remaining": 0.0,
                "message": "Name a cost centre: ?cost_center_id=3" if cost_center_id is None else "There is no budget table"}
    ensure("budget_line:read", what="see the budget")
    return {"has_budget": True, **ops.budget_position(db, cost_center_id, requested=requested, on=on or None,
                                                     spend_category_id=spend_category_id)}


@router.get("/requisitions/{requisition_id}/advice")
def get_advice(requisition_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    ensure("requisition:read", what="see requisitions")
    return ops.check_request(db, requisition_id)


class NewRequisition(BaseModel):
    title: str
    amount: float
    cost_center_id: int | None = None
    spend_category_id: int | None = None
    supplier_id: int | None = None
    justification: str = ""
    needed_by: str | None = None


class Order(BaseModel):
    supplier_id: int | None = None
    expected_delivery: str | None = None


@router.post("/requisitions", status_code=201)
def post_requisition(payload: NewRequisition, db: Session = Depends(get_session)) -> dict[str, Any]:
    """A draft requisition, with its reference and its requester; it is submitted through its workflow."""
    ensure("requisition:create", what="raise a requisition")
    req = ops.create_requisition(db, payload.model_dump())
    return document(Book(db, Scope(compare="none")), "requisition", req)


@router.post("/requisitions/{requisition_id}/order")
def post_order(requisition_id: int, payload: Order | None = None, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Raise the purchase order of an approved requisition."""
    ensure("requisition:order", what="raise an order")
    payload = payload or Order()
    return ops.raise_order(db, requisition_id, supplier_id=payload.supplier_id, expected_delivery=payload.expected_delivery)


@router.post("/purchase-orders/{order_id}/send")
def post_send(order_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
    """Send an approved order to the supplier and create it in the ERP."""
    ensure("purchase_order:send", what="send an order")
    return ops.send_order(db, order_id)


@router.get("/approvals")
def get_approvals(entity: str = "", mine: bool = True, db: Session = Depends(get_session)) -> dict[str, Any]:
    """What waits for a decision: each approval with its record, and whether this person may decide it.
    ?mine=false lists every one; ?entity=requisition only those."""
    book = Book(db, Scope(compare="none"))
    rows = []
    for item in ops.waiting(db, entity):
        if not can(f"{item['entity']}:read") or (mine and not item["can_decide"]):
            continue
        rec = item.pop("record")
        asked = item.pop("title")
        rows.append({**document(book, item["entity"], rec), **item, "approval_title": asked, "id": rec.id})
    amount = sum((book.in_base(r, r.get("amount") or r.get("value") or 0) for r in rows), ZERO)
    return {"count": len(rows), "amount": _money(amount), "overdue": sum(1 for r in rows if r["overdue"]), "rows": rows}
