"""Mirror a run into Jira as it happens: the plan when it is approved, progress as it is made.

    run             -> Initiative   (the product: vision, scope, success metrics)
    backlog epic    -> Epic         (parent: the initiative)
    backlog story   -> Story        (parent: its epic; acceptance criteria, estimate)
    sprint          -> Sprint       (on the project's scrum board, started)
    story building  -> In Progress
    story green     -> Done, with what was verified
    story red       -> stays In Progress, labelled poiesis-red, with the failure
    release         -> comment and link on the initiative; sprint closed

Two rules govern every call here.

It never stops a run. Jira being down, a revoked token or a project that refuses
a field costs a warning in the run's log, nothing more: the organisation's view of
the work is a mirror of it, not a dependency of it.

It never duplicates. LangGraph replays a whole node each time a gate is answered,
so every hook below runs several times per run. Each issue is created under a
remember() key, and — for the crash between Jira answering and the key being
stored — each carries a label unique to the run and the item, which is searched
before anything is created.

    python -m app.integrations.tracker backfill <run_id>   # mirror an existing run
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Awaitable, Callable

import httpx

from ..config import settings
from ..db import Artifact, Event, NodeCache, session
from ..events import emit
from ..graph.memo import remember
from .jira import Jira, JiraError, adf, bullets, configured, heading, link, para

# Tests swap in a fake Jira here; production leaves it None and talks to the site.
_transport: httpx.AsyncBaseTransport | None = None

_ORDER = {"new": 0, "indeterminate": 1, "done": 2}


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = transport


def _labels(run_id: str, ref: str) -> list[str]:
    return ["poiesis", f"poiesis-run-{run_id}", f"poiesis-{run_id}-{ref.lower()}"]


def _line(item: Any) -> str:
    """One readable line from a vision entry, which may be a string or a small dict."""
    if not isinstance(item, dict):
        return str(item)
    parts = [str(v) for v in item.values() if v not in (None, "", [], {})]
    return " — ".join(parts)


def _list(value: Any) -> list[str]:
    return [_line(v) for v in value] if isinstance(value, list) else ([_line(value)] if value else [])


async def _safely(run_id: str, stage: str, what: str,
                  work: Callable[[Jira], Awaitable[Any]]) -> Any:
    if not configured():
        return None
    j = Jira(transport=_transport)
    try:
        return await work(j)
    except Exception as exc:  # noqa: BLE001 — a mirror must never take the run down
        await emit(run_id, f"Jira sync skipped ({what}): {exc}", agent="tracker",
                   stage=stage, level="warn")
        return None
    finally:
        await j.close()


async def _ensure(run_id: str, j: Jira, ref: str, create: Callable[[list[str]], Awaitable[dict]]) -> dict:
    """The Jira issue for `ref`, created exactly once however often this runs."""
    async def produce() -> dict:
        labels = _labels(run_id, ref)
        existing = await j.find_by_label(labels[-1])
        if existing:
            return {"key": existing["key"], "url": j.browse(existing["key"]), "found": True}
        issue = await create(labels)
        return {"key": issue["key"], "url": j.browse(issue["key"]), "dropped": issue.get("_dropped", [])}
    return await remember(run_id, f"jira:{ref.lower()}", produce)


def _known(run_id: str, ref: str) -> dict | None:
    with session() as s:
        row = s.get(NodeCache, (run_id, f"jira:{ref.lower()}"))
        return None if row is None else (row.value or {}).get("__value__")


async def _forward(j: Jira, key: str, category: str) -> None:
    """Move an issue towards `category`, never backwards: a replay must not reopen Done."""
    if _ORDER[await j.status_category(key)] < _ORDER[category]:
        await j.move_to(key, category)


# --- the plan ---------------------------------------------------------------------

def _initiative_body(run_id: str, vision: dict[str, Any]) -> dict[str, Any]:
    return adf(
        para(vision.get("problem_statement")),
        heading("Value"), para(vision.get("value_proposition")),
        heading("Who it is for"), bullets(_list(vision.get("target_users"))),
        heading("Success metrics"), bullets(_list(vision.get("success_metrics"))),
        heading("In scope"), bullets(_list(vision.get("in_scope"))),
        heading("Out of scope"), bullets(_list(vision.get("explicitly_out_of_scope"))),
        heading("Risks"), bullets(_list(vision.get("key_risks"))),
        para(f"Planned and built by Poiesis, run {run_id}."),
    )


def _story_body(run_id: str, story: dict[str, Any]) -> dict[str, Any]:
    details = [f"Poiesis story {story.get('id')}"]
    for label, key in (("Value", "value"), ("Estimate", "estimate"), ("Risk", "risk")):
        if story.get(key) not in (None, ""):
            details.append(f"{label}: {story[key]}")
    if story.get("depends_on"):
        details.append("Depends on: " + ", ".join(map(str, story["depends_on"])))
    return adf(
        para(story.get("narrative")),
        heading("Acceptance criteria"), bullets(story.get("acceptance_criteria") or []),
        heading("Details"), bullets(details),
        para(("Evidence: " + ", ".join(story["evidence_ids"])) if story.get("evidence_ids") else ""),
        para(f"Planned by Poiesis, run {run_id}."),
    )


async def on_backlog(run_id: str, state: dict[str, Any], backlog: dict[str, Any]) -> None:
    """The approved backlog becomes an initiative, its epics and its stories."""
    async def work(j: Jira) -> None:
        types = await j.issue_types()
        if not types["story"]:
            raise JiraError(0, "GET", "project", "the project has no Story or Task issue type")
        vision = state.get("vision") or {}
        product = vision.get("product_name") or state.get("title") or "Poiesis run"
        notes: list[str] = []

        initiative = None
        if types["initiative"]:
            initiative = await _ensure(run_id, j, "initiative", lambda labels: _create(
                j, types["initiative"]["id"], product, _initiative_body(run_id, vision), labels))
        else:
            notes.append(f"no '{settings().jira_initiative_type}' issue type, so epics have no parent")

        epics: dict[str, str] = {}
        for epic in backlog.get("epics", []):
            if not types["epic"]:
                break
            made = await _ensure(run_id, j, epic["id"], lambda labels, e=epic: _create(
                j, types["epic"]["id"], e.get("title") or e["id"],
                adf(para(e.get("outcome")), para(f"Planned by Poiesis, run {run_id}.")),
                labels, parent=initiative["key"] if initiative else None))
            epics[epic["id"]] = made["key"]
            if "parent" in made.get("dropped", []):
                notes.append("the project's hierarchy refused initiative > epic, so epics have no parent")

        points = await j.story_points_field()
        stories = backlog.get("stories", [])
        for story in stories:
            estimate = story.get("estimate")
            extra = {points: estimate} if points and isinstance(estimate, (int, float)) else None
            await _ensure(run_id, j, story["id"], lambda labels, s=story, x=extra: _create(
                j, types["story"]["id"], s.get("title") or s["id"], _story_body(run_id, s),
                labels, parent=epics.get(s.get("epic_id", "")), extra=x))

        head = initiative or (_known(run_id, stories[0]["id"]) if stories else None)
        where = f" — {head['url']}" if head else ""
        await emit(run_id, f"Jira: {'initiative ' + initiative['key'] + ', ' if initiative else ''}"
                           f"{len(epics)} epic(s) and {len(stories)} stor(ies) in "
                           f"{j.project_key}{where}"
                           + (f" ({'; '.join(dict.fromkeys(notes))})" if notes else ""),
                   agent="tracker", stage="backlog",
                   data={"jira": {"initiative": initiative, "epics": epics}})
    await _safely(run_id, "backlog", "backlog", work)


async def _create(j: Jira, type_id: str, summary: str, body: dict[str, Any], labels: list[str],
                  parent: str | None = None, extra: dict[str, Any] | None = None) -> dict:
    issue, dropped = await j.create_issue(type_id=type_id, summary=summary, description=body,
                                          labels=labels, parent=parent, extra=extra)
    return {**issue, "_dropped": dropped}


async def on_sprint(run_id: str, state: dict[str, Any], sprint: dict[str, Any]) -> None:
    """The cut sprint becomes a started Jira sprint holding exactly its stories."""
    async def work(j: Jira) -> None:
        board = await j.scrum_board()
        if not board:
            await emit(run_id, f"Jira: {j.project_key} has no scrum board, so the sprint was "
                               "not created; its stories are in the backlog", agent="tracker",
                       stage="sprint", level="warn")
            return
        product = ((state.get("vision") or {}).get("product_name") or state.get("title") or "Poiesis")
        name = f"{product[:14].strip()} S1 {run_id[:6]}"
        keys = [m["key"] for m in (_known(run_id, e["id"]) for e in sprint.get("stories", [])) if m]

        async def produce() -> dict:
            found = await j.find_sprint(board["id"], name)
            made = found or await j.create_sprint(board["id"], name, sprint.get("sprint_goal", ""))
            await j.add_to_sprint(made["id"], keys)
            note = ""
            if made.get("state") == "future":
                try:
                    await j.start_sprint(made["id"], _sprint_days())
                    made["state"] = "active"
                except JiraError as exc:
                    # Most boards allow one active sprint; leaving it planned is fine.
                    note = f"left planned, not started: {exc}"
            return {"id": made["id"], "name": name, "state": made.get("state"), "note": note,
                    "board": board["id"], "stories": keys}
        made = await remember(run_id, "jira:sprint:1", produce)
        await emit(run_id, f"Jira: sprint '{name}' on board {board['id']} with {len(keys)} "
                           f"stor(ies), {made.get('state')}"
                           + (f" ({made['note']})" if made.get("note") else ""),
                   agent="tracker", stage="sprint", data={"jira": {"sprint": made}})
    await _safely(run_id, "sprint", "sprint", work)


def _sprint_days() -> int:
    return settings().jira_sprint_days


# --- progress ---------------------------------------------------------------------

async def on_story_started(run_id: str, story_id: str) -> None:
    async def work(j: Jira) -> None:
        known = _known(run_id, story_id)
        if known:
            await _forward(j, known["key"], "indeterminate")
    await _safely(run_id, "build", f"{story_id} started", work)


async def on_story_result(run_id: str, result: dict[str, Any], rnd: int) -> None:
    """Green moves to Done; red and dropped are labelled and explained, never closed."""
    sid, status = result.get("story_id", ""), result.get("status", "")

    async def work(j: Jira) -> None:
        known = _known(run_id, sid)
        if not known:
            return
        key = known["key"]
        if status == "green":
            await _forward(j, key, "done")
            body = adf(para(f"Built and verified by Poiesis in round {rnd + 1}: its tests pass "
                            f"and its screen was checked, after {result.get('repair_attempts', 0)} "
                            "repair attempt(s)."),
                       heading("Files"), bullets(result.get("files") or []))
        else:
            await j.add_labels(key, [f"poiesis-{status}"])
            why = result.get("reason") or "It still fails its checks after the repair budget."
            tail = str(result.get("test_output") or "")[-1500:]
            body = adf(para(f"Poiesis could not finish this story in round {rnd + 1} ({status}). {why}"),
                       {"type": "codeBlock", "content": [{"type": "text", "text": tail}]} if tail else None)

        async def post() -> bool:
            await j.comment(key, body)
            return True
        await remember(run_id, f"jira:note:{sid.lower()}:r{rnd}:{status}", post)
    await _safely(run_id, "build", f"{sid} {status}", work)


async def on_release(run_id: str, state: dict[str, Any], release: dict[str, Any]) -> None:
    status = release.get("status", "")
    rounds = state.get("human_rebuilds", 0)

    async def work(j: Jira) -> None:
        head = _known(run_id, "initiative")
        url = release.get("url") or (state.get("deployment") or {}).get("url")
        if head:
            if status == "released" and url and url.startswith("http"):
                await j.remote_link(head["key"], url, f"{release.get('version', 'Release')} — running app")
            lines = {
                "released": f"Released {release.get('version', '')}"
                            + (" as a partial base app" if release.get("partial") else "") + ".",
                "held": "The release was held at the release gate.",
                "rebuild": "Sent back from the release gate for another build round.",
            }.get(status, f"Release status: {status}.")
            body = adf(para(lines), link("Open the application", url) if url else None,
                       para(release.get("notes") if isinstance(release.get("notes"), str) else ""))

            async def post() -> bool:
                await j.comment(head["key"], body)
                return True
            await remember(run_id, f"jira:note:release:{rounds}:{status}", post)

        sprint = _known(run_id, "sprint:1")
        if status == "released" and sprint and sprint.get("state") == "active":
            async def close() -> bool:
                await j.close_sprint(sprint["id"])
                return True
            await remember(run_id, "jira:sprint:1:closed", close)
        await emit(run_id, f"Jira: release {status} recorded"
                           + (f" on {head['key']}" if head else ""),
                   agent="tracker", stage="release")
    await _safely(run_id, "release", f"release {status}", work)


# --- reading it back, and mirroring an existing run -------------------------------

def mapping(run_id: str) -> dict[str, Any]:
    """Everything this run has in Jira, for the API and the UI."""
    with session() as s:
        rows = s.query(NodeCache).filter(NodeCache.run_id == run_id,
                                         NodeCache.key.like("jira:%")).all()
    out: dict[str, Any] = {"enabled": configured(), "initiative": None, "epics": {},
                           "stories": {}, "sprint": None}
    for row in rows:
        value = (row.value or {}).get("__value__")
        ref = row.key.split(":", 1)[1]
        if ref == "initiative":
            out["initiative"] = value
        elif ref == "sprint:1":
            out["sprint"] = value
        elif ref.startswith("e") and ref[1:].isdigit():
            out["epics"][ref.upper()] = value
        elif ref.startswith("s") and ref[1:].isdigit():
            out["stories"][ref.upper()] = value
    return out


def _latest(run_id: str, kind: str) -> dict[str, Any] | None:
    with session() as s:
        row = (s.query(Artifact).filter(Artifact.run_id == run_id, Artifact.kind == kind)
               .order_by(Artifact.version.desc(), Artifact.created_at.desc()).first())
        return None if row is None else row.body


def _outcomes_from_events(run_id: str) -> list[dict[str, Any]]:
    """Story outcomes for a run that never wrote a test report (it stopped mid-build)."""
    import re
    latest: dict[str, dict[str, Any]] = {}
    with session() as s:
        for e in s.query(Event).filter(Event.run_id == run_id, Event.stage == "build").order_by(Event.at):
            m = re.match(r"(S\d+) is (green|red) after (\d+) repair", e.message)
            if m:
                latest[m.group(1)] = {"story_id": m.group(1), "status": m.group(2),
                                      "repair_attempts": int(m.group(3)),
                                      "test_output": (e.data or {}).get("output", "")}
    return list(latest.values())


async def backfill(run_id: str) -> int:
    """Mirror a run that already happened. Makes no model calls; safe to repeat."""
    if not configured():
        print("Jira is not configured - see `python -m app.integrations.jira check`.")
        return 1
    vision, backlog, sprint = (_latest(run_id, k) for k in ("vision", "backlog", "sprint"))
    if not backlog:
        print(f"Run {run_id} has no approved backlog to mirror.")
        return 1
    state = {"run_id": run_id, "vision": vision or {}, "title": (vision or {}).get("product_name", "")}
    await on_backlog(run_id, state, backlog)
    if sprint:
        await on_sprint(run_id, state, sprint)
    report = _latest(run_id, "test_report")
    outcomes = (report or {}).get("stories") or _outcomes_from_events(run_id)
    for result in outcomes:
        await on_story_started(run_id, result["story_id"])
        await on_story_result(run_id, result, 0)
    release = _latest(run_id, "release")
    if release:
        await on_release(run_id, state, release)
    m = mapping(run_id)
    print(f"initiative: {(m['initiative'] or {}).get('url', '(none)')}")
    print(f"epics: {len(m['epics'])}   stories: {len(m['stories'])}   "
          f"sprint: {(m['sprint'] or {}).get('name', '(none)')}")
    for sid, v in sorted(m["stories"].items(), key=lambda kv: int(kv[0][1:])):
        print(f"  {sid:4s} {v['key']:10s} {v['url']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "backfill":
        raise SystemExit(asyncio.run(backfill(sys.argv[2])))
    print(__doc__)
