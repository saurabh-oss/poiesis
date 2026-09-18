"""Event bus: agents narrate, Postgres records, Redis fans out to the UI."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import redis.asyncio as aioredis

from .config import settings
from .db import Event, now, session, uid

_redis: aioredis.Redis | None = None


def redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings().redis_url, decode_responses=True)
    return _redis


def channel(run_id: str) -> str:
    return f"poiesis:run:{run_id}"


async def emit(
    run_id: str,
    message: str,
    *,
    agent: str = "system",
    stage: str = "",
    level: str = "info",
    data: dict[str, Any] | None = None,
) -> None:
    # Stamp once and send the same id and time to the database row and the live
    # channel. Live events used to arrive without either, so the UI could not say
    # how long a stage had been running, or de-duplicate history against live lines.
    at = now()
    event_id = uid()
    payload = {
        "id": event_id,
        "at": at.isoformat(),
        "run_id": run_id,
        "agent": agent,
        "stage": stage,
        "level": level,
        "message": message,
        "data": data or {},
    }

    def _write() -> None:
        with session() as s:
            s.add(Event(id=event_id, at=at, run_id=run_id, agent=agent, stage=stage,
                        level=level, message=message, data=data or {}))
            s.commit()

    await asyncio.to_thread(_write)
    await redis().publish(channel(run_id), json.dumps(payload, default=str))


async def subscribe(run_id: str) -> AsyncIterator[dict[str, Any]]:
    pubsub = redis().pubsub()
    await pubsub.subscribe(channel(run_id))
    try:
        async for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            yield json.loads(raw["data"])
    finally:
        await pubsub.unsubscribe(channel(run_id))
        await pubsub.aclose()
