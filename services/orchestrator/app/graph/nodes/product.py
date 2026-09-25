"""Stage 3-4: Product Vision, then Product Backlog. Both gated.

The backlog is checked against the brief before anyone approves it. The enterprise
DupeGuard run's backlog had nine stories for a brief with ten screens, and the Accuracy
& settings screen — where every threshold and approval rule of the brief lived — was
never built. Now the platform lists what the brief requires (requirements.py), asks the
Product Owner which requirements each story delivers, and has it write the stories that
are missing before the gate.
"""
from __future__ import annotations

import re
from typing import Any

from ... import requirements as req
from ...agents import schemas
from ...agents.base import PRODUCT_OWNER, REQUIREMENTS
from ...config import pack
from ...events import emit
from ...integrations import tracker
from ...llm import ReplyTruncated, UnparseableReply
from ..gates import raise_gate
from ..memo import remember
from ..state import RunState
from ..store import save_artifact, set_stage, set_title

MAX_REVISIONS = 2
# Focused rounds asking only for the stories the backlog is missing.
ADDITION_ROUNDS = 2


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


def domain_layer() -> bool:
    return bool(pack().get("build", {}).get("domain", False))


async def inventory(state: RunState, run_id: str) -> list[dict[str, Any]]:
    """What the brief requires: its own numbered items, classified, plus what it left unnumbered."""
    defined = req.defined_ids(state.get("evidence") or [])
    ids = ", ".join(d["id"] for d in defined)
    items: list[dict[str, Any]] = []
    try:
        reply = await remember(run_id, "requirements", lambda: REQUIREMENTS.json(
            f"IDS THE BRIEF DEFINES (each must be in your list exactly once):\n{ids or '(none)'}\n\n"
            f"BRIEF:\n{state['brief'][:40000]}\n\nList every requirement.",
            max_tokens=16000,
        ))
        items = reply.get("items") or []
    except (ReplyTruncated, UnparseableReply) as exc:
        await emit(run_id, f"Could not classify the brief's requirements ({type(exc).__name__}); "
                           "checking against the ids it defines", agent="analyst", stage="backlog", level="warn")
    inv = req.merge(defined, items, state.get("brief") or "")
    await save_artifact(run_id, "requirements", "backlog", {"items": inv, "defined": len(defined)})
    kinds: dict[str, int] = {}
    for it in inv:
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    await emit(run_id, f"The brief states {len(inv)} requirements ("
                       + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])) + ")",
               agent="analyst", stage="backlog", data={"requirements": inv})
    return inv


def _next_ids(stories: list[dict[str, Any]]) -> int:
    nums = [int(m.group(1)) for s in stories if (m := re.fullmatch(r"S(\d+)", str(s.get("id") or "")))]
    return max(nums, default=0) + 1


def _best_epic(story: dict[str, Any], epics: list[dict[str, Any]]) -> str:
    words = set(re.findall(r"[a-z]{4,}", f"{story.get('title')} {story.get('narrative')}".lower()))
    scored = [(len(words & set(re.findall(r"[a-z]{4,}", f"{e.get('title')} {e.get('outcome')}".lower()))), e["id"])
              for e in epics if e.get("id")]
    return max(scored)[1] if scored else ""


def merge_additions(doc: dict[str, Any], additions: dict[str, Any]) -> list[str]:
    """Append the new stories under fresh ids; returns the ids given."""
    stories = doc.setdefault("stories", [])
    epics = doc.get("epics") or []
    epic_ids = {e.get("id") for e in epics}
    known = {s.get("id") for s in stories}
    n = _next_ids(stories)
    added: list[str] = []
    renamed: dict[str, str] = {}
    for s in additions.get("stories") or []:
        if len(s.get("acceptance_criteria") or []) < 2:
            continue
        new_id = f"S{n}"
        n += 1
        renamed[str(s.get("id"))] = new_id
        s = {**s, "id": new_id}
        if s.get("epic_id") not in epic_ids:
            s["epic_id"] = _best_epic(s, epics)
        stories.append(s)
        added.append(new_id)
    for s in stories:
        if s.get("id") in added:
            # An id the backlog already has means that story; otherwise it is a new story, renamed.
            deps = [d if d in known else renamed.get(d) for d in s.get("depends_on") or []]
            s["depends_on"] = [d for d in dict.fromkeys(deps) if d and d != s["id"]]
    have = {req.norm(x.get("id")) for x in doc.get("not_covered") or []}
    for x in additions.get("not_covered") or []:
        if req.norm(x.get("id")) not in have and str(x.get("reason") or "").strip():
            doc.setdefault("not_covered", []).append(x)
    return added


