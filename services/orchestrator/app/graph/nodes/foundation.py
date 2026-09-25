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
    quality_issues,
    rows_to_sql,
    strip_seed_section,
    summary,
    tables_in,
    write_seed_section,
)
from ...workspace.seedspec import SPEC_CONTRACT, SPEC_FILE, expand_spec, spec_schema
from ..memo import remember
from ..state import RunState
from ..store import save_artifact, set_stage
from .build import _apply, _refused_note

SEED_REPAIRS = 4
_SOFT = __import__("re").compile(r"is not a column of its CREATE TABLE|do not exist in its CREATE TABLE")


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
        _brief_text(state, 40000)
        + f"\n\nARCHITECT'S DATA MODEL (a starting point; complete it from the stories):\n{arch.get('data_model', [])}\n"
        + f"\nEVERY STORY AND ITS ACCEPTANCE CRITERIA (each one needs its columns):\n{stories}\n"
        + excerpt(run_id, EDITABLE)
        + "\nWrite the three files."
    )


def _domain_note(state: RunState) -> str:
    """The seed must speak the domain's language: workflow states and the personas' names."""
    d = state.get("domain") or {}
    if not d.get("imports"):
        return ""
    flows = "\n".join(f"- {w['entity']}.{w.get('field', 'status')}: use only these states, spread across all of them: "
                      f"{', '.join(w['states'])}" for w in d.get("workflows", []))
    people = "\n".join(f"- {p.get('full_name')} ({', '.join(p.get('roles') or [])}, {p.get('title') or ''})"
                       for p in d.get("personas", []))
    return ("\n\nTHE APPLICATION'S LIFECYCLES (a seeded status outside them breaks its workflow):\n" + (flows or "- none")
            + "\n\nTHE PEOPLE WHO SIGN IN. Where a table holds people (agents, owners, assignees, approvers, "
              "requesters), use these exact full names for a good share of the rows, alongside others, so each "
              "persona finds their own work on first sign-in:\n" + (people or "- none") + "\n")


def _seed_prompt(state: RunState, run_id: str) -> str:
    root = repo.workspace_path(run_id)
    sql = strip_seed_section((root / "db" / "init.sql").read_text(encoding="utf-8", errors="replace"))
    data_lines = [c for c in _criteria(state)
                  if any(w in c.lower() for w in ("at least", "demonstration", "sample", "demo", "seed", "realistic", "loaded"))]
    screens = "\n".join(f"- {s.get('id')}: {s.get('title')}" for s in _stories(state))
    return (
        _brief_text(state, 40000)
        + "\n\nWHAT THE STORIES EXPECT TO FIND ON FIRST OPEN:\n"
        + "\n".join(f"- {c}" for c in data_lines[:25])
        + "\n\nTHE SCREENS THAT WILL SHOW THIS DATA — each must open with something to show and something "
          "to do (a queue needs untriaged rows, an assign flow needs unassigned rows, a status board needs "
          "rows in every status):\n" + screens
        + _domain_note(state)
        + f"\n\nTHE TABLES (db/init.sql, exactly as they are — every column name is what you use as a key):\n{sql[:14000]}\n\n"
        + SPEC_CONTRACT
        + "\nWrite the spec."
    )


