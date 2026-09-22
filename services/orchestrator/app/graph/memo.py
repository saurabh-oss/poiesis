"""Replay-safe memoisation for graph nodes.

LangGraph resumes a checkpointed `interrupt` by re-executing the entire node it
was raised from. Everything above the interrupt therefore runs a second time,
and a model call does not answer the same way twice. Left alone that breaks the
central promise of the platform: the stakeholder approves the artifact they were
shown, the node replays, and the graph carries on with a different one nobody
reviewed. It also silently doubles the cost of every gated stage.

So each non-deterministic step is recorded under a stable key. On the first pass
the producer runs and its result is stored; on replay the stored result is
returned and the producer is never called. The key must identify the *step*, not
the attempt at running it — `vision:0` and `vision:1` are different drafts, but
the first draft is the same draft whether it is being produced or replayed.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .. import telemetry
from ..db import NodeCache, session

# Cached values are stored as JSON, so a bare list or string is wrapped rather
# than forcing every caller to return a dict.
_WRAPPER = "__value__"


def _get(run_id: str, key: str) -> dict[str, Any] | None:
    with session() as s:
        row = s.get(NodeCache, (run_id, key))
        return None if row is None else row.value


def _put(run_id: str, key: str, value: Any) -> None:
    with session() as s:
        row = s.get(NodeCache, (run_id, key))
        payload = {_WRAPPER: value}
        if row is None:
            s.add(NodeCache(run_id=run_id, key=key, value=payload))
        else:
            row.value = payload
        s.commit()


async def remember(run_id: str, key: str, producer: Callable[[], Awaitable[Any]]) -> Any:
    """Run `producer` once per (run, key); replays get the recorded result."""
    cached = await asyncio.to_thread(_get, run_id, key)
    if cached is not None:
        return cached.get(_WRAPPER)
    # The step is what a trace is attributed to: "impl:S3:r0" tells you which
    # model call produced which file, which a stage name alone never could.
    token = telemetry.current_step.set(key)
    try:
        value = await producer()
    finally:
        telemetry.current_step.reset(token)
    await asyncio.to_thread(_put, run_id, key, value)
    return value


def _forget(run_id: str, prefix: str) -> None:
    with session() as s:
        s.query(NodeCache).filter(
            NodeCache.run_id == run_id, NodeCache.key.like(f"{prefix}%")
        ).delete(synchronize_session=False)
        s.commit()


async def forget(run_id: str, prefix: str) -> None:
    """Drop memoised steps so they are genuinely redone.

    Used when the graph loops back on purpose — a rework round must rebuild, not
    replay the increment the Reviewer just rejected.
    """
    await asyncio.to_thread(_forget, run_id, prefix)
