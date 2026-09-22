"""Stage 9-10: independent review with a weighted verdict, then release and harvest.

Review now runs after the increment has been deployed and opened in a real
browser (see deploy.py), and judges what that proved. A released app once showed
nothing but the scaffold placeholder because review read code and test reports
only; the live check is now part of the verdict, and release refuses an app that
is not proven working.
"""
from __future__ import annotations

import re
from typing import Any

from ...agents import schemas
from ...agents.base import RELEASE, REVIEWER
from ...kg import vectors
from ...llm import complete_json
from ...config import pack
from ...events import emit
from ...integrations import gitremote, tracker
from ...kg.client import kg
from ...workspace import browser_check, repo
from ...workspace import checks as platform_checks_mod
from ...workspace import deployment as runtime
from ...workspace.interface import EXAMPLE_ROUTER, EXAMPLE_SCREEN
from ..gates import raise_gate
from ..memo import remember
from ..state import RunState
from ..store import save_artifact, set_stage


def _seeded_row_count(run_id: str) -> int:
    """How many rows the shipped database starts with, ignoring the worked example."""
    path = repo.workspace_path(run_id) / "db" / "init.sql"
    if not path.is_file():
        return 0
    grouped = platform_checks_mod._inserts_by_table(
        path.read_text(encoding="utf-8", errors="replace"))
    return sum(platform_checks_mod._seed_rows(v)
               for t, v in grouped.items() if t != "example")


# Files whose breakage can take the whole application down rather than one
# screen: the database, the shared schema, and a router (an import error in one
# router crashes FastAPI's whole app, not just its own endpoint). A screen is
# deliberately not here — a broken screen fails in the browser, never at
# deploy, so including it would blame whichever story simply ran last.
_DEPLOY_RISK_PREFIXES = (
    "db/init.sql", "backend/app/models.py", "backend/app/schemas.py", "backend/app/routers/",
)


def _attribute_to_last_writer(state: RunState) -> str | None:
    """Which story most recently touched a file likely to break the whole app.

    A deploy failure — the database container crash-looping, the compose build
    itself failing — has no story_id of its own, and an unattributed blocker
    forces every story in the sprint to be rebuilt to fix what one of them
    broke. Stories run in a fixed order within a round, so the last one whose
    own files list touches a shared, deploy-critical file is the likeliest
    cause; attributing to it turns an N-story rebuild into a 1-story one.
    Returns None when nothing points at a single story, and the old,
    conservative full-sprint rebuild is what's left.
    """
    stories = (state.get("test_report") or {}).get("stories", [])
    for result in reversed(stories):
        if result.get("status") == "dropped":
            continue
        files = result.get("files") or []
        if any(f.startswith(_DEPLOY_RISK_PREFIXES) for f in files):
            return result.get("story_id")
    return None

DEFAULT_WEIGHTS = {
    "acceptance_criteria_met": 0.35,
    "reuse_compliance": 0.15,
    "test_adequacy": 0.20,
    "maintainability": 0.15,
    "operational_safety": 0.15,
}


def weights() -> dict[str, float]:
    """The pack owns the scoring policy; these are only the fallback."""
    configured = pack().get("review", {}).get("weights") or {}
    return {k: float(v) for k, v in configured.items()} or DEFAULT_WEIGHTS


def weighted_score(dimensions: dict) -> float:
    """Normalised so a pack whose weights do not sum to 1 still scores out of 100."""
    active = weights()
    total = sum(
        float((dimensions.get(key) or {}).get("score", 0)) * weight
        for key, weight in active.items()
    )
    divisor = sum(active.values()) or 1.0
    return round(total / divisor, 1)


def _rank(path: str) -> int:
    """Story code first. The scaffold is platform-owned and already verified."""
    p = path.replace("\\", "/")
    if p.startswith("backend/app/routers/") and not p.endswith(("__init__.py", "examples.py")):
        return 0
    if p.startswith("frontend/screens/") and not p.endswith(("index.js", "example.js")):
        return 0
    if p in ("backend/app/schemas.py", "backend/app/models.py", "db/init.sql"):
        return 1
    if p.startswith("tests/") and "scaffold" not in p and "conftest" not in p:
        return 2
    if p == "backend/requirements.txt":
        return 3
    return 9