async def generate_seed(state: RunState, run_id: str, key_prefix: str, stage: str = "foundation",
                        extra_feedback: str = "") -> dict[str, Any]:
    """Ask the Data Designer for a generator, run it, check it, keep what passes.

    Returns {"rows": {table: count}, "problems": [...], "reasoning": str, "commit": str}.
    """
    tables = tables_in(run_id)
    base_prompt = _seed_prompt(state, run_id) + extra_feedback
    criteria = _criteria(state) + [str(state.get("brief") or "")]
    schema = spec_schema(sorted(t for t in tables if t != "example"))
    feedback = ""
    rows: dict[str, list[dict[str, Any]]] | None = None
    seed_sql = ""
    problems: list[str] = []
    reply: dict[str, Any] = {}
    for attempt in range(SEED_REPAIRS + 1):
        try:
            reply = await remember(run_id, f"{key_prefix}:{attempt}", lambda: DATA_DESIGNER.json(
                base_prompt + feedback, max_tokens=12000, schema=schema))
        except (ReplyTruncated, UnparseableReply) as exc:
            reply = {"tables": [], "reasoning": ""}
            problems = [f"your reply could not be used ({type(exc).__name__}): it was too long to finish. "
                        "Keep records to 30-40 per large table and bodies to two sentences"]
            await emit(run_id, f"Demonstration data, attempt {attempt + 1}: " + problems[0][:200],
                       agent="data_designer", stage=stage, level="warn")
            feedback = "\n\nYOUR PREVIOUS REPLY WAS CUT OFF: " + problems[0] + "\nReturn a shorter spec."
            continue
        rows, problems, derived = expand_spec(reply, tables)
        # A column the table does not have is dropped when the rows are rendered; say
        # so, but it is no reason to throw away an otherwise good data set.
        dropped = [p for p in problems if _SOFT.search(p)]
        problems = [p for p in problems if not _SOFT.search(p)]
        # The enterprise DupeGuard run's first spec was 81 KB of one table (customers) and
        # nothing else: tickets, clusters and known issues all opened empty, and nothing
        # said so. Every table a screen can show needs rows.
        empty = sorted(t for t in tables if t != "example" and not (rows or {}).get(t))
        if rows is not None and empty:
            problems.append(
                f"the spec gives no rows for {len(empty)} table(s): {', '.join(empty)}. Every table needs rows — "
                "write a short entry for each (catalogues of 10-25 values, not hundreds) before elaborating any one")
        if dropped:
            await emit(run_id, "Demonstration data: ignored " + "; ".join(d[:120] for d in dropped[:4]),
                       agent="data_designer", stage=stage, level="info")
        if rows and not problems:
            import json as _json
            repo.write_files(run_id, {SPEC_FILE: _json.dumps(reply, indent=1)})
            seed_sql, problems = rows_to_sql(rows, tables)
            problems = [p for p in problems if not _SOFT.search(p)]
            problems += quality_issues(rows, criteria, tables, derived)
            if not problems:
                write_seed_section(run_id, seed_sql)
                check = await validate_init_sql(run_id)
                if not check.ok:
                    problems = ["the generated INSERT statements were rejected by Postgres: "
                                + check.stdout.strip()[-600:]]
        elif not rows and not problems:
            problems = ["the spec produced no rows"]
        if not problems:
            break
        await emit(run_id, f"Demonstration data, attempt {attempt + 1}: " + "; ".join(p[:160] for p in problems[:4]),
                   agent="data_designer", stage=stage, level="warn", data={"problems": problems})
        feedback = ("\n\nYOUR PREVIOUS SPEC WAS EXPANDED. It cannot be used as it is:\n"
                    + "\n".join(f"- {p}" for p in problems[:12])
                    + "\nReturn the whole corrected spec.")
    else:
        # The seed never met the bar; whatever the last attempt produced is still better
        # than an empty app, once its required gaps are filled.
        if rows:
            from ...workspace.seeding import fill_required
            filled = fill_required(rows, tables)
            seed_sql, _ = rows_to_sql(rows, tables)
            if filled:
                await emit(run_id, "Demonstration data: " + "; ".join(filled[:6]),
                           agent="data_designer", stage=stage, level="warn")
        if rows and seed_sql:
            # Keep the spec these rows came from, as the passing path does: a later
            # re-expansion or reseed must start from the data that is actually loaded.
            import json as _json
            repo.write_files(run_id, {SPEC_FILE: _json.dumps(reply, indent=1)})
            write_seed_section(run_id, seed_sql)
            check = await validate_init_sql(run_id)
            if not check.ok:
                write_seed_section(run_id, "")
                seed_sql = ""
                rows = None
                await emit(run_id, "Demonstration data rejected by Postgres; the app starts empty: "
                                   + check.stdout.strip()[-300:],
                           agent="data_designer", stage=stage, level="error")
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

    # 2. The business logic (enterprise pack): policy, rules, workflows, services, rule tests.
    from .domain import design_domain, enabled as domain_enabled
    domain: dict = {}
    if domain_enabled(run_id):
        domain = await design_domain({**state, "foundation": {"tables": sorted(tables)}}, run_id)
        state = {**state, "domain": domain}  # type: ignore[assignment]

    # 3. The demonstration data: a generator, run and checked here.
    await emit(run_id, "Writing the demonstration data generator", agent="data_designer", stage="foundation")
    seed = await generate_seed(state, run_id, "foundation:seed")
    record = {
        "tables": sorted(tables),
        "rows": seed["rows"],
        "problems": seed["problems"],
        "commit": seed["commit"] or sha,
    }
    await save_artifact(run_id, "foundation", "foundation", record)
    if domain:
        await save_artifact(run_id, "domain", "foundation", domain)
        return {"foundation": record, "domain": domain}
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
