"""The rules every finance and procurement function runs on. Written by Poiesis, and read-only.

Each is one pure function with an id (`FIN-…` for finance, `PROC-…` for procurement),
registered in the application's rule catalogue and proven by tests/test_finance_library.py.

The numbers an organisation sets for itself (approval limits, tolerances, thresholds) have
one home, `POLICY`, which an application sets once from its brief:

    from ..finance import rules as fin

    fin.configure(
        doa=[(2_000, "budget_holder"), (20_000, "head_of_department"), (None, "cfo")],     # BR-01
        tolerance=fin.Tolerance(price_pct=1, quantity_pct=0, amount_abs=25),                 # BR-05
        po_required_above=500,                                                               # BR-06
    )

Every rule reads its number from there unless it is passed one, and so do the lifecycles
(who approves which amount), the operations (what matches) and the insight API (what the
controls flag): the application, its screens and its dashboards work to the same numbers.
The brief's own rule is then the library's under the brief's id:

    @rule("BR-05", "An invoice matches within 1% and £25", source="BRD 4", kind="validation")
    def invoice_matches(order, receipts, invoice):
        return fin.three_way_match(order, receipts, invoice)

Records may be ORM rows, dicts or SimpleNamespace objects; amounts any number. Nothing
here reads the database, the clock or the network: pass `as_of`.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Sequence

from ..kernel.rules import check, rule
from . import money
from .money import D
from .periods import add_months, as_date, days_overdue, end_of_month

SOURCE = "Poiesis finance library"


def _p(value: Any, name: str) -> Any:
    """The value a rule was passed, or the organisation's own from POLICY."""
    return getattr(POLICY, name) if value is None else value


def get(record: Any, name: str, default: Any = None) -> Any:
    """A field of a record, whether it is a row, a dict or a plain object."""
    if record is None:
        return default
    if isinstance(record, dict):
        value = record.get(name, default)
    else:
        value = getattr(record, name, default)
    return default if value is None else value


def _amounts(records: Iterable[Any], name: str = "amount") -> Decimal:
    return sum((D(get(r, name, 0)) for r in records or []), Decimal(0))


# =========================================================================== finance

# --- FIN-01 segregation of duties ---------------------------------------------------

SOD_CONFLICTS: tuple[tuple[str, str], ...] = (
    ("request", "approve"),                     # nobody approves what they asked for
    ("order", "receive"),                       # the buyer does not book the goods in
    ("approve_invoice", "release_payment"),     # approving an invoice and paying it are two people
    ("maintain_supplier", "approve_invoice"),   # whoever can create a supplier cannot approve its invoices
    ("maintain_supplier", "release_payment"),   # … nor pay it
)


@rule("FIN-01", "Segregation of duties: conflicting steps of one transaction are done by different people",
      statement="Request and approve, order and receive, approve an invoice and release its payment, and maintain a "
                "supplier and pay it, are each done by two different people.",
      source=SOURCE, kind="authorisation")
def check_segregation(duties: dict[str, Any], conflicts: Sequence[tuple[str, str]] = SOD_CONFLICTS) -> None:
    """`duties` maps a duty to who performed it: {"request": "Aisha Khan", "approve": "Marcus Lindqvist"}."""
    who = {k: str(v).strip().lower() for k, v in (duties or {}).items() if v not in (None, "")}
    for a, b in conflicts:
        check(not (a in who and b in who and who[a] == who[b]), "FIN-01",
              f"{duties.get(a)} cannot both {a.replace('_', ' ')} and {b.replace('_', ' ')} the same transaction; "
              "a second person must do one of them", duty=a, conflicts_with=b)


# --- FIN-02 budget availability -------------------------------------------------------

BUDGET_WARNING_PCT = 90      # utilisation at which a budget holder is warned


@dataclass(frozen=True)
class BudgetPosition:
    budget: Decimal
    actual: Decimal           # invoiced or paid
    committed: Decimal        # ordered, not yet invoiced
    requested: Decimal        # what is being asked for now
    available: Decimal        # budget − actual − committed, before this request
    remaining: Decimal        # … and after it
    utilisation_pct: float | None
    status: str               # ok | warning | exceeded

    def as_dict(self) -> dict[str, Any]:
        return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


@rule("FIN-02", "Budget availability: spend is checked against budget less actuals and commitments",
      statement="Available budget is the budget less what is invoiced and what is ordered but not yet invoiced. "
                "A request that takes utilisation to 90% warns; one that exceeds the budget is refused or escalated.",
      source=SOURCE, kind="validation")
def budget_position(budget: Any, actual: Any = 0, committed: Any = 0, requested: Any = 0,
                    warning_pct: float | None = None) -> BudgetPosition:
    warning_pct = _p(warning_pct, "budget_warning_pct")
    b, a, c, r = D(budget), D(actual), D(committed), D(requested)
    available = b - a - c
    remaining = available - r
    used = a + c + r
    utilisation = money.pct(used, b)
    if remaining < 0:
        status = "exceeded"
    elif b > 0 and used * 100 >= b * D(warning_pct):        # on the amounts: 89.99% is shown as 90.0 and is not 90
        status = "warning"
    else:
        status = "ok"
    return BudgetPosition(b, a, c, r, available, remaining, utilisation, status)


