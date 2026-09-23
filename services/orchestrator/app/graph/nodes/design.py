"""Stage 5-6: architecture with enforced reuse, then sprint planning."""
from __future__ import annotations

from ...agents.base import ARCHITECT, PLANNER
from ...config import settings
from ...events import emit
from ...integrations import tracker
from ...kg.client import kg
from ...reuse.retriever import portfolio_context, render_for_prompt
from ..gates import raise_gate
from ..memo import remember
from ..state import RunState
from ..store import save_artifact, set_stage


async def architecture(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "architecture")

    await emit(run_id, "Querying the portfolio knowledge graph before designing anything",
               agent="architect", stage="architecture")
    ctx = await remember(run_id, "portfolio", lambda: portfolio_context(
        f"{state['vision'].get('problem_statement','')}\n"
        + "\n".join(s.get("narrative", "") for s in state["backlog"].get("stories", []))
    ))
    await emit(
        run_id,
        f"{len(ctx['reuse_candidates'])} reuse candidates across the portfolio "
        f"for terms: {', '.join(ctx['search_terms'])}",
        agent="architect", stage="architecture",
        data={"portfolio": ctx},
    )

    design = await remember(run_id, "architecture", lambda: ARCHITECT.json(
        f"VISION:\n{state['vision']}\n\n"
        f"BACKLOG:\n{state['backlog']}\n\n"
        f"PORTFOLIO KNOWLEDGE GRAPH:\n{render_for_prompt(ctx)}\n\n"
        "Produce the architecture, with an explicit reuse verdict per capability.",
        max_tokens=4000,
    ))
    await save_artifact(run_id, "architecture", "architecture", design)

    reuse = design.get("reuse_plan", [])
    reused = [r for r in reuse if r.get("verdict") in ("reuse", "extend")]
    new = [r for r in reuse if r.get("verdict") == "build_new"]
    unjustified = [r["need"] for r in new if not (r.get("rationale") or "").strip()]

    await emit(
        run_id,
        f"Reuse plan: {len(reused)} reused or extended, {len(new)} built new",
        agent="architect", stage="architecture",
        level="warn" if unjustified else "info",
        data={"reuse_plan": reuse, "unjustified": unjustified,
              "diagram": design.get("diagram_mermaid", "")},
    )

    response = await raise_gate(
        run_id=run_id, kind="approve_architecture", stage="architecture",
        question="Approve the design and its reuse decisions.",
        artifact={**design, "portfolio_context": ctx},
        options=[
            {"value": "approve", "label": "Approve architecture"},
            {"value": "force_reuse", "label": "Reject a build-new decision"},
            {"value": "revise", "label": "Revise with my comments"},
        ],
    )

    if response.get("decision") in ("revise", "force_reuse"):
        prior = design
        design = await remember(run_id, "architecture:revised", lambda: ARCHITECT.json(
            f"Your previous design:\n{prior}\n\n"
            f"ARCHITECTURE REVIEW FEEDBACK (binding):\n{response.get('notes','')}\n\n"
            f"PORTFOLIO KNOWLEDGE GRAPH:\n{render_for_prompt(ctx)}\n\n"
            "Produce the revised architecture.",
            max_tokens=4000,
        ))
        await save_artifact(run_id, "architecture", "architecture", design)

    project = state["vision"].get("product_name") or state.get("title", run_id)
    await kg().record_run(run_id, project, state["vision"])
    for decision in design.get("decisions", []):
        await kg().record_decision(run_id, project, decision)
    ids = [r["component_id"] for r in design.get("reuse_plan", [])
           if r.get("verdict") in ("reuse", "extend") and r.get("component_id")]
    if ids:
        await kg().record_reuse(project, ids)
        await emit(run_id, f"Recorded {len(ids)} reuse edges in the knowledge graph",
                   agent="architect", stage="architecture", data={"component_ids": ids})

    return {"portfolio": ctx, "architecture": design}


async def plan_sprint(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "sprint")
    capacity = settings().poiesis_max_sprint_stories

    sprint = await remember(run_id, "sprint", lambda: PLANNER.json(
        f"BACKLOG:\n{state['backlog']}\n\n"
        f"ARCHITECTURE REUSE PLAN:\n{state['architecture'].get('reuse_plan', [])}\n\n"
        f"CAPACITY: at most {capacity} stories this sprint.\n"
        "Cut sprint one."
    ))
    known = {s.get("id") for s in state["backlog"].get("stories", [])}
    # The Planner once cut an "S11" into a ten-story backlog: a story nobody wrote.
    sprint["stories"] = [e for e in sprint.get("stories", []) if e.get("id") in known][:capacity]
    await save_artifact(run_id, "sprint", "sprint", sprint)
    await emit(
        run_id,
        f"Sprint 1 goal: {sprint.get('sprint_goal', '')}",
        agent="planner", stage="sprint",
        data={"sprint": sprint, "count": len(sprint["stories"])},
    )

    response = await raise_gate(
        run_id=run_id, kind="approve_sprint", stage="sprint",
        question="This is what will be built now. Change the scope, or let it run.",
        artifact=sprint,
        options=[
            {"value": "approve", "label": "Start the build"},
            {"value": "revise", "label": "Change the sprint scope"},
        ],
    )
    if response.get("decision") == "revise" and response.get("notes"):
        prior = sprint
        sprint = await remember(run_id, "sprint:revised", lambda: PLANNER.json(
            f"Previous sprint plan:\n{prior}\n\nBACKLOG:\n{state['backlog']}\n\n"
            f"BINDING SCOPE CHANGE FROM STAKEHOLDER:\n{response['notes']}\n"
            f"CAPACITY: at most {capacity} stories."
        ))
        sprint["stories"] = [e for e in sprint.get("stories", []) if e.get("id") in known][:capacity]
        await save_artifact(run_id, "sprint", "sprint", sprint)

    await tracker.on_sprint(run_id, state, sprint)
    return {"sprint": sprint}
