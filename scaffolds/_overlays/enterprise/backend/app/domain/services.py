"""Operations over the database that combine rules, workflows and connectors.
WORKED EXAMPLE over the scaffold's Example model: the domain stage replaces this file.

A router calls a service; a service calls rules for decisions, `transition()` for
status changes, `record()` for anything the audit trail should explain, and a
connector for anything outside. Routers stay thin: parse, call one service, return.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from ..connectors import jira
from ..kernel import record
from ..models import Example
from . import rules


def ranked(db: Session, now: dt.datetime | None = None) -> list[dict[str, Any]]:
    """Every open item with its EX-03 priority, highest first."""
    now = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for item in db.query(Example).filter(Example.status != "done").all():
        created = item.created_at if item.created_at.tzinfo else item.created_at.replace(tzinfo=dt.timezone.utc)
        out.append({"id": item.id, "label": item.label, "status": item.status, "owner": item.owner,
                    "amount": item.amount, "priority": rules.priority(item.amount or 0, (now - created).days)})
    return sorted(out, key=lambda r: -r["priority"])


def escalate_to_jira(db: Session, item: Example) -> dict[str, Any]:
    """Raise a Jira issue for an item, once (idempotent), and say so in the audit trail."""
    result = jira().create_issue(f"{item.label}", f"Amount {item.amount:,.0f}; owner {item.owner or 'none'}",
                                 labels=["poiesis"], idempotency_key=f"example-{item.id}", ref=f"example:{item.id}")
    if result.ok:
        record(db, "connector", f"Raised {result.key} in Jira for item {item.id}", entity="example", entity_id=item.id)
        db.commit()
    return result.as_dict()