def check_budget(budget: Any, actual: Any = 0, committed: Any = 0, requested: Any = 0, currency: str = "GBP") -> BudgetPosition:
    """Refuse a request the budget cannot cover (a hard budget control)."""
    p = budget_position(budget, actual, committed, requested)
    check(p.status != "exceeded", "FIN-02",
          f"This takes the budget over by {money.fmt(-p.remaining, currency)}: {money.fmt(p.available, currency)} is "
          f"available and {money.fmt(p.requested, currency)} is asked for. Ask for a budget change, or reduce the request",
          available=float(p.available), requested=float(p.requested))
    return p


# --- FIN-03 payment terms, FIN-04 early payment discount ---------------------------------

@dataclass(frozen=True)
class Terms:
    code: str
    days: int = 30                 # days until due
    end_of_month: bool = False     # counted from the end of the invoice's month
    discount_pct: float = 0.0      # early payment discount
    discount_days: int = 0         # … when paid within this many days


_TERMS = re.compile(r"^(?:(?P<disc>\d+(?:\.\d+)?)\s*/\s*(?P<ddays>\d+)\s*)?(?P<kind>NET|EOM)?\s*(?P<days>\d+)?$")
_IMMEDIATE = {"COD", "PIA", "IMMEDIATE", "DUE ON RECEIPT", "ON RECEIPT", "CASH"}


def parse_terms(code: Any, default_days: int = 30) -> Terms:
    """NET30, "Net 45", 2/10NET30 (2% if paid in 10 days, else 30), EOM30, COD."""
    text = re.sub(r"\s+", " ", str(code or "").upper().replace("-", " ")).strip()
    if not text:
        return Terms(f"NET{default_days}", default_days)
    if text in _IMMEDIATE:
        return Terms(text, 0)
    m = _TERMS.match(text.replace(" ", ""))
    if not m or (m.group("days") is None and m.group("disc") is None):
        return Terms(text, default_days)
    days = int(m.group("days") or default_days)
    return Terms(text.replace(" ", ""), days, m.group("kind") == "EOM",
                 float(m.group("disc") or 0), int(m.group("ddays") or 0))


@rule("FIN-03", "Payment terms: the due date follows from the invoice date and the agreed terms",
      statement="Net terms count days from the invoice date; end-of-month terms count from the last day of the "
                "invoice's month; cash terms are due on the invoice date.",
      source=SOURCE, kind="calculation")
def due_date(invoice_date: Any, terms: Any = "NET30") -> dt.date:
    t = terms if isinstance(terms, Terms) else parse_terms(terms)
    start = as_date(invoice_date)
    if t.end_of_month:
        start = end_of_month(start)
    return start + dt.timedelta(days=t.days)


@dataclass(frozen=True)
class Discount:
    available: bool
    amount: Decimal             # what is saved by paying in time
    pay: Decimal                # what is paid when the discount is taken
    last_day: dt.date | None    # the last day the discount can be taken
    annualised_pct: float | None  # the discount as a yearly rate of return: is it worth paying early?


@rule("FIN-04", "Early payment discount: what paying within the discount window saves",
      statement="Terms such as 2/10 net 30 give 2% off when paid within 10 days. The annualised return of taking "
                "it is discount ÷ (100 − discount) × 365 ÷ (net days − discount days).",
      source=SOURCE, kind="calculation")
def early_payment_discount(amount: Any, invoice_date: Any, terms: Any, as_of: Any = None,
                           currency: str = "GBP") -> Discount:
    t = terms if isinstance(terms, Terms) else parse_terms(terms)
    gross = money.quantize(amount, currency)
    if t.discount_pct <= 0 or t.discount_days <= 0:
        return Discount(False, Decimal(0), gross, None, None)
    last = as_date(invoice_date) + dt.timedelta(days=t.discount_days)
    saved = money.quantize(gross * D(t.discount_pct) / 100, currency)
    gap = max(1, t.days - t.discount_days)
    annual = round(t.discount_pct / (100 - t.discount_pct) * 365 / gap * 100, 1)
    open_ = as_of is None or as_date(as_of) <= last
    return Discount(open_, saved if open_ else Decimal(0), gross - saved if open_ else gross, last, annual)


# --- FIN-05 late payment interest -----------------------------------------------------------

LATE_INTEREST_PCT = 8.0      # the statutory uplift in the UK and the EU; add the central bank's reference rate


@rule("FIN-05", "Late payment interest: simple interest on an overdue amount, by the day",
      statement="Interest is the overdue amount × the annual rate × days overdue ÷ 365, from the day after the "
                "due date.",
      source=SOURCE, kind="calculation")
def late_interest(amount: Any, due: Any, as_of: Any, annual_rate_pct: float | None = None,
                  currency: str = "GBP") -> Decimal:
    annual_rate_pct = _p(annual_rate_pct, "late_interest_pct")
    days = days_overdue(due, as_of)
    if days <= 0:
        return Decimal(0)
    return money.quantize(D(amount) * D(annual_rate_pct) / 100 * days / 365, currency)


# --- FIN-06 tax -----------------------------------------------------------------------------------

TAX_RATES = {"standard": 20.0, "reduced": 5.0, "zero": 0.0, "exempt": 0.0}     # UK VAT; pass your own


@dataclass(frozen=True)
class Tax:
    net: Decimal
    tax: Decimal
    gross: Decimal
    rate_pct: float
    reverse_charge: bool = False


