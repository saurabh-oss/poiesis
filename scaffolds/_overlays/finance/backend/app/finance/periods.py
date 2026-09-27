"""The fiscal calendar, periods and ageing. Written by Poiesis, and read-only.

Finance does not count in calendar years. A fiscal year starts in the month the
organisation says (April in the UK public sector and much of India, October for the US
federal government, January for most companies), is named after the year it ends in,
and is cut into quarters and twelve periods. Every dashboard compares a period with
the one before it and the same one a year earlier.

    from ..finance.periods import FiscalCalendar, aging_bucket
    cal = FiscalCalendar(start_month=4)
    cal.fiscal_year(date(2026, 9, 25))        -> 2027        (April 2026 – March 2027)
    cal.quarter(date(2026, 9, 25))            -> 2
    cal.label("quarter", date(2026, 9, 25))   -> "Q2 FY2027"
    cal.bounds("quarter", date(2026, 9, 25))  -> (date(2026, 7, 1), date(2026, 9, 30))
    cal.to_date("year", date(2026, 9, 25))    -> (date(2026, 4, 1), date(2026, 9, 25))     # YTD
    aging_bucket(due, as_of)                  -> "31-60"

Pure: nothing here reads the clock. Pass the date.
"""
from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable

KINDS = ("month", "quarter", "year")
AGING_EDGES = (0, 30, 60, 90)


def as_date(value: Any) -> dt.date | None:
    """A date from a date, a datetime or an ISO string; None from nothing."""
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    try:
        return dt.date.fromisoformat(text[:10])
    except ValueError:
        raise ValueError(f"{value!r} is not a date") from None


def end_of_month(d: dt.date) -> dt.date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d: dt.date, months: int) -> dt.date:
    """The same day `months` later, or the month's last day when it has no such day."""
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class FiscalCalendar:
    start_month: int = 1            # the month the fiscal year starts in (4 = April)
    name_by: str = "end"            # a year is named after the calendar year it ends in, or "start"

    def __post_init__(self) -> None:
        if not 1 <= int(self.start_month) <= 12:
            raise ValueError("start_month is a month, 1 to 12")

    # -- where a date falls ----------------------------------------------------------
    def fiscal_year(self, d: Any) -> int:
        d = as_date(d)
        start_year = d.year if d.month >= self.start_month else d.year - 1
        if self.start_month == 1 or self.name_by == "start":
            return start_year
        return start_year + 1

    def period(self, d: Any) -> int:
        """1 to 12: the month within the fiscal year."""
        d = as_date(d)
        return (d.month - self.start_month) % 12 + 1

    def quarter(self, d: Any) -> int:
        return (self.period(d) - 1) // 3 + 1

    def year_start(self, fiscal_year: int) -> dt.date:
        first = fiscal_year if (self.start_month == 1 or self.name_by == "start") else fiscal_year - 1
        return dt.date(first, self.start_month, 1)

    def period_start(self, fiscal_year: int, period: int) -> dt.date:
        return add_months(self.year_start(fiscal_year), period - 1)

    # -- ranges ------------------------------------------------------------------------
    def bounds(self, kind: str, d: Any) -> tuple[dt.date, dt.date]:
        """The first and last day of the month, quarter or fiscal year `d` falls in."""
        d = as_date(d)
        if kind == "month":
            return d.replace(day=1), end_of_month(d)
        start = self.year_start(self.fiscal_year(d))
        if kind == "quarter":
            start = add_months(start, (self.quarter(d) - 1) * 3)
            return start, end_of_month(add_months(start, 2))
        if kind == "year":
            return start, end_of_month(add_months(start, 11))
        raise ValueError(f"kind is one of {', '.join(KINDS)}")

    def to_date(self, kind: str, d: Any) -> tuple[dt.date, dt.date]:
        """Month, quarter or year to date: from the start of the period to `d`."""
        d = as_date(d)
        return self.bounds(kind, d)[0], d

    def prior(self, kind: str, d: Any) -> tuple[dt.date, dt.date]:
        """The period just before the one `d` falls in."""
        start, _ = self.bounds(kind, d)
        return self.bounds(kind, start - dt.timedelta(days=1))

    def year_ago(self, start: Any, end: Any) -> tuple[dt.date, dt.date]:
        """The same range one year earlier, for a like-for-like comparison."""
        return add_months(as_date(start), -12), add_months(as_date(end), -12)

    def periods(self, kind: str, start: Any, end: Any) -> list[tuple[dt.date, dt.date]]:
        """Every month, quarter or year from the one holding `start` to the one holding `end`."""
        out = []
        cursor = self.bounds(kind, as_date(start))
        last = self.bounds(kind, as_date(end))
        while cursor[0] <= last[0]:
            out.append(cursor)
            cursor = self.bounds(kind, cursor[1] + dt.timedelta(days=1))
        return out

    def last(self, kind: str, count: int, d: Any) -> list[tuple[dt.date, dt.date]]:
        """The `count` periods ending with the one `d` falls in, oldest first."""
        out = [self.bounds(kind, d)]
        while len(out) < count:
            out.append(self.prior(kind, out[-1][0]))
        return list(reversed(out))

    # -- names -------------------------------------------------------------------------
    def label(self, kind: str, d: Any) -> str:
        d = as_date(d)
        if kind == "month":
            return f"{calendar.month_abbr[d.month]} {d.year}"
        if kind == "quarter":
            return f"Q{self.quarter(d)} FY{self.fiscal_year(d)}"
        if kind == "year":
            return f"FY{self.fiscal_year(d)}"
        raise ValueError(f"kind is one of {', '.join(KINDS)}")