def _review_sample(run_id: str, budget: int = 20000) -> str:
    """The code the Reviewer judges, inside a local model's context.

    It used to be the first 25 files of the tree, alphabetically — mostly
    scaffold, with story code cut off — capped at 40k characters, more than the
    model's whole context.
    """
    chosen = sorted((p for p in repo.tree(run_id) if _rank(p) < 9), key=lambda p: (_rank(p), p))
    blocks: list[str] = []
    used = 0
    for path in chosen:
        body = repo.read(run_id, path, 5000)
        block = f"### {path}\n{body}"
        if used + len(block) > budget:
            blocks.append(f"### {path}\n(omitted for length)")
            continue
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _test_summary(state: RunState) -> str:
    lines = []
    for s in (state.get("test_report") or {}).get("stories", []):
        line = (f"- {s.get('story_id')} {s.get('status')}: {s.get('repair_attempts', 0)} repairs; "
                f"criteria covered {len(s.get('criteria_covered') or [])}, "
                f"not covered {s.get('criteria_not_covered') or []}")
        if s.get("status") not in ("green", "dropped") and s.get("test_output"):
            line += f"\n  last output: …{str(s['test_output'])[-700:]}"
        if s.get("reason"):
            line += f"\n  reason: {s['reason']}"
        lines.append(line)
    return "\n".join(lines) or "(no stories were built)"


def live_check(state: RunState) -> dict[str, Any]:
    """What the running application proved, as findings the verdict can count.

    Returns {working, summary, findings, screens}. Findings name the story whose
    screen failed, so a rework round rebuilds that story and not the sprint.
    """
    sc = state.get("scaffold") or {}
    dep = state.get("deployment") or {}
    status = dep.get("status")
    if status == "not_applicable":
        return {"working": True, "summary": "This archetype has nothing to run.",
                "findings": [], "screens": []}
    if status != "running":
        detail = str(dep.get("detail") or "no detail was recorded")[-900:]
        finding = {
            "severity": "blocker", "file": "docker-compose.yml",
            "finding": f"The application did not start when it was deployed: {detail}",
            "required_fix": "Make every service start: a package missing from "
                            "requirements.txt, an error in init.sql or an import error "
                            "in a router are the usual causes.",
        }
        suspect = _attribute_to_last_writer(state)
        if suspect:
            finding["story_id"] = suspect
        return {"working": False, "summary": "The application did not start.", "screens": [],
                "findings": [finding]}
    if sc.get("entrypoint") != "frontend":
        return {"working": True, "summary": f"Running at {dep.get('url')}; no interface to open.",
                "findings": [], "screens": []}

    v = dep.get("verification") or {}
    screens = [s for s in v.get("screens", []) if not s.get("example")]
    rows = [{"id": s.get("id"), "title": s.get("title"), "story": s.get("story"),
             "ok": bool(s.get("ok")), "problems": s.get("problems", []),
             "text": str(s.get("text") or "")[:300],
             # What the screen actually pulled from the database and what a user
             # can do on it: "it opened without errors" was never enough to tell
             # a working application from a set of empty pages.
             "fetched": s.get("fetched", []), "controls": s.get("controls", 0)}
            for s in screens]
    shown = sum(f.get("count") or 0 for s in rows for f in s["fetched"])
    seeded = _seeded_row_count(state["run_id"])
    if v.get("ok") and seeded and not shown:
        # Every screen opened, nothing threw, and not one record reached any of
        # them. An endpoint answering [] over a full table looks identical to a
        # healthy app until you count what the user can actually see.
        return {"working": False, "screens": rows, "findings": [{
            "severity": "blocker", "file": "backend/app/routers/",
            "story_id": "", "finding":
                f"The database ships with {seeded} seeded row(s), but across every screen the "
                "application displayed none of them. The screens open and the API answers, so "
                "the endpoints are returning empty results over a populated database — check "
                "the queries and the filters behind each screen.",
            "required_fix": "Make each screen's endpoint return the seeded rows, and show them.",
        }], "summary": f"Every screen opened, but not one of the {seeded} seeded record(s) "
                       "reached the interface."}
    if v.get("ok"):
        inert = [s["id"] for s in rows if not s["controls"]]
        return {"working": True, "findings": [], "screens": rows,
                "summary": f"All {len(screens)} screen(s) opened in a real browser against "
                           f"the running API without errors, showing {shown} record(s) between "
                           f"them. Screens with no controls at all: "
                           f"{', '.join(inert) if inert else 'none'}."}

    findings: list[dict[str, Any]] = [{
        "severity": "blocker", "file": "frontend/screens/",
        "finding": f"In the running app: {p}",
        "required_fix": "Every story needs a screen in frontend/screens/ that loads and "
                        "renders its data without errors.",
    } for p in v.get("problems", [])]
    errors = v.get("backend_errors") or []
    for s in screens:
        if s.get("ok"):
            continue
        detail = "; ".join(s.get("problems", []))[:700]
        if errors and any(re.search(r"(returned|failed with) 5\d\d", p) for p in s.get("problems", [])):
            # The traceback is what turns "500" into something a rework can fix.
            detail += "\nThe backend raised:\n" + "\n\n".join(errors)[:1200]
        for sid in re.findall(r"\bS\d+\b", s.get("story") or "") or [None]:
            finding = {
                "severity": "blocker", "file": f"frontend/screens/{s.get('id')}.js",
                "finding": f"Opened in a real browser, the '{s.get('title')}' screen failed: {detail}",
                "required_fix": "Make the screen render against the real API: call only routes "
                                "the backend serves, use only fields its responses contain, and "
                                "show errors on the page instead of throwing.",
            }
            if sid:
                finding["story_id"] = sid
            findings.append(finding)
    broken = sum(1 for r in rows if not r["ok"])
    return {"working": False, "findings": findings, "screens": rows,
            "summary": f"The browser check failed: {broken} of {len(rows)} screen(s) broken"
                       + (f"; {len(v.get('problems', []))} app-wide problem(s)"
                          if v.get("problems") else "") + "."}


