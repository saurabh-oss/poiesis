"""The numbers behind a finance dashboard. Written by Poiesis, and read-only.

Pure functions over rows (ORM rows, dicts or plain objects): a router loads the rows
its screen needs and calls these, so every dashboard in the application computes spend,
budget, ageing and cycle time the same way.

    from ..finance import analytics as fa
    from ..finance.periods import FiscalCalendar

    invoices = db.query(Invoice).filter(Invoice.status != "rejected").all()
    fa.group_sum(invoices, "spend_category_id", top=8, names=category_names)   # spend by category
    fa.trend(invoices, "invoice_date", kind="month", periods=12, end=today)    # twelve months, none missing
    fa.budget_vs_actual(budget_lines, invoices, by="cost_center_id", committed=open_orders)
    fa.aging(open_invoices, as_of=today)                                        # Not due, 1-30, 31-60, 61-90, 90+
    fa.concentration(invoices, "supplier_id")                                   # Pareto and the top-10 share

Amounts are summed exactly (Decimal) and returned as plain numbers, rounded to pennies,
ready for JSON. Nothing here reads the database or the clock.
"""
from __future__ import annotations

import datetime as dt
import statistics
from decimal import Decimal
from typing import Any, Callable, Iterable

from . import money
from .money import D
from .periods import CALENDAR_YEAR, FiscalCalendar, aging_bucket, aging_buckets, as_date, within
from .rules import budget_position, get, variance

Rows = Iterable[Any]
Key = str | Callable[[Any], Any]
Amount = str | Callable[[Any], Any]          # a column, or how to work the amount out from a row


def _key(row: Any, by: Key) -> Any:
    return by(row) if callable(by) else get(row, by)


def _value(row: Any, amount: Amount) -> Decimal:
    return D(amount(row) if callable(amount) else get(row, amount, 0))


def _num(value: Decimal | Any) -> float:
    return float(money.quantize(value))


def _name(key: Any, names: dict[Any, str] | None) -> str:
    if names and key in names:
        return str(names[key])
    return "Unassigned" if key in (None, "") else str(key)


def total(rows: Rows, amount: Amount = "amount") -> float:
    return _num(sum((_value(r, amount) for r in rows or []), Decimal(0)))


def in_period(rows: Rows, date: str, start: Any, end: Any) -> list[Any]:
    """The rows whose date falls in the range, both ends included."""
    return [r for r in rows or [] if get(r, date) is not None and within(get(r, date), start, end)]


def compare(current: Any, prior: Any) -> dict[str, Any]:
    """A figure against the one it is compared with: the change, as an amount and a percentage."""
    c, p = D(current), D(prior)
    return {"current": _num(c), "prior": _num(p), "change": _num(c - p), "change_pct": money.pct(c - p, p),
            "direction": "up" if c > p else "down" if c < p else "flat"}


def group_sum(rows: Rows, by: Key, amount: Amount = "amount", *, names: dict[Any, str] | None = None,
              top: int | None = None, other: str = "Other") -> list[dict[str, Any]]:
    """The total and count per group, largest first, each with its share of the whole.
    `top` keeps that many groups and adds the rest up as "Other"."""
    sums: dict[Any, Decimal] = {}
    counts: dict[Any, int] = {}
    for r in rows or []:
        k = _key(r, by)
        sums[k] = sums.get(k, Decimal(0)) + _value(r, amount)
        counts[k] = counts.get(k, 0) + 1
    whole = sum(sums.values(), Decimal(0))
    ordered = sorted(sums, key=lambda k: (-sums[k], str(k)))
    out = [{"key": k, "label": _name(k, names), "value": _num(sums[k]), "count": counts[k],
            "share_pct": money.pct(sums[k], whole)} for k in ordered]
    if top is not None and len(out) > top:
        rest = out[top:]
        out = out[:top] + [{"key": None, "label": other, "value": _num(sum((D(r["value"]) for r in rest), Decimal(0))),
                            "count": sum(r["count"] for r in rest),
                            "share_pct": money.pct(sum((D(r["value"]) for r in rest), Decimal(0)), whole)}]
    return out