CALENDAR_YEAR = FiscalCalendar(1)
APRIL_YEAR = FiscalCalendar(4)


def within(value: Any, start: Any, end: Any) -> bool:
    """Whether a date falls in a range, both ends included."""
    d = as_date(value)
    return d is not None and as_date(start) <= d <= as_date(end)


def days_overdue(due: Any, as_of: Any) -> int:
    """Days past the due date; zero or negative when it is not yet due."""
    return (as_date(as_of) - as_date(due)).days


def aging_bucket(due: Any, as_of: Any, edges: Iterable[int] = AGING_EDGES) -> str:
    """The ageing bucket of an open item: "Not due", "1-30", "31-60", "61-90", "90+"."""
    late = days_overdue(due, as_of)
    edges = list(edges)
    if late <= edges[0]:
        return "Not due"
    for low, high in zip(edges, edges[1:]):
        if late <= high:
            return f"{low + 1}-{high}"
    return f"{edges[-1]}+"


def aging_buckets(edges: Iterable[int] = AGING_EDGES) -> list[str]:
    """Every bucket in order, so a chart shows the empty ones too."""
    edges = list(edges)
    return ["Not due"] + [f"{a + 1}-{b}" for a, b in zip(edges, edges[1:])] + [f"{edges[-1]}+"]


def is_business_day(d: dt.date, holidays: Iterable[dt.date] = ()) -> bool:
    return d.weekday() < 5 and d not in set(holidays)


def add_business_days(d: Any, days: int, holidays: Iterable[dt.date] = ()) -> dt.date:
    d = as_date(d)
    closed = set(holidays)
    step = 1 if days >= 0 else -1
    left = abs(days)
    while left:
        d += dt.timedelta(days=step)
        if is_business_day(d, closed):
            left -= 1
    return d


def business_days_between(start: Any, end: Any, holidays: Iterable[dt.date] = ()) -> int:
    """Working days after `start` up to and including `end`."""
    a, b = as_date(start), as_date(end)
    if b < a:
        return -business_days_between(b, a, holidays)
    closed = set(holidays)
    return sum(1 for i in range(1, (b - a).days + 1) if is_business_day(a + dt.timedelta(days=i), closed))
