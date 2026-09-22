"""Human-in-the-loop as a typed, durable interrupt.

A gate is not a chat message. It is a record with a schema: what is being asked,
what the agent will do if nobody answers, and what the human actually chose. The
graph blocks on it via LangGraph's checkpointed interrupt, so the process can be
restarted, the laptop can sleep, and the run resumes exactly where it stopped.

Policy per gate kind lives in the domain pack, so an organisation can decide that
vision needs sign-off but sprint planning does not.
"""
from __future__ import annotations

import asyncio
from typing import Any

from langgraph.types import interrupt

from .. import telemetry
from ..config import pack
from ..db import Gate, now, session
from ..events import emit


def _policy(kind: str) -> dict[str, Any]:
    return pack().get("gates", {}).get(kind, {"mode": "require"})


def _open_gate(run_id: str, kind: str, stage: str, payload: dict[str, Any]) -> str:
    with session() as s:
        gate = Gate(run_id=run_id, kind=kind, stage=stage, payload=payload)
        s.add(gate)
        s.commit()
        return gate.id


def _reuse_or_open(run_id: str, kind: str, stage: str, payload: dict[str, Any]) -> str:
    """The open gate already asking this question, or a new one.

    A gate's node replays from the top when it resumes (and after a restart), so
    raise_gate runs again for the same question. It used to open a fresh row each
    time and resolve that one, leaving the row the checkpoint's interrupt names
    open forever — so after a restart an answered gate looked unanswered, and one
    run sat parked for ninety minutes. One question, one row.
    """
    with session() as s:
        rows = (
            s.query(Gate)
            .filter(Gate.run_id == run_id, Gate.kind == kind, Gate.stage == stage,
                    Gate.status == "open")
            .order_by(Gate.opened_at.desc())
            .all()
        )
        for row in rows:
            if (row.payload or {}).get("question") == payload["question"]:
                return row.id
    return _open_gate(run_id, kind, stage, payload)


def _close_gate(gate_id: str, response: dict[str, Any], status: str = "resolved") -> None:
    with session() as s:
        gate = s.get(Gate, gate_id)
        if gate is None:
            return
        gate.status = status
        gate.response = response
        gate.resolved_at = now()
        gate.resolved_by = response.get("actor", "stakeholder")
        s.commit()
        waited = None
        if status == "resolved" and gate.opened_at:
            waited = (gate.resolved_at - gate.opened_at).total_seconds()
        telemetry.record_gate(gate.kind, str(response.get("decision", "")), waited)


async def raise_gate(
    *,
    run_id: str,
    kind: str,
    stage: str,
    question: str,
    artifact: dict[str, Any] | None = None,
    options: list[dict[str, str]] | None = None,
    fields: list[dict[str, Any]] | None = None,
    default: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Block the graph until a human answers, or auto-resolve per pack policy.

    Returns {"decision": "approve"|"revise"|"reject"|..., "notes": str, ...}
    """
    policy = _policy(kind)
    payload = {
        "kind": kind,
        "stage": stage,
        "question": question,
        "artifact": artifact or {},
        "options": options or [
            {"value": "approve", "label": "Approve and continue"},
            {"value": "revise", "label": "Send back with changes"},
        ],
        "fields": fields or [],
        "default": default or {"decision": "approve", "notes": ""},
    }

    if policy.get("mode") == "auto":
        await emit(
            run_id, f"Gate '{kind}' auto-approved by policy", agent="governance",
            stage=stage, level="gate", data={"kind": kind, "mode": "auto"},
        )
        gate_id = _open_gate(run_id, kind, stage, payload)
        _close_gate(gate_id, {**payload["default"], "actor": "policy:auto"}, status="auto")
        return payload["default"]

    gate_id = await asyncio.to_thread(_reuse_or_open, run_id, kind, stage, payload)
    await emit(
        run_id, question, agent="governance", stage=stage, level="gate",
        data={"gate_id": gate_id, **payload},
    )

    response = interrupt({"gate_id": gate_id, **payload})

    if not isinstance(response, dict):
        response = {"decision": str(response), "notes": ""}
    _close_gate(gate_id, response)
    await emit(
        run_id,
        f"Gate '{kind}' resolved: {response.get('decision')}",
        agent="governance", stage=stage, level="gate",
        data={"gate_id": gate_id, "response": response},
    )
    return response
