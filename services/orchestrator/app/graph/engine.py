"""Run lifecycle: start a run, resume a gated run, queue, cancel, inspect where it is.

The engine is the only thing that drives a graph. It owns three invariants:

* **One driver per run.** Answering a gate twice, or /start racing /retry, must
  never put two tasks on the same checkpoint thread.
* **A bounded number of drivers at once.** On one GPU, two runs do not go twice
  as fast; they go half as fast each and thrash the model cache. Runs beyond
  the limit wait in a queue with a visible position and start as slots free.
* **Every driver is attributable.** The run id is set in the telemetry context
  before the graph moves, so every span and model call underneath it is tagged.
"""
from __future__ import annotations

import asyncio
import traceback
from typing import Any

from langgraph.types import Command

from .. import telemetry
from ..config import settings
from ..db import Gate, Run, session
from ..events import emit
from .graph import compiled_graph
from .store import set_stage


def _mark(run_id: str, status: str) -> None:
    with session() as s:
        run = s.get(Run, run_id)
        if run is not None and run.status != status:
            run.status = status
            s.commit()


async def _mark_waiting(run_id: str) -> None:
    """Keep the stage where it is; only the status changes while a gate is open."""
    await asyncio.to_thread(_mark, run_id, "waiting")


_graph = None
_graph_cm = None
_lock = asyncio.Lock()
_tasks: dict[str, asyncio.Task] = {}
_queue: list[tuple[str, Any]] = []          # (run_id, payload) waiting for a slot
_cancel_requested: set[str] = set()


async def graph():
    global _graph, _graph_cm
    async with _lock:
        if _graph is None:
            _graph, _graph_cm = await compiled_graph()
    return _graph


def config_for(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 80}


def is_busy(run_id: str) -> bool:
    """True while a task is driving this run's graph, or it is queued to be.

    The checkpoint keeps reporting the last interrupt until the resumed node
    reaches its next one, so "a gate is in the checkpoint" and "the run is
    waiting on a human" are different questions. Answering a gate a second time
    in that window started a second, concurrent driver on the same thread.
    """
    task = _tasks.get(run_id)
    if task is not None and not task.done():
        return True
    return any(r == run_id for r, _ in _queue)


def _limit() -> int:
    return max(1, int(settings().poiesis_max_concurrent_runs))


def active() -> list[str]:
    return [r for r, t in _tasks.items() if not t.done()]


def queued() -> list[str]:
    return [r for r, _ in _queue]


def stats() -> dict[str, Any]:
    return {"active": active(), "queued": queued(), "limit": _limit()}


def _gauge() -> None:
    telemetry.set_drivers(len(active()), len(_queue))


def gate_answered(gate_id: str | None) -> bool:
    """True when a gate the checkpoint still shows was already decided.

    That happens when the process dies after a decision and before the node that
    raised the gate gets past it. A second resume value is not ignored — LangGraph
    hands it to the next gate the node raises — so an answered gate is never
    resumed again; it is redriven with no input.
    """
    if not gate_id:
        return False
    with session() as s:
        gate = s.get(Gate, gate_id)
        if gate is None:
            return False
        if gate.status in ("resolved", "auto"):
            return True
        question = (gate.payload or {}).get("question")
        later = (
            s.query(Gate)
            .filter(Gate.run_id == gate.run_id, Gate.kind == gate.kind,
                    Gate.opened_at >= gate.opened_at,
                    Gate.status.in_(("resolved", "auto")))
            .all()
        )
        return any((g.payload or {}).get("question") == question for g in later)


# ---- scheduling ------------------------------------------------------------------

async def _launch(run_id: str, payload: Any) -> bool:
    """Drive the run now if a slot is free, otherwise queue it. False when queued."""
    if len(active()) >= _limit():
        if run_id not in queued():
            _queue.append((run_id, payload))
            await asyncio.to_thread(_mark, run_id, "scheduled")
            await emit(run_id, f"Queued behind {len(active())} run(s) already using the models; "
                               f"position {len(_queue)}. It starts as soon as a slot is free.",
                       agent="system", data={"position": len(_queue), "active": active()})
        _gauge()
        return False
    _tasks[run_id] = asyncio.create_task(_drive(run_id, payload))
    _gauge()
    return True


async def _pump() -> None:
    """Start queued runs while slots are free."""
    while _queue and len(active()) < _limit():
        run_id, payload = _queue.pop(0)
        if run_id in _cancel_requested:
            _cancel_requested.discard(run_id)
            continue
        await emit(run_id, "A slot is free; starting now", agent="system")
        _tasks[run_id] = asyncio.create_task(_drive(run_id, payload))
    _gauge()


