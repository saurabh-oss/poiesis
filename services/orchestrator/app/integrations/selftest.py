"""Self-test for the Jira mirror. No Jira site, no network, no model calls.

    docker compose exec orchestrator python -m app.integrations.selftest

Each scenario runs against a FakeJira configured like a different real project,
under a throwaway run whose rows are deleted at the end, pass or fail.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from ..config import settings
from ..db import Event, NodeCache, Run, session
from . import tracker
from .fake_jira import FakeJira

failures: list[str] = []

VISION = {
    "product_name": "Helix Triage",
    "problem_statement": "Tickets land in one inbox and urgent ones sit unread.",
    "value_proposition": "Every ticket is seen and routed the moment it arrives.",
    "target_users": [{"persona": "Triage manager", "current_pain": "Reads every ticket by hand"}],
    "success_metrics": [{"metric": "SLA breach rate", "baseline": "1 in 9", "target": "1 in 50"}],
    "in_scope": ["Triage queue", "Duplicate detection"],
    "explicitly_out_of_scope": ["Authentication"],
    "key_risks": [{"risk": "Word overlap misses paraphrases", "mitigation": "Human review"}],
}
BACKLOG = {
    "epics": [{"id": "E1", "title": "Automated triage queue", "outcome": "Nothing sits unread."},
              {"id": "E2", "title": "Duplicate detection", "outcome": "Each incident is worked once."}],
    "stories": [
        {"id": "S1", "epic_id": "E1", "title": "View triage queue with SLA standing",
         "narrative": "As a triage manager I want to see what needs attention.",
         "acceptance_criteria": ["Given tickets, when I open the queue, then breaching ones stand out.",
                                 "Given a filter, when I apply it, then the list narrows."],
         "value": 8, "estimate": 5, "risk": "low", "evidence_ids": ["ev1"]},
        {"id": "S2", "epic_id": "E1", "title": "Auto-triage an untriaged ticket",
         "narrative": "As a triage manager I want the rules applied for me.",
         "acceptance_criteria": ["Given a Sev-1, when triaged, then it is Critical.",
                                 "Given payment wording, when triaged, then it goes to Payments."],
         "value": 13, "estimate": 8, "depends_on": ["S1"]},
        {"id": "S3", "epic_id": "E2", "title": "Confirm a duplicate group and merge",
         "narrative": "As a reviewer I want to merge a confirmed group.",
         "acceptance_criteria": ["Given a group, when confirmed, then the rest are Merged.",
                                 "Given a merged ticket, then it leaves the queue."],
         "value": 13, "estimate": 8},
    ],
}
SPRINT = {"sprint_goal": "See urgent work and triage it.", "stories": [{"id": "S1"}, {"id": "S2"}]}


def expect(name: str, ok: bool, detail: str = "") -> None:
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok or not detail else f"\n       {detail}"))
    if not ok:
        failures.append(name)


def _text_of(doc: dict[str, Any]) -> str:
    return json.dumps(doc)


def _new_run(title: str) -> str:
    with session() as s:
        run = Run(title=title)
        s.add(run)
        s.commit()
        return run.id


def _drop_run(run_id: str) -> None:
    with session() as s:
        row = s.get(Run, run_id)
        if row is not None:
            s.delete(row)
            s.commit()


def _warnings(run_id: str) -> list[str]:
    with session() as s:
        return [e.message for e in s.query(Event).filter(Event.run_id == run_id, Event.agent == "tracker")]


def _configure(on: bool) -> dict[str, Any]:
    s = settings()
    saved = {k: getattr(s, k) for k in ("jira_base_url", "jira_email", "jira_api_token",
                                        "jira_project_key", "jira_board_id")}
    values = {"jira_base_url": "https://fake.atlassian.net", "jira_email": "bot@example.com",
              "jira_api_token": "t", "jira_project_key": "HEL", "jira_board_id": 0} if on else \
             {"jira_base_url": "", "jira_email": "", "jira_api_token": "", "jira_project_key": ""}
    for k, v in values.items():
        setattr(s, k, v)
    return saved


async def scenario(title: str, fake: FakeJira, body) -> None:
    print(f"\n===== {title} =====")
    rid = _new_run(f"jira selftest: {title}")
    tracker.use_transport(fake.transport())
    try:
        await body(rid, fake)
    finally:
        tracker.use_transport(None)
        _drop_run(rid)


async def full_hierarchy(rid: str, fake: FakeJira) -> None:
    state = {"run_id": rid, "vision": VISION, "title": "Helix Triage"}
    await tracker.on_backlog(rid, state, BACKLOG)
    inits, epics, stories = fake.of_type("Initiative"), fake.of_type("Epic"), fake.of_type("Story")
    expect("one initiative for the run", len(inits) == 1, str(len(inits)))
    expect("an epic per backlog epic, each under the initiative",
           len(epics) == 2 and all(e["parent"] == inits[0]["key"] for e in epics))
    by_title = {s["summary"]: s for s in stories}
    s1 = by_title.get("View triage queue with SLA standing", {})
    e1 = next(e for e in epics if e["summary"] == "Automated triage queue")
    expect("a story per backlog story, each under its epic",
           len(stories) == 3 and s1.get("parent") == e1["key"])
    expect("the initiative carries the vision",
           "SLA breach rate" in _text_of(inits[0]["description"])
           and "Out of scope" in _text_of(inits[0]["description"]))
    expect("a story carries its acceptance criteria and estimate",
           "breaching ones stand out" in _text_of(s1.get("description", {})) and s1.get("points") == 5)

    await tracker.on_backlog(rid, state, BACKLOG)
    await tracker.on_backlog(rid, state, BACKLOG)
    expect("replaying the approved backlog creates nothing new", len(fake.issues) == 6, str(len(fake.issues)))

    with session() as s:  # the crash between Jira answering and the key being stored
        s.query(NodeCache).filter(NodeCache.run_id == rid, NodeCache.key == "jira:s1").delete()
        s.commit()
    await tracker.on_backlog(rid, state, BACKLOG)
    expect("a lost memo is recovered from the item's label, not duplicated", len(fake.issues) == 6)

    await tracker.on_sprint(rid, state, SPRINT)
    await tracker.on_sprint(rid, state, SPRINT)
    sprints = list(fake.sprints.values())
    s1_key, s2_key = tracker._known(rid, "S1")["key"], tracker._known(rid, "S2")["key"]
    expect("one started sprint holding exactly the sprint's stories",
           len(sprints) == 1 and sprints[0]["state"] == "active"
           and sorted(sprints[0]["issues"]) == sorted([s1_key, s2_key]), str(sprints))
    expect("the sprint name fits Jira's 30-character limit", len(sprints[0]["name"]) <= 30)

    await tracker.on_story_started(rid, "S1")
    expect("a story being built is In Progress", fake.issues[s1_key]["status"][2] == "indeterminate")
    green = {"story_id": "S1", "status": "green", "repair_attempts": 1, "files": ["backend/app/routers/queue.py"]}
    await tracker.on_story_result(rid, green, 0)
    await tracker.on_story_result(rid, green, 0)
    expect("a green story is Done", fake.issues[s1_key]["status"][2] == "done")
    expect("its verification note is posted once, however often the node replays",
           len(fake.comments.get(s1_key, [])) == 1)
    await tracker.on_story_started(rid, "S1")
    expect("a replayed 'started' never reopens a Done story", fake.issues[s1_key]["status"][2] == "done")

    red = {"story_id": "S2", "status": "red", "repair_attempts": 4, "test_output": "E   assert 404 == 200"}
    await tracker.on_story_started(rid, "S2")
    await tracker.on_story_result(rid, red, 0)
    expect("a red story stays open, labelled, with the failure attached",
           fake.issues[s2_key]["status"][2] == "indeterminate"
           and "poiesis-red" in fake.issues[s2_key]["labels"]
           and "assert 404 == 200" in _text_of(fake.comments[s2_key][0]))

    release = {"status": "released", "version": "0.1.0", "url": "http://localhost:8102"}
    await tracker.on_release(rid, {**state, "human_rebuilds": 0}, release)
    await tracker.on_release(rid, {**state, "human_rebuilds": 0}, release)
    head = inits[0]["key"]
    expect("the release links the running app from the initiative",
           "http://localhost:8102" in fake.links.get(head, {}))
    expect("the release is noted once on the initiative", len(fake.comments.get(head, [])) == 1)
    expect("releasing closes the sprint", sprints[0]["state"] == "closed")

    m = tracker.mapping(rid)
    expect("the mapping reads back every item",
           m["initiative"]["key"] == head and len(m["epics"]) == 2 and len(m["stories"]) == 3
           and m["sprint"]["state"] == "active")  # recorded as it was when created


async def no_initiative(rid: str, fake: FakeJira) -> None:
    await tracker.on_backlog(rid, {"run_id": rid, "vision": VISION}, BACKLOG)
    epics = fake.of_type("Epic")
    expect("without an Initiative type, epics are created with no parent",
           len(epics) == 2 and all(e["parent"] is None for e in epics) and len(fake.of_type("Story")) == 3)
    expect("and the run's log says why",
           any("no 'Initiative' issue type" in w for w in _warnings(rid)), str(_warnings(rid)))


async def hierarchy_refused(rid: str, fake: FakeJira) -> None:
    await tracker.on_backlog(rid, {"run_id": rid, "vision": VISION}, BACKLOG)
    epics = fake.of_type("Epic")
    expect("when the hierarchy refuses initiative > epic, epics are still created",
           len(fake.of_type("Initiative")) == 1 and len(epics) == 2 and all(e["parent"] is None for e in epics))
    expect("and the refusal is reported", any("refused initiative > epic" in w for w in _warnings(rid)))


async def points_refused(rid: str, fake: FakeJira) -> None:
    await tracker.on_backlog(rid, {"run_id": rid, "vision": VISION}, BACKLOG)
    stories = fake.of_type("Story")
    expect("a story points field missing from the screen is dropped, not fatal",
           len(stories) == 3 and all(s["points"] is None for s in stories))


async def rate_limited(rid: str, fake: FakeJira) -> None:
    await tracker.on_backlog(rid, {"run_id": rid, "vision": VISION}, BACKLOG)
    expect("a 429 is retried and the backlog still lands", len(fake.issues) == 6, str(len(fake.issues)))


async def no_board(rid: str, fake: FakeJira) -> None:
    state = {"run_id": rid, "vision": VISION}
    await tracker.on_backlog(rid, state, BACKLOG)
    await tracker.on_sprint(rid, state, SPRINT)
    expect("with no scrum board the sprint is skipped and said so",
           not fake.sprints and any("no scrum board" in w for w in _warnings(rid)))


async def auth_failure(rid: str, fake: FakeJira) -> None:
    state = {"run_id": rid, "vision": VISION}
    try:
        await tracker.on_backlog(rid, state, BACKLOG)
        await tracker.on_sprint(rid, state, SPRINT)
        await tracker.on_story_result(rid, {"story_id": "S1", "status": "green"}, 0)
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
    expect("a revoked token never raises into the run", not raised)
    expect("it is logged as a warning instead",
           any("Jira sync skipped" in w and "401" in w for w in _warnings(rid)), str(_warnings(rid)))


async def disabled(rid: str, fake: FakeJira) -> None:
    saved = _configure(False)
    try:
        await tracker.on_backlog(rid, {"run_id": rid, "vision": VISION}, BACKLOG)
    finally:
        for k, v in saved.items():
            setattr(settings(), k, v)
    expect("unconfigured, it makes no calls at all", fake.calls == [], str(fake.calls[:3]))


async def main() -> int:
    saved = _configure(True)
    # The tracker hooks also mirror into Plane; these made-up runs must not land there.
    saved["plane_api_token"] = settings().plane_api_token
    settings().plane_api_token = ""
    try:
        await scenario("full hierarchy", FakeJira(), full_hierarchy)
        await scenario("no Initiative type", FakeJira(initiative=False), no_initiative)
        await scenario("hierarchy refuses initiative > epic", FakeJira(hierarchy=False), hierarchy_refused)
        await scenario("story points not on the create screen", FakeJira(points_on_screen=False), points_refused)
        await scenario("rate limited", FakeJira(rate_limit_first_create=True), rate_limited)
        await scenario("kanban-only project", FakeJira(scrum_board=False), no_board)
        await scenario("revoked token", FakeJira(auth_ok=False), auth_failure)
        await scenario("not configured", FakeJira(), disabled)
    finally:
        for k, v in saved.items():
            setattr(settings(), k, v)
    print("\nALL PASSED" if not failures else f"\n{len(failures)} FAILED: " + "; ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