def _unhealthy_stories(state: RunState) -> set[str]:
    """Stories with no real claim to being part of a working release right now."""
    rv = state.get("review") or {}
    bad = {str(s.get("story_id")) for s in (state.get("test_report") or {}).get("stories", [])
           if s.get("status") not in ("green", "dropped")}
    for f in rv.get("blocking_findings") or []:
        if f.get("story_id"):
            bad.add(str(f["story_id"]))
    return bad


def _sole_owned_files(state: RunState, story_id: str) -> list[str]:
    """This story's own router and screen files — never a file another story also claims.

    Only files exclusively about one story are safe to delete outright: a
    shared router or screen still needed by a healthy story must stay, even if
    imperfect, rather than be removed out from under it.

    A screen names its own story right in the file (`story: "S1"`), read the
    same way the platform's other checks do. A router never does — nothing in
    its contract asks it to — so ownership there comes from the build's own
    record of which story actually wrote which file, the only place it exists.
    """
    run_id = state["run_id"]
    root = repo.workspace_path(run_id)
    out: list[str] = []

    screens = root / "frontend" / "screens"
    if screens.is_dir():
        for p in screens.glob("*.js"):
            if p.name.startswith("_") or p.name == EXAMPLE_SCREEN:
                continue
            owners = set(platform_checks_mod.stories_in(p.read_text(encoding="utf-8", errors="replace")))
            if owners == {story_id}:
                out.append(f"frontend/screens/{p.name}")

    router_owners: dict[str, set[str]] = {}
    for s in (state.get("test_report") or {}).get("stories", []):
        for f in s.get("files") or []:
            if f.startswith("backend/app/routers/") and not f.endswith(EXAMPLE_ROUTER):
                router_owners.setdefault(f, set()).add(s.get("story_id"))
    out += [f for f, owners in router_owners.items() if owners == {story_id}
            and (root / f).is_file()]
    return out


