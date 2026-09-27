"""The insight API as functions, for a router or a job. Written by Poiesis, and read-only.

What a screen asks the insight API for (`fin.data(api).budget({by: "cost_center"})`), a router
asks for by the same name, with the session it was given:

    from ..finance import insight

    @router.get("/my-budget")
    def my_budget(db: Session = Depends(get_session)):
        position = insight.budget(db, by="cost_center", period="fy_to_date", department="Operations")
        return {"rows": position["rows"], "totals": position["totals"]}

Every function takes the session, then what its endpoint takes: the scope (`period`, or `start`
and `end` as dates written 2026-04-01; `compare`; the filters `cost_center_id`, `spend_category_id`,
`supplier_id`, `family`, `department`, `region`, `country`, `currency`) and its own parameters. It
returns what the endpoint returns. A screen needs none of this: it calls the insight API itself.
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from . import api

SCOPE = ("period", "start", "end", "compare", "cost_center_id", "spend_category_id", "supplier_id", "family",
         "department", "region", "country", "currency")


def _text(value: Any) -> str:
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(v) for v in value)
    return "" if value is None else str(value)


def scope(**params: Any) -> api.Scope:
    """The period, the comparison and the filters, from keywords. `from_` and `to` are read as `start` and `end`."""
    given = {("start" if k in ("from_", "from") else "end" if k == "to" else k): v for k, v in params.items()}
    return api.Scope(**{k: _text(v) for k, v in given.items() if k in SCOPE and v is not None})


def _ask(endpoint: Callable[..., Any], db: Session, params: dict[str, Any], **fixed: Any) -> Any:
    own = {k: v for k, v in params.items() if k not in SCOPE and k not in ("from_", "from", "to") and v is not None}
    return endpoint(**fixed, **own, db=db, scope=scope(**params))


def calendar(db: Session | None = None, **params: Any) -> dict[str, Any]:
    return api.get_calendar(scope=scope(**params))


def dimensions(db: Session) -> dict[str, Any]:
    return api.get_dimensions(db=db)


def kpis(db: Session, keys: Any = "", **params: Any) -> dict[str, Any]:
    return _ask(api.get_kpis, db, params, keys=_text(keys))


def breakdown(db: Session, measure: str = "spend", by: str = "supplier", **params: Any) -> dict[str, Any]:
    return _ask(api.get_breakdown, db, params, measure=measure, by=by)


def concentration(db: Session, measure: str = "spend", by: str = "supplier", **params: Any) -> dict[str, Any]:
    return _ask(api.get_concentration, db, params, measure=measure, by=by)


def trend(db: Session, measure: str = "spend", kind: str = "month", periods: int = 12, **params: Any) -> dict[str, Any]:
    return _ask(api.get_trend, db, params, measure=measure, kind=kind, periods=periods)


def pivot(db: Session, measure: str = "spend", rows: str = "cost_center", columns: str = "month", **params: Any) -> dict[str, Any]:
    return _ask(api.get_pivot, db, params, measure=measure, rows=rows, columns=columns)


def budget(db: Session, by: str = "cost_center", **params: Any) -> dict[str, Any]:
    return _ask(api.get_budget, db, params, by=by)


def waterfall(db: Session, by: str = "cost_center", **params: Any) -> dict[str, Any]:
    return _ask(api.get_waterfall, db, params, by=by)


def aging(db: Session, **params: Any) -> dict[str, Any]:
    return _ask(api.get_aging, db, params)


def funnel(db: Session, **params: Any) -> dict[str, Any]:
    return _ask(api.get_funnel, db, params)


def cycle_times(db: Session, **params: Any) -> dict[str, Any]:
    return _ask(api.get_cycle_times, db, params)


def exceptions(db: Session, **params: Any) -> dict[str, Any]:
    return _ask(api.get_exceptions, db, params)


def accruals(db: Session, **params: Any) -> dict[str, Any]:
    return _ask(api.get_accruals, db, params)


def renewals(db: Session, within: int = 180, **params: Any) -> dict[str, Any]:
    return _ask(api.get_renewals, db, params, within=within)


def controls(db: Session, days: int = 90, **params: Any) -> dict[str, Any]:
    return _ask(api.get_controls, db, params, days=days)


def scorecard(db: Session, supplier_id: int, **params: Any) -> dict[str, Any]:
    return _ask(api.get_scorecard, db, params, supplier_id=int(supplier_id))


def documents(db: Session, entity: str = "invoice", **params: Any) -> dict[str, Any]:
    defaults = {"status": "", "match_status": "", "overdue": False, "bucket": "", "dated": True, "date": "", "q": "",
                "sort": "", "limit": 500, "where": "", "mine": False}
    own = {k: params.pop(k) for k in list(params) if k in defaults}
    return api.get_documents(entity=entity, **{**defaults, **own}, db=db, scope=scope(**params))


def worklist(db: Session, entity: str = "requisition", mine: bool = False, **params: Any) -> dict[str, Any]:
    """How many of an entity's records are in each state."""
    return api.get_worklist(entity=entity, mine=mine, db=db, scope=scope(**params))


def approvals(db: Session, entity: str = "", mine: bool = True) -> dict[str, Any]:
    """What waits for a decision by the person this request is for."""
    return api.get_approvals(entity=entity, mine=mine, db=db)
