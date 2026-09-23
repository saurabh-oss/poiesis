"""Stage: the data layer and the demonstration data, before any story.

Stories used to invent the schema one at a time — each rewriting models.py and
init.sql from a truncated view of the last story's version — and to write their
own seed rows, badly. Both are done once here: the Developer designs every
table from the whole backlog, and the Data Designer writes a generator the
platform runs, checks and renders into db/init.sql. Every story then builds a
screen over tables that exist and hold believable data, and the generic data
API already serves them.

Runs once per run; a rework round goes straight back to build. The data can be
regenerated on demand for a run (`POST /api/runs/{id}/reseed`), for when the
first set turns out to leave a screen with nothing to show.
"""
from __future__ import annotations

import time
from typing import Any

from ...agents.base import DATA_DESIGNER, FOUNDATION
from ...config import pack
from ...events import emit
from ...llm import ReplyTruncated, UnparseableReply
from ...workspace import repo
from ...workspace.checks import validate_init_sql
from ...workspace.interface import excerpt, EDITABLE
from ...workspace.seeding import (
    SEED_CONTRACT,
    SEED_SCRIPT,
    quality_issues,
    rows_to_sql,
    run_seed_script,
    size_issue,
    strip_seed_section,
    summary,
    tables_in,
    write_seed_section,
)
from ..memo import remember
from ..state import RunState
from ..store import save_artifact, set_stage
from .build import _apply, _refused_note

SEED_REPAIRS = 3


def enabled() -> bool:
    return bool(pack().get("build", {}).get("foundation", False))


def _stories(state: RunState) -> list[dict[str, Any]]:
    return list((state.get("backlog") or {}).get("stories") or [])


def _criteria(state: RunState) -> list[str]:
    out: list[str] = []
    for s in _stories(state):
        out += [str(c) for c in s.get("acceptance_criteria") or []]
    return out


def _brief_text(state: RunState, limit: int) -> str:
    vision = state.get("vision") or {}
    head = (f"PRODUCT: {vision.get('product_name', '')}\n{vision.get('value_proposition', '')}\n\n"
            if vision else "")
    return head + "BRIEF:\n" + str(state.get("brief") or "")[:limit]


def _schema_prompt(state: RunState, run_id: str) -> str:
    arch = state.get("architecture") or {}
    stories = "\n".join(
        f"- {s.get('id')}: {s.get('title')}\n" + "\n".join(f"    · {c}" for c in s.get("acceptance_criteria") or [])
        for s in _stories(state))
    return (
        _brief_text(state, 12000)
        + f"\n\nARCHITECT'S DATA MODEL (a starting point; complete it from the stories):\n{arch.get('data_model', [])}\n"
        + f"\nEVERY STORY AND ITS ACCEPTANCE CRITERIA (each one needs its columns):\n{stories}\n"
        + excerpt(run_id, EDITABLE)
        + "\nWrite the three files."
    )


def _seed_prompt(state: RunState, run_id: str) -> str:
    root = repo.workspace_path(run_id)
    sql = strip_seed_section((root / "db" / "init.sql").read_text(encoding="utf-8", errors="replace"))
    data_lines = [c for c in _criteria(state)
                  if any(w in c.lower() for w in ("at least", "demonstration", "sample", "demo", "seed", "realistic", "loaded"))]
    screens = "\n".join(f"- {s.get('id')}: {s.get('title')}" for s in _stories(state))
    return (
        _brief_text(state, 12000)
        + "\n\nWHAT THE STORIES EXPECT TO FIND ON FIRST OPEN:\n"
        + "\n".join(f"- {c}" for c in data_lines[:25])
        + "\n\nTHE SCREENS THAT WILL SHOW THIS DATA — each must open with something to show and something "
          "to do (a queue needs untriaged rows, an assign flow needs unassigned rows, a status board needs "
          "rows in every status):\n" + screens
        + f"\n\nTHE TABLES (db/init.sql, exactly as they are — every column name is what you use as a key):\n{sql[:14000]}\n\n"
        + SEED_CONTRACT
        + f"\nWrite {SEED_SCRIPT}."
    )