def count_by(rows: Rows, by: Key, *, names: dict[Any, str] | None = None, order: list[Any] | None = None) -> list[dict[str, Any]]:
    """How many rows per value, in `order` when given (every status of a lifecycle, empty ones too)."""
    counts: dict[Any, int] = {}
    for r in rows or []:
        k = _key(r, by)
        counts[k] = counts.get(k, 0) + 1
    keys = list(order) + [k for k in counts if k not in set(order)] if order else sorted(counts, key=lambda k: -counts[k])
    return [{"key": k, "label": _name(k, names), "value": counts.get(k, 0)} for k in keys]


def trend(rows: Rows, date: str, amount: Amount = "amount", *, kind: str = "month", periods: int = 12, end: Any = None,
          calendar: FiscalCalendar = CALENDAR_YEAR) -> list[dict[str, Any]]:
    """The total per month, quarter or fiscal year for the `periods` ending at `end`,
    oldest first, with the periods that had nothing at zero."""
    rows = list(rows or [])
    dates = [as_date(get(r, date)) for r in rows if get(r, date) is not None]
    last = as_date(end) if end is not None else (max(dates) if dates else dt.date.today())
    out = []
    for start, finish in calendar.last(kind, periods, last):
        inside = [r for r in rows if get(r, date) is not None and start <= as_date(get(r, date)) <= finish]
        out.append({"label": calendar.label(kind, start), "start": start.isoformat(), "end": finish.isoformat(),
                    "value": total(inside, amount), "count": len(inside)})
    return out


def cumulative(points: list[dict[str, Any]], key: str = "value") -> list[dict[str, Any]]:
    """The same points with a running total, for a year-to-date line."""
    running = Decimal(0)
    out = []
    for p in points:
        running += D(p.get(key, 0))
        out.append({**p, "cumulative": _num(running)})
    return out


def budget_vs_actual(budgets: Rows, actuals: Rows, by: Key = "cost_center_id", *, committed: Rows = (),
                     budget_amount: Amount = "amount", actual_amount: Amount = "amount", committed_amount: Amount = "amount",
                     names: dict[Any, str] | None = None, kind: str = "cost") -> list[dict[str, Any]]:
    """Per group: budget, actual, committed (ordered, not yet invoiced), what is left, the
    variance and whether it is favourable, and the position (FIN-02, FIN-07). Most over budget first."""
    def sums(rows: Rows, amount: str) -> dict[Any, Decimal]:
        acc: dict[Any, Decimal] = {}
        for r in rows or []:
            k = _key(r, by)
            acc[k] = acc.get(k, Decimal(0)) + _value(r, amount)
        return acc

    b, a, c = sums(budgets, budget_amount), sums(actuals, actual_amount), sums(committed, committed_amount)
    out = []
    for k in set(b) | set(a) | set(c):
        position = budget_position(b.get(k, 0), a.get(k, 0), c.get(k, 0))
        v = variance(a.get(k, 0), b.get(k, 0), kind)
        out.append({"key": k, "label": _name(k, names), "budget": _num(position.budget), "actual": _num(position.actual),
                    "committed": _num(position.committed), "available": _num(position.available),
                    "utilisation_pct": position.utilisation_pct, "status": position.status,
                    "variance": _num(v.amount), "variance_pct": v.pct, "favourable": v.favourable,
                    "material": v.material})
    return sorted(out, key=lambda r: (-(r["utilisation_pct"] or 0), str(r["label"])))


def aging(items: Rows, *, due: str = "due_date", amount: Amount = "amount", as_of: Any, edges: Iterable[int] = (0, 30, 60, 90),
          ) -> list[dict[str, Any]]:
    """Open items by how overdue they are, every bucket present: amount, count and share."""
    edges = list(edges)
    sums = {b: Decimal(0) for b in aging_buckets(edges)}
    counts = {b: 0 for b in sums}
    for r in items or []:
        if get(r, due) is None:
            continue
        bucket = aging_bucket(get(r, due), as_of, edges)
        sums[bucket] += _value(r, amount)
        counts[bucket] += 1
    whole = sum(sums.values(), Decimal(0))
    return [{"label": b, "value": _num(sums[b]), "count": counts[b], "share_pct": money.pct(sums[b], whole),
             "overdue": b != "Not due"} for b in sums]