@rule("FIN-06", "Tax: net, tax and gross agree to the penny, and a reverse charge carries no tax on the invoice",
      statement="Tax is the net amount × the rate, rounded to the minor unit; gross is net plus tax. Under the "
                "reverse charge the supplier charges none and the buyer accounts for it.",
      source=SOURCE, kind="calculation")
def tax(net: Any = None, *, gross: Any = None, rate: Any = "standard", reverse_charge: bool = False,
        currency: str = "GBP", rates: dict[str, float] | None = None) -> Tax:
    rates = _p(rates, "tax_rates")
    pct = float(rates[rate]) if isinstance(rate, str) else float(rate)
    if reverse_charge:
        n = money.quantize(net if net is not None else gross, currency)
        return Tax(n, Decimal(0), n, pct, True)
    if net is not None:
        return Tax(*money.add_tax(net, pct, currency), pct)
    check(gross is not None, "FIN-06", "Give a net or a gross amount to work the tax out from")
    return Tax(*money.remove_tax(gross, pct, currency), pct)


def check_tax(net: Any, tax_amount: Any, gross: Any, rate: Any = "standard", tolerance: Any = "0.01",
              currency: str = "GBP") -> None:
    """An invoice whose tax does not follow from its net, or whose gross is not their sum, is refused."""
    expected = tax(net, rate=rate, currency=currency)
    check(abs(D(tax_amount) - expected.tax) <= D(tolerance), "FIN-06",
          f"Tax of {money.fmt(tax_amount, currency)} does not follow from {money.fmt(net, currency)} at "
          f"{expected.rate_pct:g}%: it should be {money.fmt(expected.tax, currency)}")
    check(abs(D(net) + D(tax_amount) - D(gross)) <= D(tolerance), "FIN-06",
          f"Net {money.fmt(net, currency)} plus tax {money.fmt(tax_amount, currency)} is not the gross "
          f"{money.fmt(gross, currency)}")


# --- FIN-07 variance ----------------------------------------------------------------------------

MATERIAL_PCT = 5.0
MATERIAL_AMOUNT = 1000


@dataclass(frozen=True)
class Variance:
    actual: Decimal
    budget: Decimal
    amount: Decimal            # actual − budget
    pct: float | None          # … as a share of budget
    favourable: bool           # under budget on a cost, over budget on revenue
    material: bool             # large enough to need an explanation

    def as_dict(self) -> dict[str, Any]:
        return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


@rule("FIN-07", "Variance: actual against budget, favourable or adverse, and whether it is material",
      statement="Variance is actual less budget. On a cost, spending less is favourable; on revenue, earning more "
                "is. A variance of 5% or more of budget and at least 1,000 is material and needs an explanation.",
      source=SOURCE, kind="calculation")
def variance(actual: Any, budget: Any, kind: str = "cost", material_pct: float | None = None,
             material_amount: Any = None) -> Variance:
    material_pct, material_amount = _p(material_pct, "material_pct"), _p(material_amount, "material_amount")
    a, b = D(actual), D(budget)
    delta = a - b
    pct = money.pct(delta, b)
    favourable = delta <= 0 if kind in ("cost", "expense", "capex") else delta >= 0
    # On the amounts, not the rounded percentage; with no budget to compare against, the amount alone decides.
    material = abs(delta) >= D(material_amount) and (b == 0 or abs(delta) * 100 >= abs(b) * D(material_pct))
    return Variance(a, b, delta, pct, favourable, material)


# --- FIN-08 goods received not invoiced ------------------------------------------------------

@rule("FIN-08", "Accruals: goods received and not yet invoiced are accrued at the period end",
      statement="The accrual for an order is the value received less the value invoiced, never below zero.",
      source=SOURCE, kind="calculation")
def grni(received_amount: Any, invoiced_amount: Any, currency: str = "GBP") -> Decimal:
    return max(Decimal(0), money.quantize(D(received_amount) - D(invoiced_amount), currency))


def accruals(orders: Iterable[Any], currency: str = "GBP") -> list[dict[str, Any]]:
    """The accrual per open order, largest first: what finance books at month end."""
    out = []
    for o in orders or []:
        amount = grni(get(o, "received_amount", 0), get(o, "invoiced_amount", 0), currency)
        if amount > 0 and get(o, "status", "") not in ("cancelled", "closed"):
            out.append({"purchase_order_id": get(o, "id"), "reference": get(o, "reference", ""),
                        "supplier_id": get(o, "supplier_id"), "cost_center_id": get(o, "cost_center_id"),
                        "accrual": float(amount)})
    return sorted(out, key=lambda r: -r["accrual"])


# --- FIN-09 allocation -----------------------------------------------------------------------------

@rule("FIN-09", "Allocation: an amount split across cost centres sums back to the amount exactly",
      statement="Shares are rounded down to the minor unit and the pennies left over go to the largest "
                "remainders, so nothing is lost or created by rounding.",
      source=SOURCE, kind="calculation")
def allocate(amount: Any, shares: dict[Any, Any], currency: str = "GBP") -> dict[Any, Decimal]:
    """`shares` maps each cost centre (or anything) to its weight: {"CC-100": 60, "CC-200": 40}."""
    check(bool(shares), "FIN-09", "Name at least one cost centre to allocate to")
    check(all(D(w) >= 0 for w in shares.values()), "FIN-09", "A share cannot be negative")
    check(sum((D(w) for w in shares.values()), Decimal(0)) > 0, "FIN-09", "The shares add up to nothing")
    keys = list(shares)
    parts = money.allocate(amount, [shares[k] for k in keys], currency)
    return dict(zip(keys, parts))


