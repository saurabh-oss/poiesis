"""Stage 1-2: assemble the brief from evidence, then interrogate it."""
from __future__ import annotations

import json
from typing import Any

from ...agents.base import ANALYST
from ...db import Evidence, session
from ...events import emit
from ..gates import raise_gate
from ..memo import remember
from ..state import RunState
from ..store import save_artifact, set_stage


def _load_evidence(run_id: str) -> list[dict[str, Any]]:
    with session() as s:
        rows = s.query(Evidence).filter(Evidence.run_id == run_id).all()
        return [
            {"id": r.id, "source_kind": r.source_kind, "source_ref": r.source_ref,
             "locator": r.locator, "content": r.content}
            for r in rows
        ]


def render_brief(evidence: list[dict[str, Any]]) -> str:
    parts = []
    for e in evidence:
        head = f"[{e['id']}] {e['source_kind']}:{e['source_ref']}"
        if e["locator"]:
            head += f" ({e['locator']})"
        parts.append(f"{head}\n{e['content']}")
    return "\n\n---\n\n".join(parts)


async def intake(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "intake", status="running")
    evidence = _load_evidence(run_id)
    await emit(
        run_id,
        f"Captured {len(evidence)} evidence fragments from "
        f"{len({e['source_ref'] for e in evidence})} sources",
        agent="intake", stage="intake",
        data={"count": len(evidence),
              "sources": sorted({e["source_ref"] for e in evidence})},
    )
    return {"evidence": evidence, "brief": render_brief(evidence), "repair_attempts": 0}


async def analyse(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "discovery")
    await emit(run_id, "Reading the brief for gaps and contradictions",
               agent="analyst", stage="discovery")

    # Memoised: the clarify gate below replays this node, and the stakeholder's
    # answers are keyed to the question ids they were actually shown.
    result = await remember(run_id, "discovery", lambda: ANALYST.json(
        f"EVIDENCE:\n\n{state['brief'][:12000]}\n\n"
        "Produce your understanding, signals, contradictions and clarifying questions."
    ))
    questions = result.get("questions", [])
    await save_artifact(run_id, "discovery", "discovery", result)
    await emit(
        run_id,
        f"{len(questions)} open questions; "
        f"{len(result.get('contradictions', []))} contradictions found",
        agent="analyst", stage="discovery",
        data={"understanding": result.get("understanding", ""), "questions": questions},
    )

    if not questions:
        return {"clarifications": [], "answers": {}}

    response = await raise_gate(
        run_id=run_id, kind="clarify", stage="discovery",
        question="The Analyst needs these answered before the vision is written.",
        artifact=result,
        fields=[
            {"id": q["id"], "label": q["question"], "help": q.get("why_it_matters", ""),
             "placeholder": q.get("proposed_default", ""), "type": "text"}
            for q in questions
        ],
        options=[
            {"value": "answer", "label": "Submit answers"},
            {"value": "use_defaults", "label": "Use the proposed defaults"},
        ],
        default={"decision": "use_defaults", "notes": ""},
    )

    if response.get("decision") == "use_defaults":
        answers = {q["id"]: q.get("proposed_default", "") for q in questions}
        await emit(run_id, "Proceeding on the Analyst's proposed defaults",
                   agent="analyst", stage="discovery", level="warn", data={"answers": answers})
    else:
        answers = {
            q["id"]: (response.get("answers", {}) or {}).get(q["id"])
            or q.get("proposed_default", "")
            for q in questions
        }

    answered = "\n".join(
        f"Q: {q['question']}\nA: {answers.get(q['id'], '')}" for q in questions
    )
    brief = (
        state["brief"]
        + "\n\n---\n\n[clarifications] Stakeholder answers to Analyst questions:\n"
        + answered
    )
    if response.get("notes"):
        brief += f"\n\n[stakeholder-note] {response['notes']}"

    return {"clarifications": questions, "answers": answers, "brief": brief,
            "log": [f"discovery: {json.dumps(answers)[:400]}"]}