async def _drop_and_redeploy(run_id: str, state: RunState, bad: set[str]) -> dict[str, Any]:
    """Remove what's broken, redeploy, and report whether what's left actually works.

    Returns {"ok": bool, "dropped": [...], "kept_but_broken": [...], "deployment": {...}}.
    A story whose files are shared with a healthy one is left in place even if
    it's part of `bad` — `kept_but_broken` names those, so release notes and the
    stakeholder both know what still needs a follow-up run.
    """
    dropped: list[str] = []
    kept_but_broken: list[str] = []
    for sid in sorted(bad):
        owned = _sole_owned_files(state, sid)
        if owned:
            for rel in owned:
                repo.remove(run_id, rel)
            dropped.append(sid)
        else:
            kept_but_broken.append(sid)
    if dropped:
        platform_checks_mod.regenerate_registry(run_id)
        repo.commit(run_id, "chore(release): drop story(ies) not ready for this release — "
                            + ", ".join(dropped))

    # fresh=True for the same reason as the automated per-round deploy: this run
    # has been redeployed onto the same volume every round it's been through, so
    # its live schema may already be stale relative to what init.sql says now —
    # exactly the bug that makes "drop what's broken" pointless if the part kept
    # is still reading from a database that predates its own schema.
    outcome = await runtime.deploy(run_id, fresh=True)
    record = {**outcome.as_dict(), "run_id": run_id}
    verification: dict[str, Any] = {"ok": True, "screens": [], "problems": []}
    if outcome.status == "running" and (state.get("scaffold") or {}).get("entrypoint") == "frontend":
        verification = await browser_check.verify(run_id)
        record["verification"] = verification
    await save_artifact(run_id, "deployment", "release", record)
    ok = outcome.status == "running" and verification.get("ok", True)
    return {"ok": ok, "dropped": dropped, "kept_but_broken": kept_but_broken, "deployment": record}


async def review(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "review")
    await emit(run_id, "Reviewing the increment against its acceptance criteria and what "
                       "the running app showed",
               agent="reviewer", stage="review")

    dep = state.get("deployment") or {}
    v = dep.get("verification") or {}
    if v and "backend_errors" not in v and browser_check.has_server_errors(v):
        # Deployed by an older check that did not collect them; the app is still up.
        v = {**v, "backend_errors": await browser_check.backend_errors(run_id)}
        state = {**state, "deployment": {**dep, "verification": v}}
    live = live_check(state)
    live_lines = "\n".join(f"- {f['finding']}" for f in live["findings"][:8])
    # What a first-time visitor actually reads. Without it the Reviewer scored an
    # "explain how LLMs work" app 77/100 when its screens were blank forms asking
    # the visitor to type the explanation themselves.
    shows = "\n".join(
        f"- {r.get('title')} ({r.get('story') or 'no story'}): "
        f"\"{str(r.get('text') or '').replace(chr(10), ' / ')[:260]}\""
        for r in live["screens"]
    )
    dod = pack().get("definition_of_done", [])
    verdict = await REVIEWER.json(
        ("DEFINITION OF DONE (this organisation's, binding):\n"
         + "\n".join(f"- {d}" for d in dod) + "\n\n" if dod else "")
        + f"SPRINT GOAL: {state['sprint'].get('sprint_goal','')}\n\n"
        f"STORIES AND CRITERIA:\n{str(state['sprint'].get('stories', []))[:3000]}\n\n"
        f"REUSE PLAN (binding):\n{str(state['architecture'].get('reuse_plan', []))[:1200]}\n\n"
        f"TEST REPORT:\n{_test_summary(state)}\n\n"
        f"LIVE CHECK (the platform deployed this increment and opened every screen in a "
        f"real browser):\n{live['summary']}\n{live_lines}\n\n"
        + (f"WHAT EACH SCREEN SHOWS to a first-time visitor on a fresh deployment (its "
           f"visible text):\n{shows}\n\n" if shows else "")
        +
        "CODE (story code only; the scaffold is platform-owned):\n" + _review_sample(run_id),
        max_tokens=5000,
    )
    score = weighted_score(verdict.get("dimensions", {}))
    threshold = pack().get("review", {}).get("ship_threshold", 70)
    # The live findings are facts, not opinions: they go in front of the model's.
    verdict["blocking_findings"] = live["findings"] + list(verdict.get("blocking_findings") or [])
    blockers = [f for f in verdict["blocking_findings"] if f.get("severity") == "blocker"]
    # A red story is a failed definition of done ("all acceptance criteria have a
    # passing test"), and that has to be arithmetic too.
    failing = [
        s.get("story_id")
        for s in (state.get("test_report") or {}).get("stories", [])
        # "dropped" is the stakeholder's own decision at the failed_story gate.
        if s.get("status") not in ("green", "dropped")
    ]
    computed = (
        "rework" if (score < threshold or blockers or failing or not live["working"])
        else verdict.get("verdict", "ship")
    )

    verdict["weighted_score"] = score
    verdict["computed_verdict"] = computed
    verdict["threshold"] = threshold
    verdict["failing_stories"] = failing
    verdict["live"] = {k: live[k] for k in ("working", "summary", "screens")}
    await save_artifact(run_id, "review", "review", verdict)
    await emit(
        run_id,
        f"Release verdict: {computed} — weighted score {score}/100 "
        f"(threshold {threshold}), {len(blockers)} blockers, {len(failing)} red stories, "
        f"app {'working' if live['working'] else 'NOT working'} in the browser",
        agent="reviewer", stage="review",
        level="error" if computed == "rework" else "info",
        data=verdict,
    )
    return {"review": verdict}