# --- FIN-10 period lock ----------------------------------------------------------------------------

@rule("FIN-10", "Closed periods: nothing is posted into a period that has been closed",
      statement="A posting dated on or before the last closed day is refused; it is posted in the open period "
                "or the period is reopened by someone authorised to.",
      source=SOURCE, kind="validation")
def check_period_open(posting_date: Any, closed_through: Any) -> None:
    if closed_through in (None, ""):
        return
    d, closed = as_date(posting_date), as_date(closed_through)
    check(d > closed, "FIN-10",
          f"{d:%d %b %Y} falls in a closed period (closed through {closed:%d %b %Y}). Post it on or after "
          f"{closed + dt.timedelta(days=1):%d %b %Y}, or ask for the period to be reopened")


# --- FIN-11 foreign currency -------------------------------------------------------------------

@dataclass(frozen=True)
class FxResult:
    booked: Decimal         # in the base currency, at the rate when the invoice was booked
    settled: Decimal        # … at the rate when it was paid
    difference: Decimal     # settled − booked: a loss when paying cost more than was booked
    gain: bool


@rule("FIN-11", "Foreign currency: an invoice is booked at the day's rate and the difference at payment is a gain or loss",
      statement="Rates are units of foreign currency per one unit of base currency. The base amount is the foreign "
                "amount ÷ the rate; paying at a different rate gives an exchange gain or loss.",
      source=SOURCE, kind="calculation")
def fx_difference(amount: Any, booking_rate: Any, settlement_rate: Any, base_currency: str = "GBP") -> FxResult:
    check(D(booking_rate) > 0 and D(settlement_rate) > 0, "FIN-11", "An exchange rate must be greater than zero")
    booked = money.quantize(D(amount) / D(booking_rate), base_currency)
    settled = money.quantize(D(amount) / D(settlement_rate), base_currency)
    return FxResult(booked, settled, settled - booked, settled <= booked)


def to_base(amount: Any, rate: Any, base_currency: str = "GBP") -> Decimal:
    """A foreign amount in the base currency, at `rate` units of foreign currency per unit of base."""
    check(D(rate) > 0, "FIN-11", "An exchange rate must be greater than zero")
    return money.quantize(D(amount) / D(rate), base_currency)


# ======================================================================= procurement

# --- PROC-01 three-way match ---------------------------------------------------------------------

@dataclass(frozen=True)
class Tolerance:
    price_pct: float = 2.0        # the invoiced price may exceed the ordered price by this much
    quantity_pct: float = 0.0     # the invoiced quantity may exceed the received quantity by this much
    amount_abs: Any = 50          # … and neither difference may be worth more than this


@dataclass
class Match:
    status: str                                   # matched | price_variance | quantity_variance | no_po | no_receipt
    ok: bool
    discrepancies: list[str] = field(default_factory=list)
    ordered: Decimal = Decimal(0)
    received: Decimal = Decimal(0)
    invoiced: Decimal = Decimal(0)
    price_delta: Decimal = Decimal(0)             # value invoiced above the ordered price
    quantity_delta: Decimal = Decimal(0)          # value invoiced above what was received

    def as_dict(self) -> dict[str, Any]:
        return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in self.__dict__.items()}


def _pct_ok(excess: Decimal, base: Decimal, pct: Any) -> bool:
    """Whether an excess is inside a percentage of its base. No tolerance means no excess."""
    if excess <= 0:
        return True
    return D(pct) > 0 and base > 0 and excess <= base * D(pct) / 100


def _cap_ok(value: Decimal, cap: Any) -> bool:
    """Whether the worth of an excess is inside the absolute cap, when there is one."""
    return cap in (None, "") or value <= D(cap)


def match_line(ordered_qty: Any, ordered_price: Any, received_qty: Any, invoiced_qty: Any, invoiced_price: Any,
               tolerance: Tolerance | None = None, currency: str = "GBP") -> Match:
    """One line of an order against what was received and what is invoiced. A difference
    is tolerated when it is inside the percentage and worth no more than the cap."""
    tolerance = _p(tolerance, "tolerance")
    oq, op, rq, iq, ip = D(ordered_qty), D(ordered_price), D(received_qty), D(invoiced_qty), D(invoiced_price)
    m = Match("matched", True, ordered=money.quantize(oq * op, currency), received=money.quantize(rq * op, currency),
              invoiced=money.quantize(iq * ip, currency))
    if rq <= 0 and iq > 0:
        m.status, m.ok = "no_receipt", False
        m.discrepancies.append(f"{iq:g} invoiced and nothing received yet")
        m.quantity_delta = m.invoiced
        return m
    m.price_delta = money.quantize(max(Decimal(0), ip - op) * iq, currency)
    m.quantity_delta = money.quantize(max(Decimal(0), iq - rq) * op, currency)
    cap = tolerance.amount_abs
    if not (_pct_ok(iq - rq, rq, tolerance.quantity_pct) and _cap_ok(m.quantity_delta, cap)):
        m.status, m.ok = "quantity_variance", False
        m.discrepancies.append(f"{iq:g} invoiced against {rq:g} received "
                               f"({money.fmt(m.quantity_delta, currency)} more than was received)")
    if not (_pct_ok(ip - op, op, tolerance.price_pct) and _cap_ok(m.price_delta, cap)):
        if m.ok:
            m.status = "price_variance"
        m.ok = False
        m.discrepancies.append(f"invoiced at {money.fmt(ip, currency)} against {money.fmt(op, currency)} ordered "
                               f"({money.fmt(m.price_delta, currency)} over)")
    return m


