"""Run lifecycle: start a run, resume a gated run, inspect where it is."""
from __future__ import annotations

import asyncio
import traceback
from typing import Any

from langgraph.types import Command

from ..db import Gate, Run, session
from ..events import emit
from .graph import compiled_graph
from .store import set_stage


async def _mark_waiting(run_id: str) -> None:
    """Keep the stage where it is; only the status changes while a gate is open."""
    with session() as s:
        run = s.get(Run, run_id)
        if run is not None:
            run.status = "waiting"
            s.commit()

_graph = None
_graph_cm = None
_lock = asyncio.Lock()
_tasks: dict[str, asyncio.Task] = {}


async def graph():
    global _graph, _graph_cm
    async with _lock:
        if _graph is None:
            _graph, _graph_cm = await compiled_graph()
    return _graph


def config_for(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": 80}


def is_busy(run_id: str) -> bool:
    """True while a task is driving this run's graph.

    The checkpoint keeps reporting the last interrupt until the resumed node
    reaches its next one, so "a gate is in the checkpoint" and "the run is
    waiting on a human" are different questions. Answering a gate a second time
    in that window started a second, concurrent driver on the same thread; in one
    run that happened fourteen times in four minutes, each replaying the build.
    """
    task = _tasks.get(run_id)
    return task is not None and not task.done()


def _mark_running(run_id: str) -> None:
    with session() as s:
        run = s.get(Run, run_id)
        if run is not None and run.status != "running":
            run.status = "running"
            s.commit()


def gate_answered(gate_id: str | None) -> bool:
    """True when a gate the checkpoint still shows was already decided.

    That happens when the process dies after a decision and before the node that
    raised the gate gets past it. Recovery used to park such a run as "waiting on
    a human", with the answered gate shown as open again: one run sat idle for
    fifteen minutes until someone answered the same question a second time.
    Worse, a second resume value is not ignored — LangGraph hands it to the next
    gate the node raises, so a later story's failure would be "decided" without
    anyone being asked.
    """
    if not gate_id:
        return False
    with session() as s:
        gate = s.get(Gate, gate_id)
        if gate is None:
            return False
        if gate.status in ("resolved", "auto"):
            return True
        # Before gates.py reused the open row across replays, a replay opened a
        # fresh row for the same question and resolved that one instead.
        question = (gate.payload or {}).get("question")
        later = (
            s.query(Gate)
            .filter(Gate.run_id == gate.run_id, Gate.kind == gate.kind,
                    Gate.opened_at >= gate.opened_at,
                    Gate.status.in_(("resolved", "auto")))
            .all()
        )
        return any((g.payload or {}).get("question") == question for g in later)


async def redrive(run_id: str) -> bool:
    """Carry on a run whose gate was answered but whose driver died acting on it.

    Driven with no input, the node replays and the gate takes the answer already
    recorded in the checkpoint; if none was recorded, it asks again as a new gate.
    Never resumes with a new value, for the reason in gate_answered().
    """
    if is_busy(run_id):
        return False
    await emit(run_id, "Continuing with the decision already given", agent="system")
    _tasks[run_id] = asyncio.create_task(_drive(run_id, None))
    return True


async def retry(run_id: str) -> bool:
    """Drive a failed run on from its last checkpoint.

    A run that died on a platform error (a bug since fixed, a daemon that went
    away) keeps every completed stage in its checkpoint and every model call in
    the node cache, so continuing costs only the work that had not finished.
    """
    if is_busy(run_id):
        return False
    await emit(run_id, "Retrying from the last checkpoint", agent="system")
    _tasks[run_id] = asyncio.create_task(_drive(run_id, None))
    return True


async def _drive(run_id: str, payload: Any) -> None:
    g = await graph()
    # Resuming from a gate leaves the row on 'waiting'; nodes only set the stage,
    # so without this the UI shows a working run as still blocked on a human.
    await asyncio.to_thread(_mark_running, run_id)
    try:
        async for _ in g.astream(payload, config_for(run_id), stream_mode="updates"):
            pass
        state = await g.aget_state(config_for(run_id))
        if state.next:
            await emit(run_id, "Waiting on a human decision", agent="governance",
                       stage="", level="gate", data={"next": list(state.next)})
            await _mark_waiting(run_id)
    except Exception as exc:  # noqa: BLE001
        await emit(run_id, f"Run failed: {exc}", agent="system", level="error",
                   data={"traceback": traceback.format_exc()[-4000:]})
        await set_stage(run_id, "failed", status="failed")
    finally:
        _tasks.pop(run_id, None)


async def start(run_id: str, title: str) -> None:
    _tasks[run_id] = asyncio.create_task(
        _drive(run_id, {"run_id": run_id, "title": title})
    )


async def resume(run_id: str, response: dict[str, Any]) -> bool:
    """Start driving a gated run again. False if it is already being driven.

    Nothing is awaited between the check and the create, which makes the claim
    atomic within the event loop: two clicks cannot both start a driver.
    """
    if is_busy(run_id):
        return False
    _tasks[run_id] = asyncio.create_task(_drive(run_id, Command(resume=response)))
    return True


async def recover() -> list[str]:
    """Restart runs that were mid-flight when the process died.

    `_tasks` lives in memory, so a restart (including a uvicorn --reload) leaves a
    run marked 'running' with nothing driving it. The LangGraph checkpoint still
    holds the last completed node, so passing None resumes from there. Runs parked
    on a gate are left alone: they are waiting on a human, not on us.
    """
    with session() as s:
        stale = [r.id for r in s.query(Run).filter(Run.status == "running").all()]
    if not stale:
        return []

    g = await graph()
    resumed: list[str] = []
    for run_id in stale:
        try:
            state = await g.aget_state(config_for(run_id))
        except Exception:  # noqa: BLE001 — an unknown thread is not recoverable
            continue

        pending = next((t.interrupts[0].value for t in state.tasks if t.interrupts), None)
        if pending is not None and not gate_answered((pending or {}).get("gate_id")):
            await _mark_waiting(run_id)  # a gate is open; the UI will show it
            continue
        # Otherwise nothing is waiting on a human — including a gate that was
        # answered just before the restart — so drive on from the checkpoint.
        if not state.next:
            continue  # it actually finished; the terminal node set the status

        await emit(run_id, "Resuming after an orchestrator restart", agent="system",
                   data={"next": list(state.next)})
        _tasks[run_id] = asyncio.create_task(_drive(run_id, None))
        resumed.append(run_id)
    return resumed


async def shutdown() -> None:
    """Release the Postgres checkpointer connection pool on a clean exit."""
    global _graph, _graph_cm
    for task in list(_tasks.values()):
        task.cancel()
    _tasks.clear()
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