def concentration(rows: Rows, by: Key, amount: Amount = "amount", *, names: dict[Any, str] | None = None,
                  cut_pct: float = 80.0) -> dict[str, Any]:
    """How concentrated spend is: the groups largest first with a running share (a Pareto),
    how many of them make up 80%, the top ten's share, and the Herfindahl index (0-10,000)."""
    groups = group_sum(rows, by, amount, names=names)
    whole = sum((D(g["value"]) for g in groups), Decimal(0))
    running = Decimal(0)
    items = []
    cut = None
    for i, g in enumerate(groups, start=1):
        running += D(g["value"])                      # on the amounts, so the last group lands on 100 exactly
        items.append({**g, "cumulative_pct": money.pct(running, whole), "rank": i})
        if cut is None and whole > 0 and running * 100 >= whole * D(cut_pct):
            cut = i
    return {"items": items, "groups": len(groups), "groups_for_cut": cut or len(groups), "cut_pct": cut_pct,
            "top10_share_pct": money.pct(sum((D(g["value"]) for g in groups[:10]), Decimal(0)), whole),
            "hhi": round(sum((g["share_pct"] or 0) ** 2 for g in groups))}


def cycle_time(rows: Rows, start: str, end: str) -> dict[str, Any]:
    """How long a step takes, in days: average, median and the 90th percentile."""
    days = []
    for r in rows or []:
        a, b = get(r, start), get(r, end)
        if a is None or b is None:
            continue
        if isinstance(a, dt.datetime) and isinstance(b, dt.datetime):
            if a.tzinfo is None:
                a = a.replace(tzinfo=dt.timezone.utc)
            if b.tzinfo is None:
                b = b.replace(tzinfo=dt.timezone.utc)
            days.append((b - a).total_seconds() / 86400)
        else:
            days.append(float((as_date(b) - as_date(a)).days))
    days = sorted(d for d in days if d >= 0)
    if not days:
        return {"count": 0, "average_days": None, "median_days": None, "p90_days": None}
    p90 = days[min(len(days) - 1, int(round(0.9 * (len(days) - 1))))]
    return {"count": len(days), "average_days": round(statistics.fmean(days), 1),
            "median_days": round(statistics.median(days), 1), "p90_days": round(p90, 1)}


def funnel(stages: list[tuple[str, Rows]], amount: Amount | None = "amount") -> list[dict[str, Any]]:
    """The steps of a process with how many made it to each and what share of the first:
    [("Requested", requisitions), ("Ordered", orders), ("Invoiced", invoices), ("Paid", paid)]."""
    out = []
    first = None
    for label, rows in stages:
        rows = list(rows or [])
        first = len(rows) if first is None else first
        out.append({"label": label, "count": len(rows), "value": total(rows, amount) if amount else None,
                    "of_first_pct": round(100 * len(rows) / first, 1) if first else None})
    return out


def pivot(rows: Rows, row_by: Key, column_by: Key, amount: Amount = "amount", *, row_names: dict[Any, str] | None = None,
          column_names: dict[Any, str] | None = None, column_order: list[Any] | None = None) -> dict[str, Any]:
    """A cross-tab with totals: rows largest first, columns in `column_order` or sorted."""
    cells: dict[tuple[Any, Any], Decimal] = {}
    for r in rows or []:
        k = (_key(r, row_by), _key(r, column_by))
        cells[k] = cells.get(k, Decimal(0)) + _value(r, amount)
    row_keys = {k[0] for k in cells}
    col_keys = list(column_order) if column_order else sorted({k[1] for k in cells}, key=lambda v: (v is None, str(v)))
    row_totals = {rk: sum((v for (r, _), v in cells.items() if r == rk), Decimal(0)) for rk in row_keys}
    ordered = sorted(row_keys, key=lambda rk: (-row_totals[rk], str(rk)))
    return {
        "columns": [{"key": c, "label": _name(c, column_names)} for c in col_keys],
        "rows": [{"key": rk, "label": _name(rk, row_names), "total": _num(row_totals[rk]),
                  "cells": [_num(cells.get((rk, c), 0)) for c in col_keys]} for rk in ordered],
        "totals": [_num(sum((v for (_, c2), v in cells.items() if c2 == c), Decimal(0))) for c in col_keys],
        "total": _num(sum(cells.values(), Decimal(0))),
    }


# --------------------------------------------------------------------------- procurement KPIs