@rule("PROC-01", "Three-way match: an invoice is paid when it agrees with the order and with what was received",
      statement="An invoice matches when it names an order, goods or services have been received against it, the "
                "amount invoiced is not above the amount received, and it is not above the amount ordered, each "
                "within tolerance (2% and 50 by default).",
      source=SOURCE, kind="validation")
def three_way_match(order: Any, receipts: Iterable[Any], invoice: Any, tolerance: Tolerance | None = None,
                    currency: str = "GBP", already_invoiced: Any = 0) -> Match:
    """The order, its receipts and an invoice, by value. `already_invoiced` is what earlier
    invoices against the same order have taken."""
    tolerance = _p(tolerance, "tolerance")
    invoiced = money.quantize(get(invoice, "net_amount", None) or get(invoice, "amount", 0), currency)
    if order is None:
        return Match("no_po", False, ["the invoice names no purchase order"], invoiced=invoiced)
    ordered = money.quantize(get(order, "amount", 0), currency)
    posted = [r for r in receipts or [] if get(r, "status", "posted") != "reversed"]
    received = money.quantize(_amounts(posted), currency)
    m = Match("matched", True, ordered=ordered, received=received, invoiced=invoiced)
    if received <= 0:
        m.status, m.ok = "no_receipt", False
        m.discrepancies.append("nothing has been received against the order yet")
        m.quantity_delta = invoiced
        return m
    taken = D(already_invoiced)
    m.quantity_delta = max(Decimal(0), invoiced + taken - received)
    m.price_delta = max(Decimal(0), invoiced + taken - ordered)
    cap = tolerance.amount_abs
    # By value, an invoice can exceed the receipt through price as well as quantity: the wider tolerance applies.
    over_received = not (_pct_ok(m.quantity_delta, received, max(tolerance.quantity_pct, tolerance.price_pct))
                         and _cap_ok(m.quantity_delta, cap))
    over_ordered = not (_pct_ok(m.price_delta, ordered, tolerance.price_pct) and _cap_ok(m.price_delta, cap))
    if over_ordered:
        m.status, m.ok = "price_variance", False
        m.discrepancies.append(f"{money.fmt(invoiced + taken, currency)} invoiced against {money.fmt(ordered, currency)} "
                               f"ordered ({money.fmt(m.price_delta, currency)} over)")
    if over_received:
        if m.ok:
            m.status = "quantity_variance"
        m.ok = False
        m.discrepancies.append(f"{money.fmt(invoiced + taken, currency)} invoiced against "
                               f"{money.fmt(received, currency)} received ({money.fmt(m.quantity_delta, currency)} more)")
    return m


# --- PROC-02 delegation of authority --------------------------------------------------------

# (up to and including this amount, the role that approves). None is no limit.
DEFAULT_DOA: tuple[tuple[Any, str], ...] = (
    (5_000, "budget_holder"),
    (25_000, "head_of_department"),
    (100_000, "finance_director"),
    (None, "cfo"),
)


@rule("PROC-02", "Delegation of authority: the amount decides who approves",
      statement="Each approver has a limit. A request is approved by the first role whose limit covers it; "
                "above the highest limit it goes to the role with none.",
      source=SOURCE, kind="authorisation")
def approver_for(amount: Any, matrix: Sequence[tuple[Any, str]] | None = None) -> str:
    matrix = _p(matrix, "doa")
    value = D(amount)
    for limit, role in matrix:
        if limit is None or value <= D(limit):
            return role
    return matrix[-1][1]


def approval_chain(amount: Any, matrix: Sequence[tuple[Any, str]] | None = None) -> list[str]:
    """Every role up to and including the one whose limit covers the amount, for
    organisations where each level signs in turn."""
    matrix = _p(matrix, "doa")
    out = []
    final = approver_for(amount, matrix)
    for _, role in matrix:
        out.append(role)
        if role == final:
            break
    return out


def approval_limit(role: str, matrix: Sequence[tuple[Any, str]] | None = None) -> Decimal | None:
    """What a role may approve up to; None when it has no limit or is not in the matrix."""
    matrix = _p(matrix, "doa")
    for limit, r in matrix:
        if r == role:
            return None if limit is None else D(limit)
    return Decimal(0)


def check_authority(amount: Any, role: str, matrix: Sequence[tuple[Any, str]] | None = None,
                    currency: str = "GBP") -> None:
    """Refuse an approval above the approver's limit."""
    matrix = _p(matrix, "doa")
    roles = [r for _, r in matrix]
    needed = approver_for(amount, matrix)
    ok = role in roles and roles.index(role) >= roles.index(needed)
    limit = approval_limit(role, matrix)
    check(ok, "PROC-02",
          f"{money.fmt(amount, currency)} is above what {role.replace('_', ' ')} may approve"
          + (f" ({money.fmt(limit, currency)})" if limit else "")
          + f"; it needs {needed.replace('_', ' ')}", needs=needed)


