"""Stage 3-4: Product Vision, then Product Backlog. Both gated."""
from __future__ import annotations

from ...agents import schemas
from ...agents.base import PRODUCT_OWNER
from ...config import pack
from ...events import emit
from ...integrations import tracker
from ..gates import raise_gate
from ..memo import remember
from ..state import RunState
from ..store import save_artifact, set_stage, set_title

MAX_REVISIONS = 2


async def vision(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "vision")
    feedback = ""

    for attempt in range(MAX_REVISIONS + 1):
        await emit(run_id, "Drafting the product vision" if attempt == 0
                   else f"Revising the vision (round {attempt})",
                   agent="product_owner", stage="vision")
        # Keyed by attempt: replaying the approval gate must return the draft the
        # stakeholder read, while a genuine revision round writes a new one.
        doc = await remember(run_id, f"vision:{attempt}", lambda: PRODUCT_OWNER.json(
            f"Produce the VISION.\n\nEVIDENCE:\n{state['brief'][:40000]}\n{feedback}",
            schema=schemas.VISION,
        ))
        await save_artifact(run_id, "vision", "vision", doc)
        await emit(run_id, f"Vision drafted: {doc.get('product_name', 'untitled')}",
                   agent="product_owner", stage="vision", data={"vision": doc})

        response = await raise_gate(
            run_id=run_id, kind="approve_vision", stage="vision",
            question="Does this describe the product you asked for?",
            artifact=doc,
            options=[
                {"value": "approve", "label": "Approve vision"},
                {"value": "revise", "label": "Revise with my comments"},
            ],
        )
        if response.get("decision") != "revise" or attempt == MAX_REVISIONS:
            title = doc.get("product_name") or state.get("title", "")
            await set_title(run_id, title)
            return {"vision": doc, "title": title}
        feedback = f"\n\nSTAKEHOLDER REVISION REQUEST:\n{response.get('notes', '')}"

    return {"vision": doc}


async def backlog(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "backlog")
    feedback = ""

    for attempt in range(MAX_REVISIONS + 1):
        await emit(run_id, "Building the product backlog" if attempt == 0
                   else f"Reworking the backlog (round {attempt})",
                   agent="product_owner", stage="backlog")
        dor = pack().get("definition_of_ready", [])
        guidance = str(pack().get("product", {}).get("guidance") or "").strip()
        doc = await remember(run_id, f"backlog:{attempt}", lambda: PRODUCT_OWNER.json(
            "Produce the BACKLOG.\n\n"
            + (f"HOW THIS ORGANISATION WANTS ITS BACKLOG SHAPED:\n{guidance}\n\n" if guidance else "")
            + ("DEFINITION OF READY - every story must satisfy all of these:\n"
               + "\n".join(f"- {d}" for d in dor) + "\n\n" if dor else "")
            + f"APPROVED VISION:\n{state['vision']}\n\n"
            f"EVIDENCE:\n{state['brief'][:30000]}\n{feedback}",
            max_tokens=6000, schema=schemas.BACKLOG,
        ))
        stories = doc.get("stories", [])
        thin = [s["id"] for s in stories if len(s.get("acceptance_criteria", [])) < 2]
        if thin and attempt < MAX_REVISIONS:
            feedback = (
                f"\n\nREJECTED BY DEFINITION OF READY: stories {thin} have fewer than two "
                "acceptance criteria. Rewrite them or merge them into another story."
            )
            await emit(run_id, f"{len(thin)} stories failed definition of ready",
                       agent="product_owner", stage="backlog", level="warn",
                       data={"stories": thin})
            continue

        await save_artifact(run_id, "backlog", "backlog", doc)
        await emit(
            run_id,
            f"{len(doc.get('epics', []))} epics, {len(stories)} stories, "
            f"{sum(s.get('estimate', 0) for s in stories)} points",
            agent="product_owner", stage="backlog", data={"backlog": doc},
        )

        response = await raise_gate(
            run_id=run_id, kind="approve_backlog", stage="backlog",
            question="Approve this backlog, or reprioritise before the sprint is cut.",
            artifact=doc,
            options=[
                {"value": "approve", "label": "Approve backlog"},
                {"value": "revise", "label": "Reprioritise / rewrite"},
            ],
        )
        if response.get("decision") != "revise" or attempt == MAX_REVISIONS:
            await tracker.on_backlog(run_id, state, doc)
            return {"backlog": doc}
        feedback = f"\n\nSTAKEHOLDER REVISION REQUEST:\n{response.get('notes', '')}"

    return {"backlog": doc}
