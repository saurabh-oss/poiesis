"""Background work: SLA escalation and connector retries. Written by Poiesis, and read-only.

One thread in the api service (never the data service) wakes every JOB_SECONDS
(default 30) and, acting as System:
  - escalates every workflow clock past its SLA (workflow.tick);
  - replays connector calls that failed with a retryable error or were deferred by the
    breaker, once their retry time has come — at most MAX_ATTEMPTS attempts in all,
    within a day of the first. The replay is a new outbox event; the old one is marked
    superseded and points at it.
The application can add its own periodic jobs in domain/jobs.py: every function there
decorated with `@every(minutes=…)` runs on the same thread.
"""
from __future__ import annotations

import datetime as dt
import importlib
import logging
import os
import threading
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..db import _sessionmaker
from .context import SYSTEM, acting_as
from .models import ConnectorEvent, utcnow

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 8
JOBS: list[dict[str, Any]] = []
_stop = threading.Event()


def every(*, minutes: float = 0, seconds: float = 0):
    """Register a domain job: `@every(minutes=15) def recalc(db): …`."""
    interval = minutes * 60 + seconds
    def decorate(fn: Callable[[Session], Any]) -> Callable[[Session], Any]:
        JOBS.append({"fn": fn, "interval": max(interval, 10), "next": 0.0, "name": fn.__name__})
        return fn
    return decorate


def replay_event(db: Session, e: ConnectorEvent) -> dict[str, Any]:
    from .. import connectors
    event = {k: getattr(e, k) for k in ("connector", "operation", "request", "idempotency_key", "ref")}
    result = connectors.replay(event)
    if result.event_id:
        newer = db.get(ConnectorEvent, result.event_id)
        if newer is not None:
            newer.attempts = (newer.attempts or 0) + (e.attempts or 0)
    e.status, e.superseded_by, e.retry_at = "superseded", result.event_id, None
    db.commit()
    return result.as_dict()


def retry_connectors(db: Session) -> int:
    now = utcnow()
    due = db.query(ConnectorEvent).filter(ConnectorEvent.status.in_(("failed", "deferred")),
                                          ConnectorEvent.retry_at.is_not(None), ConnectorEvent.retry_at <= now,
                                          ConnectorEvent.created_at >= now - dt.timedelta(days=1),
                                          ConnectorEvent.attempts < MAX_ATTEMPTS).limit(20).all()
    for e in due:
        try:
            replay_event(db, e)
        except Exception as exc:  # noqa: BLE001 — one bad event must not stop the rest
            log.warning("retrying connector event %s failed: %s", e.id, exc)
            e.retry_at = None
            db.commit()
    return len(due)


def run_once() -> dict[str, int]:
    from . import workflow
    done = {"sla": 0, "retries": 0, "jobs": 0}
    with acting_as(SYSTEM), _sessionmaker()() as db:
        done["sla"] = workflow.tick(db)
        done["retries"] = retry_connectors(db)
        now = time.time()
        for job in JOBS:
            if job["next"] <= now:
                job["next"] = now + job["interval"]
                try:
                    job["fn"](db)
                    db.commit()
                    done["jobs"] += 1
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    log.warning("job %s failed: %s", job["name"], exc)
    return done


def _loop() -> None:
    interval = float(os.getenv("JOB_SECONDS", "30") or 30)
    while not _stop.wait(interval):
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001 — the scheduler outlives any one failure
            log.warning("scheduled work failed: %s", exc)


def start() -> None:
    try:
        importlib.import_module(__package__.rsplit(".", 1)[0] + ".domain.jobs")
    except ModuleNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001
        log.error("domain/jobs.py did not load: %s", exc)
    _stop.clear()
    threading.Thread(target=_loop, name="poiesis-jobs", daemon=True).start()


def stop() -> None:
    _stop.set()
