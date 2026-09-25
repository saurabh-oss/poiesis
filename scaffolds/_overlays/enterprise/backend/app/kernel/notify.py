"""Notifications: an in-app inbox per person, fanned out to e-mail, Slack and Teams.
Written by Poiesis, and read-only.

    notify(db, "Approval needed: PR-1042", "£18,400 from Facilities", roles=("finance",),
           link="#/approvals", kind="approval_requested")

Every notification lands in the recipients' inboxes (the bell in the header). Which
kinds also go out through connectors is policy, set in `domain/policy.py`:

    CHANNELS = {"approval_requested": ["email", "teams"], "sla_breached": ["slack"]}

E-mail goes to each recipient's address; Slack and Teams post one message to the team
channel. Without credentials the connectors run in their sandbox, so the message is
kept in the Integrations outbox rather than sent.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Iterable

from sqlalchemy.orm import Session

from .models import AppUser, Notification

log = logging.getLogger(__name__)

DEFAULT_CHANNELS: dict[str, list[str]] = {
    "approval_requested": ["email"],
    "approval_decided": ["email"],
    "sla_breached": ["email", "teams"],
}


def channels_for(kind: str) -> list[str]:
    try:
        module = importlib.import_module(__package__.rsplit(".", 1)[0] + ".domain.policy")
        declared = getattr(module, "CHANNELS", None)
    except Exception:  # noqa: BLE001 — no policy, or a broken one: defaults
        declared = None
    table = declared if isinstance(declared, dict) else DEFAULT_CHANNELS
    return [c for c in table.get(kind, []) if c in ("email", "slack", "teams")]


def recipients(db: Session, roles: Iterable[str] = (), users: Iterable[int] = ()) -> list[AppUser]:
    wanted_roles, wanted_users = set(roles), set(users)
    out = []
    for u in db.query(AppUser).filter(AppUser.active.is_(True)).all():
        if u.id in wanted_users or (wanted_roles & set(u.role_list())):
            out.append(u)
    return out


def notify(db: Session, title: str, body: str = "", *, roles: Iterable[str] = (), users: Iterable[int] = (),
           link: str = "", level: str = "info", entity: str = "", entity_id: int | None = None,
           kind: str = "info", channels: Iterable[str] | None = None, exclude_user: int | None = None) -> int:
    """Tell people. Returns how many inboxes it reached."""
    people = [u for u in recipients(db, roles, users) if u.id != exclude_user]
    for u in people:
        db.add(Notification(user_id=u.id, title=title[:300], body=body, level=level, link=link,
                            entity=entity, entity_id=entity_id))
    chosen = list(channels) if channels is not None else channels_for(kind)
    if chosen and people:
        # Sent after the transaction commits, never inside it: an e-mail about an
        # approval that then rolled back would announce something that did not happen.
        db.info.setdefault(_QUEUE, []).append({
            "channels": chosen, "title": title, "body": body, "emails": [u.email for u in people if u.email],
            "ref": f"{entity}:{entity_id}" if entity else None,
            "facts": {"Record": f"{entity.replace('_', ' ')} {entity_id}"} if entity else None,
        })
    return len(people)


_QUEUE = "poiesis_deliveries"


def _deliver(session: Session) -> None:
    queued = session.info.pop(_QUEUE, [])
    if not queued:
        return
    from .. import connectors
    for item in queued:
        for channel in item["channels"]:
            try:
                if channel == "email" and item["emails"]:
                    connectors.email().send(item["emails"], item["title"], item["body"] or item["title"], ref=item["ref"])
                elif channel == "slack":
                    connectors.slack().post(item["title"], item["body"], facts=item["facts"], ref=item["ref"])
                elif channel == "teams":
                    connectors.teams().post(item["title"], item["body"], facts=item["facts"], ref=item["ref"])
            except Exception as exc:  # noqa: BLE001 — a notification must never undo the work it reports
                log.warning("notification over %s failed: %s", channel, exc)


def install() -> None:
    """Deliver queued notifications after each commit; forget them on rollback. Idempotent."""
    if getattr(install, "_done", False):
        return
    from sqlalchemy import event
    event.listen(Session, "after_commit", _deliver)
    event.listen(Session, "after_rollback", lambda session: session.info.pop(_QUEUE, None))
    install._done = True  # type: ignore[attr-defined]