async def release(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "release")

    rv = state.get("review") or {}
    dep = state.get("deployment") or {}
    url = dep.get("url", "") if dep.get("status") == "running" else ""
    live = rv.get("live") or {}
    working = bool(live.get("working", False))
    red = rv.get("failing_stories") or []
    policy = pack().get("review", {})
    # An app that does not work is not a release, whatever its score says: the
    # stakeholder can send it back or hold it, but not ship it.
    # A clean review is part of "done in the right way": an app that works but
    # misses what its stories promised is not a release either.
    verdict_ok = (rv.get("computed_verdict") != "rework"
                  or not policy.get("release_requires_ship_verdict", True))
    releasable = ((working and not red)
                  or not policy.get("release_requires_working_app", True)) and verdict_ok
    rebuilds = int(state.get("human_rebuilds", 0))
    can_rebuild = rebuilds < int(policy.get("max_human_rebuilds", 2))

    # A guaranteed way out that is neither "release it broken" nor "hold with
    # nothing to show": drop whatever is not ready and ship the rest, so a run
    # always has a base to hand off rather than ending as pure iteration.
    all_stories = {e["id"] for e in state["sprint"].get("stories", [])}
    unhealthy = _unhealthy_stories(state) if not releasable else set()
    can_ship_partial = bool(unhealthy) and unhealthy < all_stories

    if url and working:
        live_text = f" It is running at {url} and every screen opened cleanly — try it before you decide."
    elif url:
        live_text = f" It is running at {url}, but {live.get('summary', 'the browser check failed')}"
    elif dep.get("status") == "failed":
        live_text = " The application could not be started; the Deploy stage shows why."
    else:
        live_text = ""
    if releasable:
        ask = " Release it?"
    else:
        reasons = []
        if not working:
            reasons.append("it is not proven working in a browser")
        if red:
            reasons.append(f"{len(red)} story(ies) still failing")
        if not verdict_ok:
            reasons.append("the Reviewer found blocking problems")
        ask = " It cannot be released yet: " + "; ".join(reasons) + "."

    options = []
    if releasable:
        options.append({"value": "approve", "label": "Release this increment"})
    if can_ship_partial:
        options.append({"value": "ship_partial",
                        "label": f"Release a base app now, dropping {len(unhealthy)} "
                                 "story(ies) not ready — continue them in a follow-up run"})
    if can_rebuild:
        options.append({"value": "rebuild", "label": "Send it back for another build round"})
    options.append({"value": "hold", "label": "Hold — do not release"})

    response = await raise_gate(
        run_id=run_id, kind="approve_release", stage="release",
        question=f"The Reviewer scored this {rv.get('weighted_score')}/100 and recommends "
                 f"'{rv.get('computed_verdict')}'.{live_text}{ask}",
        artifact={**rv, "deployment": dep, "releasable": releasable,
                 "ship_partial_would_drop": sorted(unhealthy) if can_ship_partial else []},
        options=options,
        default={"decision": "hold", "notes": "auto-held: release requires a human"},
    )
    decision = response.get("decision")
    notes_in = str(response.get("notes") or "").strip()

    if decision == "ship_partial" and can_ship_partial:
        result = await _drop_and_redeploy(run_id, state, unhealthy)
        dep = result["deployment"]
        url = dep.get("url", "") if dep.get("status") == "running" else ""
        if not result["ok"]:
            # Dropping made things worse or didn't fully fix it — refuse to ship
            # broken, exactly as a normal release would, rather than pretend.
            await set_stage(run_id, "release", status="held")
            await emit(run_id, "Tried releasing a base app after dropping "
                               f"{', '.join(result['dropped']) or 'nothing'}, but it still is not "
                               "proven working — held instead. Try 'Send it back' or investigate directly.",
                       agent="governance", stage="release", level="warn", data=result)
            await tracker.on_release(run_id, state, {"status": "held", "notes": notes_in})
            return {"release": {"status": "held", "notes": notes_in}, "deployment": dep}

        for sid in result["dropped"]:
            for s in state["test_report"].get("stories", []):
                if s.get("story_id") == sid:
                    s["status"] = "dropped"
                    s["reason"] = "Dropped so a working base app could ship; left for a follow-up run."
        follow_up = sorted(set(result["dropped"]) | set(result["kept_but_broken"]))
        notes = await RELEASE.json(
            f"VISION:\n{state['vision']}\n\nSPRINT:\n{state['sprint']}\n\n"
            f"This is a PARTIAL release: {', '.join(follow_up)} were dropped or are still broken "
            "and are NOT included. Say so plainly and list them as follow-up work.\n\n"
            f"TEST REPORT:\n{_test_summary(state)}\n\nWORKSPACE FILES:\n{repo.tree(run_id)[:80]}"
        )
        notes["url"] = url
        notes["run_command"] = url
        notes["known_limitations"] = list(notes.get("known_limitations") or []) + [
            f"{sid} is not in this release" for sid in follow_up
        ]
        notes["release_notes_markdown"] = (
            f"**Open it:** {url}\n\n**Not included in this release:** {', '.join(follow_up)} "
            "(continue these in a follow-up run)\n\n" + (notes.get("release_notes_markdown") or "")
        )
        repo.write_files(run_id, {"RELEASE_NOTES.md": notes["release_notes_markdown"]})
        sha = repo.commit(run_id, f"chore(release): {notes.get('version', '0.1.0')} (partial)")
        notes["commit"] = sha
        notes["status"] = "released"
        notes["partial"] = True
        await save_artifact(run_id, "release", "release", notes)
        await set_stage(run_id, "release", status="released",
                        summary={"version": notes.get("version"), "score": rv.get("weighted_score"),
                                 "url": url, "partial": True})
        await emit(run_id, f"Released {notes.get('version')} as a base app at {url} — "
                           f"{', '.join(follow_up)} left for a follow-up run",
                   agent="release", stage="release", data=notes)
        await tracker.on_release(run_id, state, notes)
        await gitremote.on_release(run_id, state, notes)
        return {"release": notes, "deployment": dep, "test_report": state["test_report"]}

    if decision == "rebuild" and can_rebuild:
        await emit(run_id, "Sent back for another build round"
                           + (f": {notes_in}" if notes_in else ""),
                   agent="governance", stage="release", level="warn", data=response)
        findings = list(rv.get("blocking_findings") or [])
        if notes_in:
            findings.insert(0, {"severity": "blocker", "file": "(stakeholder)",
                                "finding": f"The stakeholder sent this back: {notes_in}",
                                "required_fix": notes_in})
        await tracker.on_release(run_id, state, {"status": "rebuild", "notes": notes_in})
        return {"release": {"status": "rebuild", "notes": notes_in},
                "human_rebuilds": rebuilds + 1,
                "review": {**rv, "blocking_findings": findings}}

    if decision != "approve" or not releasable:
        await set_stage(run_id, "release", status="held")
        await emit(run_id, "Release held" + ("" if releasable else
                                             " — the app is not proven working"),
                   agent="governance", stage="release", level="warn", data=response)
        await tracker.on_release(run_id, state, {"status": "held", "notes": notes_in})
        return {"release": {"status": "held", "notes": notes_in}}

    notes = await RELEASE.json(
        f"VISION:\n{state['vision']}\n\nSPRINT:\n{state['sprint']}\n\n"
        f"TEST REPORT:\n{_test_summary(state)}\n\n"
        f"REVIEW:\nscore {rv.get('weighted_score')}, verdict {rv.get('computed_verdict')}, "
        f"live check: {live.get('summary', '')}\n\n"
        f"WORKSPACE FILES:\n{repo.tree(run_id)[:80]}"
    )
    if url:
        # The Release Manager writes prose; the address is a fact, so it is set here
        # rather than trusted to the model.
        notes["url"] = url
        notes["run_command"] = url
        notes["release_notes_markdown"] = (
            f"**Open it:** {url}\n\n" + (notes.get("release_notes_markdown") or "")
        )
    repo.write_files(run_id, {"RELEASE_NOTES.md": notes.get("release_notes_markdown", "")})
    sha = repo.commit(run_id, f"chore(release): {notes.get('version', '0.1.0')}")
    notes["commit"] = sha
    notes["status"] = "released"

    await save_artifact(run_id, "release", "release", notes)
    await set_stage(run_id, "release", status="released",
                    summary={"version": notes.get("version"),
                             "score": rv.get("weighted_score"),
                             "url": url})
    await emit(run_id, f"Released {notes.get('version')} — "
                       + (f"open it at {url}" if url
                          else f"run it with: {notes.get('run_command','')}"),
               agent="release", stage="release", data=notes)
    await tracker.on_release(run_id, state, notes)
    await gitremote.on_release(run_id, state, notes)
    return {"release": notes}