# --- PROC-03 duplicate invoices --------------------------------------------------------------

DUPLICATE_DAYS = 45


def normalise_invoice_number(number: Any) -> str:
    """INV-00123, inv 123 and INV/0123 are one number; O and 0, I and 1 are read as the same."""
    text = re.sub(r"[^A-Z0-9]", "", str(number or "").upper())
    text = re.sub(r"^(INVOICE|INV|IN|NO)", "", text)
    text = text.replace("O", "0").replace("I", "1").replace("L", "1")
    return text.lstrip("0")


@rule("PROC-03", "Duplicate invoices: the same invoice is not paid twice",
      statement="An invoice is a suspected duplicate of another from the same supplier when their numbers are the "
                "same once punctuation and leading zeros are removed, or when the amount is the same and the "
                "invoice dates are within 45 days.",
      source=SOURCE, kind="decision")
def duplicate_invoices(invoice: Any, others: Iterable[Any], days: int | None = None) -> list[dict[str, Any]]:
    """The invoices `invoice` may duplicate, most certain first: [{"invoice", "confidence", "reason"}]."""
    days = _p(days, "duplicate_days")
    out = []
    number = normalise_invoice_number(get(invoice, "supplier_invoice_number", ""))
    amount = money.quantize(get(invoice, "amount", 0))
    date = as_date(get(invoice, "invoice_date"))
    for other in others or []:
        if get(other, "id") is not None and get(other, "id") == get(invoice, "id"):
            continue
        if get(other, "supplier_id") != get(invoice, "supplier_id") or get(other, "status", "") == "rejected":
            continue
        same_number = bool(number) and normalise_invoice_number(get(other, "supplier_invoice_number", "")) == number
        same_amount = money.quantize(get(other, "amount", 0)) == amount and amount != 0
        other_date = as_date(get(other, "invoice_date"))
        close = date is not None and other_date is not None and abs((date - other_date).days) <= days
        if same_number and same_amount:
            out.append({"invoice": other, "confidence": "exact", "reason": "same supplier, number and amount"})
        elif same_number:
            out.append({"invoice": other, "confidence": "likely", "reason": "same supplier and invoice number, different amount"})
        elif same_amount and close:
            gap = abs((date - other_date).days)
            out.append({"invoice": other, "confidence": "possible",
                        "reason": f"same supplier and amount, dated {gap} day(s) apart"})
    rank = {"exact": 0, "likely": 1, "possible": 2}
    return sorted(out, key=lambda r: rank[r["confidence"]])


# --- PROC-04 savings, PROC-08 purchase price variance --------------------------------------

@dataclass(frozen=True)
class Saving:
    baseline: Decimal
    negotiated: Decimal
    amount: Decimal
    pct: float | None


@rule("PROC-04", "Savings: what was negotiated against the baseline",
      statement="A saving is (baseline price − negotiated price) × quantity. It is identified when agreed and "
                "realised as the volume is actually bought.",
      source=SOURCE, kind="calculation")
def saving(baseline_price: Any, negotiated_price: Any, quantity: Any = 1, currency: str = "GBP") -> Saving:
    base = money.quantize(D(baseline_price) * D(quantity), currency)
    agreed = money.quantize(D(negotiated_price) * D(quantity), currency)
    return Saving(base, agreed, base - agreed, money.pct(base - agreed, base))


def realised_saving(identified: Any, bought_quantity: Any, planned_quantity: Any, currency: str = "GBP") -> Decimal:
    """The part of an identified saving earned so far: in proportion to the volume bought."""
    planned = D(planned_quantity)
    if planned <= 0:
        return Decimal(0)
    share = min(Decimal(1), max(Decimal(0), D(bought_quantity) / planned))
    return money.quantize(D(identified) * share, currency)


@rule("PROC-08", "Purchase price variance: what was paid against the standard price",
      statement="Purchase price variance is (actual price − standard price) × quantity; paying less is favourable.",
      source=SOURCE, kind="calculation")
def price_variance(standard_price: Any, actual_price: Any, quantity: Any, currency: str = "GBP") -> Variance:
    standard = money.quantize(D(standard_price) * D(quantity), currency)
    actual = money.quantize(D(actual_price) * D(quantity), currency)
    return variance(actual, standard, "cost")


# --- PROC-05 supplier risk --------------------------------------------------------------------

RISK_WEIGHTS = {"delivery": 25, "quality": 20, "financial": 25, "compliance": 20, "dependency": 10}
RISK_BANDS = ((34, "low"), (67, "medium"), (101, "high"))


@dataclass(frozen=True)
class Risk:
    score: float                     # 0 (none) to 100
    rating: str                      # low | medium | high
    parts: dict[str, float]          # each factor's points


@rule("PROC-05", "Supplier risk: delivery, quality, financial health, compliance and dependency, weighted",
      statement="Risk is scored 0–100: 25 for delivery (on time, in full), 20 quality, 25 financial health, 20 "
                "compliance (missing or expiring documents) and 10 dependency (the supplier's share of the "
                "category's spend). Under 34 is low, under 67 medium, otherwise high.",
      source=SOURCE, kind="calculation")