def share(rows: Rows, predicate: Callable[[Any], bool], amount: Amount | None = "amount") -> float | None:
    """The share of rows (by value, or by count when `amount` is None) for which `predicate` holds."""
    rows = list(rows or [])
    if not rows:
        return None
    if amount is None:
        return round(100 * sum(1 for r in rows if predicate(r)) / len(rows), 1)
    whole = sum((_value(r, amount) for r in rows), Decimal(0))
    part = sum((_value(r, amount) for r in rows if predicate(r)), Decimal(0))
    return money.pct(part, whole)


def po_coverage(invoices: Rows) -> float | None:
    """The share of invoiced value that names a purchase order."""
    return share(invoices, lambda r: bool(get(r, "purchase_order_id")))


def first_time_match_rate(invoices: Rows) -> float | None:
    """The share of invoices that matched without an exception, by count."""
    considered = [r for r in invoices or [] if get(r, "match_status") not in (None, "")]
    return share(considered, lambda r: get(r, "match_status") == "matched", amount=None)


def exception_rate(invoices: Rows) -> float | None:
    rate = first_time_match_rate(invoices)
    return None if rate is None else round(100 - rate, 1)


def contracted_spend(invoices: Rows, contracted_suppliers: Iterable[Any]) -> float | None:
    """Spend under management: the share of value with suppliers that have a contract."""
    under = set(contracted_suppliers)
    return share(invoices, lambda r: get(r, "supplier_id") in under)


def maverick_spend(invoices: Rows, contracted_suppliers: Iterable[Any]) -> float | None:
    """The share of value bought without an order or outside a contracted supplier."""
    under = set(contracted_suppliers)
    return share(invoices, lambda r: not get(r, "purchase_order_id") or get(r, "supplier_id") not in under)


def otif(receipts: Rows) -> float | None:
    """On time and in full: the share of receipts that were both."""
    return share(receipts, lambda r: bool(get(r, "on_time")) and bool(get(r, "in_full")), amount=None)


def on_time_payment(invoices: Rows) -> float | None:
    """The share of paid invoices paid on or before their due date, by count."""
    paid = [r for r in invoices or [] if get(r, "paid_at") is not None and get(r, "due_date") is not None]
    return share(paid, lambda r: as_date(get(r, "paid_at")) <= as_date(get(r, "due_date")), amount=None)


def days_payable_outstanding(open_payables: Any, spend_in_period: Any, days_in_period: int = 365) -> float | None:
    """DPO: what is owed ÷ what was bought in the period × the days in the period."""
    spend = D(spend_in_period)
    if spend <= 0:
        return None
    return round(float(D(open_payables) / spend * days_in_period), 1)


def discount_capture(invoices: Rows) -> dict[str, Any]:
    """Early payment discounts on offer against those taken."""
    offered = sum((D(get(r, "discount_available", 0)) for r in invoices or []), Decimal(0))
    taken = sum((D(get(r, "discount_taken", 0)) for r in invoices or []), Decimal(0))
    return {"offered": _num(offered), "taken": _num(taken), "missed": _num(max(Decimal(0), offered - taken)),
            "capture_pct": money.pct(taken, offered)}


def savings(initiatives: Rows) -> dict[str, Any]:
    """Savings identified and realised, and how much of the pipeline has landed."""
    live = [r for r in initiatives or [] if get(r, "status") != "cancelled"]
    identified = sum((D(get(r, "identified_saving", 0)) for r in live), Decimal(0))
    realised = sum((D(get(r, "realised_saving", 0)) for r in live), Decimal(0))
    return {"identified": _num(identified), "realised": _num(realised), "realised_pct": money.pct(realised, identified),
            "initiatives": len(live)}


def price_variance_total(lines: Rows) -> dict[str, Any]:
    """Purchase price variance over order lines: (unit price − standard price) × quantity."""
    total_ = Decimal(0)
    base = Decimal(0)
    for r in lines or []:
        standard = get(r, "standard_price")
        if standard in (None, 0, ""):
            continue
        qty = D(get(r, "quantity", 0))
        total_ += (D(get(r, "unit_price", 0)) - D(standard)) * qty
        base += D(standard) * qty
    return {"variance": _num(total_), "variance_pct": money.pct(total_, base), "favourable": total_ <= 0}