async def harvest(state: RunState) -> RunState:
    """Feed what we learned back into the graph so the next run starts smarter."""
    run_id = state["run_id"]
    project = state["vision"].get("product_name") or state.get("title", run_id)

    for story in state["backlog"].get("stories", []):
        await kg().run(
            """
            MERGE (s:Story {id: $sid})
            SET s.title = $title, s.narrative = $narrative, s.run_id = $run_id
            WITH s MERGE (p:Project {name: $project}) MERGE (p)-[:DELIVERS]->(s)
            """,
            sid=f"{run_id}:{story.get('id')}", title=story.get("title", ""),
            narrative=story.get("narrative", ""), run_id=run_id, project=project,
        )

    for cap in state["architecture"].get("components", []):
        await kg().run(
            """
            MERGE (c:Capability {name: $name})
            SET c.description = $desc
            WITH c MERGE (p:Project {name: $project}) MERGE (p)-[:PROVIDES]->(c)
            """,
            name=cap.get("name", "unnamed"), desc=cap.get("responsibility", ""),
            project=project,
        )
        if cap.get("technology"):
            await kg().run(
                """
                MERGE (t:Technology {name: $tech})
                WITH t MERGE (p:Project {name: $project}) MERGE (p)-[:USES]->(t)
                """,
                tech=cap["technology"], project=project,
            )

    # Outcomes: what shipped, what did not, and what it scored.
    report = state.get("test_report") or {}
    rv = state.get("review") or {}
    rel = state.get("release") or {}
    await kg().record_outcome(run_id, project, {
        "score": rv.get("weighted_score"), "verdict": rv.get("computed_verdict"),
        "released": rel.get("status") == "released",
        "green": report.get("green"), "total": report.get("total"),
    })
    stories_by_id = {s.get("id"): s for s in state["backlog"].get("stories", [])}
    story_items = []
    for r in report.get("stories", []):
        sid = str(r.get("story_id"))
        await kg().record_story_outcome(run_id, sid, r.get("status", ""), r.get("repair_attempts", 0))
        story = stories_by_id.get(sid)
        if story:
            outcome = f"{r.get('status')} after {r.get('repair_attempts', 0)} repair(s)"
            story_items.append(vectors.story_item(run_id, project, story, outcome))
    await vectors.upsert("stories", story_items)
    await vectors.upsert("decisions", [vectors.decision_item(run_id, project, d)
                                       for d in state["architecture"].get("decisions", [])])

    # Lessons: one sentence per story that needed repairs or stayed red, so the
    # next run's Developer is told before it makes the same mistake.
    lessons = await remember(run_id, "harvest:lessons", lambda: _lessons(run_id, state, stories_by_id))
    for item in lessons:
        await kg().record_lesson(run_id, item["story_id"], item["lesson"], item["applies_to"], project)
    await vectors.upsert("lessons", [vectors.lesson_item(run_id, l["story_id"], l["lesson"], l["applies_to"])
                                     for l in lessons])

    await emit(run_id, "Knowledge graph updated: this run is now reusable context"
                       + (f"; {len(lessons)} lesson(s) recorded for future runs" if lessons else ""),
               agent="governance", stage="harvest",
               data={"project": project, "lessons": lessons})
    await set_stage(run_id, "done", status="complete")
    return {}