async def generate_seed(state: RunState, run_id: str, key_prefix: str, stage: str = "foundation",
                        extra_feedback: str = "") -> dict[str, Any]:
    """Ask the Data Designer for a generator, run it, check it, keep what passes.

    Returns {"rows": {table: count}, "problems": [...], "reasoning": str, "commit": str}.
    """
    tables = tables_in(run_id)
    base_prompt = _seed_prompt(state, run_id) + extra_feedback
    criteria = _criteria(state) + [str(state.get("brief") or "")[:6000]]
    feedback = ""
    rows: dict[str, list[dict[str, Any]]] | None = None
    seed_sql = ""
    problems: list[str] = []
    reply: dict[str, Any] = {}
    for attempt in range(SEED_REPAIRS + 1):
        try:
            reply = await remember(run_id, f"{key_prefix}:{attempt}", lambda: DATA_DESIGNER.json(
                base_prompt + feedback, max_tokens=9000))
        except (ReplyTruncated, UnparseableReply) as exc:
            # A reply that does not fit is the rows written out as literals.
            reply = {"files": {}, "reasoning": ""}
            problems = [f"your reply could not be used ({type(exc).__name__}): it was too long to finish. "
                        f"{SEED_SCRIPT} must be a generator of at most 300 lines, never the rows as literals"]
            await emit(run_id, f"Demonstration data, attempt {attempt + 1}: " + problems[0][:200],
                       agent="data_designer", stage=stage, level="warn")
            feedback = "\n\nYOUR PREVIOUS REPLY WAS CUT OFF: " + problems[0] + "\nReturn a short generator."
            continue
        script = (reply.get("files") or {}).get(SEED_SCRIPT)
        rows = None
        if not isinstance(script, str) or not script.strip():
            problems = [f"the reply contained no {SEED_SCRIPT}"]
        elif size_issue(script):
            problems = [size_issue(script)]
        else:
            repo.write_files(run_id, {SEED_SCRIPT: script})
            rows, error = await run_seed_script(run_id)
            if rows is None:
                problems = [error]
            else:
                seed_sql, problems = rows_to_sql(rows, tables)
                problems += quality_issues(rows, criteria, tables)
                if not problems:
                    write_seed_section(run_id, seed_sql)
                    check = await validate_init_sql(run_id)
                    if not check.ok:
                        problems = ["the generated INSERT statements were rejected by Postgres: "
                                    + check.stdout.strip()[-600:]]
        if not problems:
            break
        await emit(run_id, f"Demonstration data, attempt {attempt + 1}: " + "; ".join(p[:160] for p in problems[:4]),
                   agent="data_designer", stage=stage, level="warn", data={"problems": problems})
        feedback = ("\n\nYOUR PREVIOUS seed.py WAS RUN. It cannot be used as it is:\n"
                    + "\n".join(f"- {p}" for p in problems[:12])
                    + "\nReturn the whole corrected file.")
    else:
        # The seed never met the bar; whatever the last run produced is still better than nothing.
        if rows and seed_sql:
            write_seed_section(run_id, seed_sql)
            if not (await validate_init_sql(run_id)).ok:
                write_seed_section(run_id, "")
                seed_sql = ""
        await emit(run_id, "The demonstration data still has problems; carrying on with what runs",
                   agent="data_designer", stage=stage, level="error", data={"problems": problems})

    sha = repo.commit(run_id, reply.get("commit_message") or "feat(data): demonstration data") if rows else None
    counts = {t: len(r) for t, r in (rows or {}).items() if isinstance(r, list)}
    await emit(run_id, f"Demonstration data loaded into db/init.sql: {summary(rows or {})}",
               agent="data_designer", stage=stage,
               data={"tables": counts, "commit": sha, "reasoning": reply.get("reasoning", "") if rows else ""})
    return {"rows": counts, "problems": problems, "reasoning": reply.get("reasoning", ""), "commit": sha}


