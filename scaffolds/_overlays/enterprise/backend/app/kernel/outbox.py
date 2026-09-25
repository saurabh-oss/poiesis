"""The connectors' outbox, in the application's database. Written by Poiesis, and read-only.

Connector calls are recorded in their own short sessions, not the request's: a call
to Jira happened whether or not the request that made it later rolled back, and the
record of it must survive.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ..db import _sessionmaker
from .context import current
from .models import ConnectorEvent, ConnectorObject, utcnow

_FIELDS = {c.key for c in ConnectorEvent.__table__.columns}


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str)) if value is not None else None


def _row(e: ConnectorEvent) -> dict[str, Any]:
    return {k: getattr(e, k) for k in _FIELDS}


class DbStore:
    def find_sent(self, connector: str, operation: str, idempotency_key: str) -> dict[str, Any] | None:
        with _sessionmaker()() as s:
            e = s.execute(select(ConnectorEvent).where(
                ConnectorEvent.connector == connector, ConnectorEvent.operation == operation,
                ConnectorEvent.idempotency_key == idempotency_key, ConnectorEvent.status == "sent",
            ).order_by(ConnectorEvent.id.desc())).scalars().first()
            return _row(e) if e else None

    def record(self, event: dict[str, Any]) -> int:
        with _sessionmaker()() as s:
            e = ConnectorEvent(**{k: (_jsonable(v) if k in ("request", "response") else v)
                                  for k, v in event.items() if k in _FIELDS},
                               actor_name=current().name)
            s.add(e)
            s.commit()
            return e.id

    def update(self, event_id: int, **fields: Any) -> None:
        with _sessionmaker()() as s:
            e = s.get(ConnectorEvent, event_id)
            if e is None:
                return
            for k, v in fields.items():
                if k in _FIELDS:
                    setattr(e, k, _jsonable(v) if k in ("request", "response") else v)
            s.commit()

    def get_object(self, connector: str, key: str) -> dict[str, Any] | None:
        with _sessionmaker()() as s:
            o = s.execute(select(ConnectorObject).where(ConnectorObject.connector == connector,
                                                        ConnectorObject.key == key)).scalars().first()
            return dict(o.data or {}) if o else None

    def put_object(self, connector: str, key: str, kind: str, data: dict[str, Any]) -> None:
        with _sessionmaker()() as s:
            o = s.execute(select(ConnectorObject).where(ConnectorObject.connector == connector,
                                                        ConnectorObject.key == key)).scalars().first()
            if o is None:
                s.add(ConnectorObject(connector=connector, key=key, kind=kind, data=_jsonable(data)))
            else:
                o.kind, o.data, o.updated_at = kind, _jsonable(data), utcnow()
            s.commit()

    def objects(self, connector: str, kind: str | None = None) -> list[dict[str, Any]]:
        with _sessionmaker()() as s:
            q = select(ConnectorObject).where(ConnectorObject.connector == connector,
                                              ~ConnectorObject.key.startswith("__counter__"))
            if kind:
                q = q.where(ConnectorObject.kind == kind)
            return [dict(o.data or {}) for o in s.execute(q.order_by(ConnectorObject.id)).scalars()]

    def next_number(self, connector: str, scope: str, start: int) -> int:
        key = f"__counter__:{scope}"
        with _sessionmaker()() as s:
            o = s.execute(select(ConnectorObject).where(ConnectorObject.connector == connector,
                                                        ConnectorObject.key == key).with_for_update()).scalars().first()
            if o is None:
                n = start
                s.add(ConnectorObject(connector=connector, key=key, kind="counter", data={"n": n}))
            else:
                n = int((o.data or {}).get("n", start - 1)) + 1
                o.data = {"n": n}
            s.commit()
            return n
