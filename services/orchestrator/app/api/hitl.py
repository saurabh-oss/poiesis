"""The human side of the loop: what is waiting, and what the human decided."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import Gate, session
from ..graph import engine
from .schemas import GateResolve

router = APIRouter(prefix="/api/runs/{run_id}/gates", tags=["hitl"])


@router.get("")
async def list_gates(run_id: str):
    with session() as s:
        rows = (
            s.query(Gate).filter(Gate.run_id == run_id)
            .order_by(Gate.opened_at.asc()).all()
        )
        return [
            {"id": g.id, "kind": g.kind, "stage": g.stage, "status": g.status,
             "payload": g.payload, "response": g.response,
             "opened_at": g.opened_at, "resolved_at": g.resolved_at,
             "resolved_by": g.resolved_by}
            for g in rows
        ]


@router.get("/open")
async def open_gate(run_id: str):
    """The gate the graph is actually blocked on, straight from the checkpoint.

    While a driver is running, the checkpoint can still hold the interrupt that
    was just answered. Reporting it as open invites a second answer, so a busy
    run has no open gate by definition.
    """
    if engine.is_busy(run_id):
        return {"open": False, "busy": True}
    pending = await engine.pending_interrupt(run_id)
    if pending is None:
        return {"open": False}
    if engine.gate_answered(pending.get("gate_id")):
        # Decided already; the process died before the run got past it. Carry on
        # with that decision instead of asking the same question twice.
        await engine.redrive(run_id)
        return {"open": False, "busy": True}
    return {"open": True, "gate": pending}


@router.post("/resolve")
async def resolve_gate(run_id: str, payload: GateResolve):
    if engine.is_busy(run_id):
        raise HTTPException(409, "the run is already acting on a decision")
    pending = await engine.pending_interrupt(run_id)
    if pending is None:
        raise HTTPException(409, "no gate is currently open for this run")
    if engine.gate_answered(pending.get("gate_id")):
        # A second resume value would be handed to the node's next gate.
        await engine.redrive(run_id)
        raise HTTPException(409, "that decision was already made; the run is continuing with it")
    if not await engine.resume(run_id, payload.model_dump()):
        raise HTTPException(409, "the run is already acting on a decision")
    return {"resumed": True, "gate_id": pending.get("gate_id")}