def supplier_risk(otif_pct: Any = 100, quality_pct: Any = 100, financial_health_pct: Any = 100,
                  compliance_pct: Any = 100, spend_share_pct: Any = 0,
                  weights: dict[str, float] = RISK_WEIGHTS) -> Risk:
    def shortfall(value: Any) -> float:
        return min(100.0, max(0.0, 100.0 - float(D(value))))
    exposure = min(100.0, max(0.0, float(D(spend_share_pct)) * 2))      # half the category is full dependency
    raw = {"delivery": shortfall(otif_pct), "quality": shortfall(quality_pct), "financial": shortfall(financial_health_pct),
           "compliance": shortfall(compliance_pct), "dependency": exposure}
    whole = sum(weights.values()) or 1
    # A shortfall of 25 points on any factor is already serious: risk rises four times as fast as the shortfall.
    parts = {k: round(min(100.0, raw[k] * (4 if k != "dependency" else 1)) * weights.get(k, 0) / whole, 1) for k in raw}
    score = round(sum(parts.values()), 1)
    rating = next(name for limit, name in RISK_BANDS if score < limit)
    return Risk(score, rating, parts)


# --- PROC-06 no order, no pay -----------------------------------------------------------------

PO_REQUIRED_ABOVE = 1_000


@rule("PROC-06", "No order, no pay: an invoice above the threshold must name a purchase order",
      statement="An invoice above 1,000 that names no purchase order is an exception, unless its category is "
                "exempt (utilities, rates, subscriptions agreed under contract).",
      source=SOURCE, kind="validation")
def po_required(amount: Any, threshold: Any = None, exempt: bool = False) -> bool:
    return not exempt and D(amount) > D(_p(threshold, "po_required_above"))


def check_po(invoice: Any, threshold: Any = None, exempt: bool = False, currency: str = "GBP") -> None:
    threshold = _p(threshold, "po_required_above")
    amount = get(invoice, "amount", 0)
    check(bool(get(invoice, "purchase_order_id")) or not po_required(amount, threshold, exempt), "PROC-06",
          f"An invoice of {money.fmt(amount, currency)} needs a purchase order (required above "
          f"{money.fmt(threshold, currency)}). Ask the supplier for the order number, or raise a retrospective order")


# --- PROC-07 contract renewal -------------------------------------------------------------------

EXPIRING_DAYS = 90


@dataclass(frozen=True)
class Renewal:
    status: str                  # active | notice_due | expiring | expired
    days_left: int
    decide_by: dt.date           # the last day to give notice
    note: str


@rule("PROC-07", "Contract renewal: notice is given before the notice period starts",
      statement="A contract is expiring within 90 days of its end date. The decision to renew or leave is due by "
                "the end date less the notice period; after that an auto-renewing contract renews.",
      source=SOURCE, kind="decision")
def renewal(end_date: Any, as_of: Any, notice_days: Any = 0, auto_renew: bool = False,
            expiring_days: int | None = None) -> Renewal:
    expiring_days = _p(expiring_days, "expiring_days")
    end, today = as_date(end_date), as_date(as_of)
    notice = int(D(notice_days))
    decide_by = end - dt.timedelta(days=notice)
    left = (end - today).days
    if left < 0:
        return Renewal("expired", left, decide_by, "renewed automatically" if auto_renew else "ended")
    if today > decide_by:
        return Renewal("notice_due", left, decide_by,
                       "the notice date has passed: it renews automatically" if auto_renew
                       else "the notice date has passed: it ends on its end date")
    if left <= expiring_days or (decide_by - today).days <= 30:
        return Renewal("expiring", left, decide_by, f"decide by {decide_by:%d %b %Y}")
    return Renewal("active", left, decide_by, "")


# --- PROC-09 approved suppliers only ----------------------------------------------------------

ORDERABLE = ("approved", "active")


@rule("PROC-09", "Approved suppliers: orders go only to suppliers that are approved or active",
      statement="A supplier that is prospective, under review, suspended or retired cannot be ordered from or paid.",
      source=SOURCE, kind="validation")
def check_supplier(supplier: Any, allowed: Sequence[str] | None = None) -> None:
    allowed = _p(allowed, "orderable")
    status = str(get(supplier, "status", "")).lower()
    check(status in allowed, "PROC-09",
          f"{get(supplier, 'name', 'This supplier')} is {status.replace('_', ' ') or 'not set up'}: only approved "
          "or active suppliers can be ordered from. Complete its onboarding first", status=status)


# --- PROC-10 competition ------------------------------------------------------------------------

# (up to and including this amount, quotes needed, whether a formal tender is needed)
QUOTE_BANDS: tuple[tuple[Any, int, bool], ...] = ((5_000, 1, False), (25_000, 3, False), (None, 3, True))


@rule("PROC-10", "Competition: the amount decides how many quotes are needed",
      statement="Up to 5,000 one quote is enough; up to 25,000 three are needed; above that a formal tender. "
                "A single source needs a recorded justification.",
      source=SOURCE, kind="validation")
def quotes_needed(amount: Any, bands: Sequence[tuple[Any, int, bool]] | None = None) -> dict[str, Any]:
    bands = _p(bands, "quote_bands")
    value = D(amount)
    for limit, quotes, tender in bands:
        if limit is None or value <= D(limit):
            return {"quotes": quotes, "tender": tender}
    return {"quotes": bands[-1][1], "tender": bands[-1][2]}