async def _add_missing(run_id: str, state: RunState, doc: dict[str, Any], missing: list[dict[str, Any]],
                       key: str) -> list[str]:
    dor = pack().get("definition_of_ready", [])
    have = "\n".join(f"- {s.get('id')} [{s.get('epic_id')}] {s.get('title')} (covers: "
                     f"{', '.join(s.get('covers') or []) or '-'})" for s in doc.get("stories") or [])
    epics = "\n".join(f"- {e.get('id')}: {e.get('title')} — {e.get('outcome', '')}" for e in doc.get("epics") or [])
    additions = await remember(run_id, key, lambda: PRODUCT_OWNER.json(
        "The backlog below leaves requirements of the brief without a story. Write the stories that "
        "deliver them.\n\n"
        f"REQUIREMENTS WITH NO STORY:\n{req.describe(missing)}\n\n"
        "RULES:\n- A screen or capability gets its own story; related functional requirements and acceptance "
        "criteria join the story for that screen.\n- Each story lists in `covers` every requirement id it "
        "delivers, and its acceptance criteria test them, keeping the brief's numbers.\n- Use an existing epic "
        "id.\n- Only when the brief itself puts a requirement out of scope, list it in `not_covered` with that "
        "reason instead; a screen the brief names is never left out.\n"
        + ("- Every story satisfies the definition of ready:\n" + "\n".join(f"  - {d}" for d in dor) + "\n" if dor else "")
        + f"\nEPICS:\n{epics}\n\nSTORIES ALREADY IN THE BACKLOG:\n{have}\n\n"
        f"APPROVED VISION:\n{state['vision']}\n\nEVIDENCE:\n{state['brief'][:24000]}",
        max_tokens=6000, schema=schemas.BACKLOG_ADDITIONS,
    ))
    return merge_additions(doc, additions)


async def check_coverage(run_id: str, state: RunState, doc: dict[str, Any], inv: list[dict[str, Any]],
                         attempt: int) -> dict[str, Any]:
    """Make the backlog cover the brief, in focused rounds; returns the coverage record."""
    layer = domain_layer()
    cov = req.backlog_coverage(inv, doc, layer)
    for rnd in range(ADDITION_ROUNDS):
        if not cov["missing"]:
            break
        await emit(run_id, f"{len(cov['missing'])} requirement(s) of the brief have no story: "
                           + ", ".join(cov["missing"][:12]) + "; asking for the stories",
                   agent="product_owner", stage="backlog", level="warn", data={"missing": cov["missing"]})
        try:
            added = await _add_missing(run_id, state, doc, cov["missing_items"], f"backlog:{attempt}:add:{rnd}")
        except (ReplyTruncated, UnparseableReply):
            added = []
        cov = req.backlog_coverage(inv, doc, layer)
        if added:
            await emit(run_id, f"Added {len(added)} story(ies): " + ", ".join(
                f"{s['id']} {s.get('title')}" for s in doc["stories"] if s["id"] in added),
                agent="product_owner", stage="backlog", data={"added": added})
    level = "warn" if cov["missing"] else "info"
    await emit(run_id, f"Backlog covers {cov['covered']} of {cov['total']} requirements of the brief"
                       + (f"; {cov['excused']} left out with a reason" if cov["excused"] else "")
                       + (f"; still without a story: {', '.join(cov['missing'])}" if cov["missing"] else ""),
               agent="product_owner", stage="backlog", level=level,
               data={"coverage": {k: v for k, v in cov.items() if k != "missing_items"}})
    return {k: v for k, v in cov.items() if k != "missing_items"}


async def backlog(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "backlog")
    feedback = ""
    inv = await inventory(state, run_id)
    listed = req.describe([it for it in inv if req.needs_story(it, domain_layer())], limit=120)

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
            + ("REQUIREMENTS OF THE BRIEF THE STORIES MUST DELIVER (list each story's ids in `covers`; every one "
               f"needs a story, or an entry in `not_covered` with the brief's own reason):\n{listed}\n\n" if listed else "")
            + f"APPROVED VISION:\n{state['vision']}\n\n"
            f"EVIDENCE:\n{state['brief'][:30000]}\n{feedback}",
            max_tokens=9000, schema=schemas.BACKLOG,
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

        doc["coverage"] = await check_coverage(run_id, state, doc, inv, attempt)
        stories = doc.get("stories", [])
        await save_artifact(run_id, "backlog", "backlog", doc)
        await emit(
            run_id,
            f"{len(doc.get('epics', []))} epics, {len(stories)} stories, "
            f"{sum(s.get('estimate', 0) for s in stories)} points",
            agent="product_owner", stage="backlog", data={"backlog": doc},
        )

        missing = doc["coverage"].get("missing") or []
        response = await raise_gate(
            run_id=run_id, kind="approve_backlog", stage="backlog",
            question="Approve this backlog, or reprioritise before the sprint is cut."
                     + (f" {len(missing)} requirement(s) of the brief still have no story: {', '.join(missing[:10])}."
                        if missing else ""),
            artifact=doc,
            options=[
                {"value": "approve", "label": "Approve backlog"},
                {"value": "revise", "label": "Reprioritise / rewrite"},
            ],
        )
        if response.get("decision") != "revise" or attempt == MAX_REVISIONS:
            await tracker.on_backlog(run_id, state, doc)
            return {"backlog": doc, "requirements": inv}
        feedback = f"\n\nSTAKEHOLDER REVISION REQUEST:\n{response.get('notes', '')}"

    return {"backlog": doc, "requirements": inv}