_LESSON_SYSTEM = """You distil one actionable lesson from a story that failed or needed repairs
on an autonomous engineering platform. The reader is the Developer agent on a future run,
building a similar story. Write one sentence in the imperative that would have prevented the
failure — concrete, about the code or the data, never about process or "be careful".
Examples: "Seed every table a screen reads in db/init.sql, or the screen shows an empty
state." "Mount a router with a prefix that matches the path its screen calls."
If the failure was a platform or environment problem and no lesson applies, return an empty
lesson."""


async def _lessons(run_id: str, state: RunState, stories: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rv = state.get("review") or {}
    findings = rv.get("blocking_findings") or []
    for r in (state.get("test_report") or {}).get("stories", []):
        sid = str(r.get("story_id"))
        troubled = r.get("status") not in ("green",) or int(r.get("repair_attempts") or 0) > 0
        if not troubled:
            continue
        story = stories.get(sid) or {}
        mine = [f.get("finding") for f in findings if str(f.get("story_id")) == sid]
        try:
            reply = await complete_json(
                role="fast", system=_LESSON_SYSTEM, schema=schemas.LESSON, max_tokens=400,
                user=(f"STORY {sid}: {story.get('title', '')}\n{story.get('narrative', '')}\n"
                      f"OUTCOME: {r.get('status')} after {r.get('repair_attempts', 0)} repair(s)\n"
                      f"REASON: {r.get('reason', '')}\n"
                      f"REVIEWER FINDINGS: {mine[:4]}\n"
                      f"LAST TEST OUTPUT:\n{str(r.get('test_output') or '')[-2500:]}"),
            )
        except Exception:  # noqa: BLE001 — a lesson is a bonus, never a blocker
            continue
        lesson = str((reply or {}).get("lesson") or "").strip()
        if len(lesson) > 20:
            out.append({"story_id": sid, "lesson": lesson[:400],
                        "applies_to": str((reply or {}).get("applies_to") or story.get("title") or "")[:200]})
    return out