def check_quotes(amount: Any, quotes_received: int, single_source_justification: str = "",
                 bands: Sequence[tuple[Any, int, bool]] | None = None, currency: str = "GBP") -> None:
    need = quotes_needed(amount, bands)
    check(quotes_received >= need["quotes"] or bool((single_source_justification or "").strip()), "PROC-10",
          f"{money.fmt(amount, currency)} needs {need['quotes']} quote(s)"
          + (" and a formal tender" if need["tender"] else "")
          + f"; {quotes_received} recorded. Add the quotes, or record why a single source is justified",
          needs=need["quotes"])


# --- PROC-11 split orders -------------------------------------------------------------------------

SPLIT_DAYS = 7


@rule("PROC-11", "Split orders: several requests just under a limit are read as one",
      statement="Requests by the same person for the same supplier within 7 days, each within an approval limit "
                "but together above it, are flagged as a possible split to avoid approval.",
      source=SOURCE, kind="decision")
def split_orders(requests: Iterable[Any], limit: Any = None, days: int | None = None) -> list[dict[str, Any]]:
    """Groups of requests that together cross `limit` (the first approval limit, unless given):
    [{"requester", "supplier_id", "total", "requests"}]."""
    days = _p(days, "split_days")
    cap = D(limit if limit is not None else first_limit())
    groups: dict[tuple[Any, Any], list[Any]] = {}
    for r in requests or []:
        if get(r, "status", "") in ("cancelled", "rejected") or D(get(r, "amount", 0)) > cap:
            continue
        key = (str(get(r, "requester_name", "")).strip().lower(), get(r, "supplier_id"))
        if key[0] and key[1] is not None:
            groups.setdefault(key, []).append(r)
    out = []
    for (who, supplier_id), items in groups.items():
        items.sort(key=lambda r: as_date(get(r, "created_at")) or dt.date.min)
        start = 0
        for end in range(len(items)):
            while (as_date(get(items[end], "created_at")) - as_date(get(items[start], "created_at"))).days > days:
                start += 1
            window = items[start:end + 1]
            total = _amounts(window)
            if len(window) > 1 and total > cap:
                out.append({"requester": get(window[0], "requester_name", who), "supplier_id": supplier_id,
                            "total": float(money.quantize(total)), "requests": list(window)})
                start = end + 1
    return sorted(out, key=lambda g: -g["total"])


# ======================================================================= the organisation's numbers

@dataclass
class Policy:
    """What an organisation sets for itself. The defaults are the usual ones."""
    doa: tuple[tuple[Any, str], ...] = DEFAULT_DOA             # PROC-02: who approves up to which amount
    tolerance: Tolerance = Tolerance()                         # PROC-01: what still matches
    po_required_above: Any = PO_REQUIRED_ABOVE                 # PROC-06: no order, no pay, above this
    po_exempt_categories: tuple[str, ...] = ("FA-RN", "FA-UT", "IT-TC")   # … except rent, utilities, telecoms (category codes)
    quote_bands: tuple[tuple[Any, int, bool], ...] = QUOTE_BANDS          # PROC-10: (up to, quotes, tender)
    budget_warning_pct: float = BUDGET_WARNING_PCT             # FIN-02: utilisation that warns
    material_pct: float = MATERIAL_PCT                         # FIN-07: a variance of this share of budget …
    material_amount: Any = MATERIAL_AMOUNT                     # … and at least this much is material
    expiring_days: int = EXPIRING_DAYS                         # PROC-07: a contract is expiring this long before it ends
    duplicate_days: int = DUPLICATE_DAYS                       # PROC-03: the same amount within this many days
    split_days: int = SPLIT_DAYS                               # PROC-11: requests this close together
    orderable: tuple[str, ...] = ORDERABLE                     # PROC-09: supplier statuses that can be ordered from
    late_interest_pct: float = LATE_INTEREST_PCT               # FIN-05
    tax_rates: dict[str, float] = field(default_factory=lambda: dict(TAX_RATES))      # FIN-06


POLICY = Policy()


def configure(**values: Any) -> Policy:
    """Set the organisation's numbers, once, where the application's rules are written.
    A name the library does not have is refused, so a misspelt one cannot be silently ignored."""
    known = set(Policy.__dataclass_fields__)
    unknown = sorted(set(values) - known)
    if unknown:
        raise TypeError(f"the finance library has no setting {', '.join(unknown)}; it has: {', '.join(sorted(known))}")
    for name, value in values.items():
        if name == "doa":
            value = tuple((limit, str(role)) for limit, role in value)
            if not value or value[-1][0] is not None:
                raise ValueError("the delegation of authority ends with a role that approves any amount: (None, \"cfo\")")
        elif name in ("quote_bands", "po_exempt_categories", "orderable"):
            value = tuple(tuple(v) if isinstance(v, (list, tuple)) else v for v in value)
        elif name == "tolerance" and not isinstance(value, Tolerance):
            value = Tolerance(**value) if isinstance(value, dict) else Tolerance(*value)
        setattr(POLICY, name, value)
    return POLICY


def reset() -> Policy:
    """Back to the library's defaults (the library's own tests state those)."""
    fresh = Policy()
    for name in Policy.__dataclass_fields__:
        setattr(POLICY, name, getattr(fresh, name))
    return POLICY


def first_limit() -> Any:
    """The first approval limit: what a request must stay under to need only the first approver."""
    return POLICY.doa[0][0] if POLICY.doa and POLICY.doa[0][0] is not None else 0