async def lay_foundation(state: RunState) -> RunState:
    run_id = state["run_id"]
    if not enabled() or state.get("foundation"):
        return {}
    await set_stage(run_id, "foundation")
    repo.init_workspace(run_id)

    # 1. The schema, from the whole backlog at once.
    await emit(run_id, "Designing the data model for every story at once", agent="developer", stage="foundation")
    prompt = _schema_prompt(state, run_id)
    try:
        impl = await remember(run_id, "foundation:schema", lambda: FOUNDATION.json(prompt, max_tokens=14000))
    except (ReplyTruncated, UnparseableReply) as exc:
        await emit(run_id, f"The data model reply could not be read ({type(exc).__name__}); asking again, shorter",
                   agent="developer", stage="foundation", level="warn")
        impl = await remember(run_id, "foundation:schema:retry", lambda: FOUNDATION.json(
            prompt + "\n\nYour previous reply was too long or unreadable. Keep every file compact: no "
                     "docstrings beyond one line, no comments except the allowed-values ones.", max_tokens=14000))
    written, sha, refused = await _apply(run_id, state, "S0", impl.get("files", {}),
                                         impl.get("commit_message") or "feat(foundation): data model")
    rejected = [r for r in refused if "REJECTED" in r]
    if rejected:
        await emit(run_id, "The data model did not execute; asking for a corrected one",
                   agent="developer", stage="foundation", level="warn", data={"refused": rejected})
        fix = await remember(run_id, "foundation:schema:fix", lambda: FOUNDATION.json(
            prompt + _refused_note(refused) + "\nReturn all three files corrected.", max_tokens=14000))
        written, sha, refused = await _apply(run_id, state, "S0", fix.get("files", {}),
                                             "fix(foundation): data model")
    tables = tables_in(run_id)
    await emit(run_id, f"Data model in place: {len(tables)} table(s) — " + ", ".join(sorted(tables)),
               agent="developer", stage="foundation",
               data={"files": written, "commit": sha, "reasoning": impl.get("reasoning", "")})

    # 2. The demonstration data: a generator, run and checked here.
    await emit(run_id, "Writing the demonstration data generator", agent="data_designer", stage="foundation")
    seed = await generate_seed(state, run_id, "foundation:seed")
    record = {
        "tables": sorted(tables),
        "rows": seed["rows"],
        "problems": seed["problems"],
        "commit": seed["commit"] or sha,
    }
    await save_artifact(run_id, "foundation", "foundation", record)
    return {"foundation": record}


async def reseed(run_id: str, notes: str = "") -> dict[str, Any]:
    """Regenerate a run's demonstration data from its checkpointed state.

    The next deploy (a rework round, a rebuild from the release gate) starts the
    database from the new rows. `notes` is what the stakeholder wants different.
    """
    from ..engine import config_for, graph  # local: engine imports the graph, which imports this module
    g = await graph()
    snapshot = await g.aget_state(config_for(run_id))
    state: RunState = dict(snapshot.values)  # type: ignore[assignment]
    state["run_id"] = run_id
    if not state.get("backlog"):
        raise ValueError("this run has no backlog yet; the data is designed from it")
    repo.init_workspace(run_id)
    await emit(run_id, "Regenerating the demonstration data" + (f": {notes}" if notes else ""),
               agent="data_designer", stage="foundation")
    extra = f"\n\nWHAT THE STAKEHOLDER WANTS DIFFERENT THIS TIME:\n{notes}\n" if notes else ""
    seed = await generate_seed(state, run_id, f"reseed:{int(time.time())}", stage="foundation", extra_feedback=extra)
    await save_artifact(run_id, "foundation", "foundation",
                        {"tables": sorted(tables_in(run_id)), "rows": seed["rows"],
                         "problems": seed["problems"], "commit": seed["commit"], "reseeded": True})
    return seed