async def _drive(run_id: str, payload: Any) -> None:
    g = await graph()
    token = telemetry.current_run.set(run_id)
    # Resuming from a gate leaves the row on 'waiting'; nodes only set the stage,
    # so without this the UI shows a working run as still blocked on a human.
    await asyncio.to_thread(_mark, run_id, "running")
    try:
        async with telemetry.span("run", "drive", payload_kind=type(payload).__name__):
            async for _ in g.astream(payload, config_for(run_id), stream_mode="updates"):
                pass
            state = await g.aget_state(config_for(run_id))
            if state.next:
                await emit(run_id, "Waiting on a human decision", agent="governance",
                           stage="", level="gate", data={"next": list(state.next)})
                await _mark_waiting(run_id)
    except asyncio.CancelledError:
        if run_id in _cancel_requested:
            _cancel_requested.discard(run_id)
            await emit(run_id, "Cancelled by the stakeholder. Everything finished so far is kept; "
                               "Retry continues from the last checkpoint.",
                       agent="governance", level="warn")
            await set_stage(run_id, _stage_of(run_id), status="cancelled")
        else:
            raise  # the process is shutting down; recover() picks the run up next boot
    except Exception as exc:  # noqa: BLE001
        await emit(run_id, f"Run failed: {exc}", agent="system", level="error",
                   data={"traceback": traceback.format_exc()[-4000:]})
        await set_stage(run_id, "failed", status="failed")
    finally:
        telemetry.current_run.reset(token)
        _tasks.pop(run_id, None)
        try:
            await _pump()
        except Exception:  # noqa: BLE001
            pass


def _stage_of(run_id: str) -> str:
    with session() as s:
        run = s.get(Run, run_id)
        return run.stage if run else "build"


# ---- the public verbs ------------------------------------------------------------

async def start(run_id: str, title: str) -> bool:
    """True when driving now, False when queued for a slot."""
    return await _launch(run_id, {"run_id": run_id, "title": title})


async def resume(run_id: str, response: dict[str, Any]) -> bool:
    """Start driving a gated run again. False if it is already being driven.

    Nothing is awaited between the check and the create, which makes the claim
    atomic within the event loop: two clicks cannot both start a driver.
    """
    if is_busy(run_id):
        return False
    await _launch(run_id, Command(resume=response))
    return True


async def redrive(run_id: str) -> bool:
    """Carry on a run whose gate was answered but whose driver died acting on it."""
    if is_busy(run_id):
        return False
    await emit(run_id, "Continuing with the decision already given", agent="system")
    await _launch(run_id, None)
    return True


async def retry(run_id: str) -> bool:
    """Drive a failed or cancelled run on from its last checkpoint."""
    if is_busy(run_id):
        return False
    await emit(run_id, "Retrying from the last checkpoint", agent="system")
    await _launch(run_id, None)
    return True


async def cancel(run_id: str) -> str:
    """Stop a run. Returns what happened: 'cancelled', 'dequeued' or 'idle'."""
    for i, (r, _) in enumerate(_queue):
        if r == run_id:
            _queue.pop(i)
            await set_stage(run_id, _stage_of(run_id), status="cancelled")
            await emit(run_id, "Removed from the queue before it started", agent="governance",
                       level="warn")
            _gauge()
            return "dequeued"
    task = _tasks.get(run_id)
    if task is None or task.done():
        return "idle"
    _cancel_requested.add(run_id)
    task.cancel()
    return "cancelled"


async def recover() -> list[str]:
    """Restart runs that were mid-flight when the process died.

    `_tasks` lives in memory, so a restart leaves a run marked 'running' with
    nothing driving it. The LangGraph checkpoint still holds the last completed
    node, so passing None resumes from there. Runs parked on a gate are left
    alone: they are waiting on a human, not on us. Runs that were queued and
    never started are started from their brief again.
    """
    with session() as s:
        stale = [(r.id, r.status, r.title) for r in
                 s.query(Run).filter(Run.status.in_(("running", "scheduled"))).all()]
    if not stale:
        return []

    g = await graph()
    resumed: list[str] = []
    for run_id, status, title in stale:
        try:
            state = await g.aget_state(config_for(run_id))
        except Exception:  # noqa: BLE001 — an unknown thread is not recoverable
            continue

        if not state.values and status == "scheduled":
            await emit(run_id, "Resuming after an orchestrator restart", agent="system")
            await _launch(run_id, {"run_id": run_id, "title": title})
            resumed.append(run_id)
            continue

        pending = next((t.interrupts[0].value for t in state.tasks if t.interrupts), None)
        if pending is not None and not gate_answered((pending or {}).get("gate_id")):
            await _mark_waiting(run_id)  # a gate is open; the UI will show it
            continue
        if not state.next:
            continue  # it actually finished; the terminal node set the status

        await emit(run_id, "Resuming after an orchestrator restart", agent="system",
                   data={"next": list(state.next)})
        await _launch(run_id, None)
        resumed.append(run_id)
    return resumed


async def shutdown() -> None:
    """Release the Postgres checkpointer connection pool on a clean exit."""
    global _graph, _graph_cm
    for task in list(_tasks.values()):
        task.cancel()
    _tasks.clear()
    _queue.clear()
    if _graph_cm is not None:
        await _graph_cm.__aexit__(None, None, None)
    _graph, _graph_cm = None, None


async def pending_interrupt(run_id: str) -> dict[str, Any] | None:
    g = await graph()
    state = await g.aget_state(config_for(run_id))
    for task in state.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


async def snapshot(run_id: str) -> dict[str, Any]:
    g = await graph()
    state = await g.aget_state(config_for(run_id))
    with session() as s:
        run = s.get(Run, run_id)
        meta = {
            "id": run_id,
            "title": run.title if run else "",
            "status": run.status if run else "unknown",
            "stage": run.stage if run else "",
            "summary": run.summary if run else {},
        }
    return {**meta, "next": list(state.next), "values_keys": sorted(state.values.keys())}
