"""Acceptance checks against the running application.

The browser check proves every screen opens and shows data; it cannot tell a screen that
shows the right numbers from one that shows plausible ones. DupeGuard's acceptance criteria
say exactly what must hold ("tickets scoring 85 or more are closed as Duplicate", "no P1
ticket is auto-closed", "undoing a closure lowers precision"), and those were checked by
hand. Here the platform checks them itself, after deploy, through the app's own API.

For each built story the Acceptance Tester writes `acceptance/test_<story>.py` from the
story's criteria, the brief's requirements it delivers and the routes the app serves; it
never sees the implementation. The checks run in the sandbox on the app's own network,
signed in as the platform's service account (enterprise apps) or as a persona. A failing
check is triaged once by the same agent, which either corrects the check (it misread the
API) or reports what the app gets wrong; what remains becomes a blocking finding against
the story, so a rework round rebuilds it with the finding in hand. The checks stay in the
repository and run again every round, as regression. The database is reset afterwards, so
the stakeholder opens the app on its demonstration data, not on what the checks did to it.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from typing import Any

from ... import requirements as req
from ...agents import schemas
from ...agents.base import ACCEPTANCE
from ...config import pack
from ...events import emit
from ...llm import ReplyTruncated, UnparseableReply
from ...workspace import repo
from ...workspace import deployment as runtime
from ...workspace import samples
from ...workspace.interface import route_contract
from ...workspace.runner import run_in_sandbox
from ..memo import remember
from ..state import RunState

DIR = "acceptance"
CONFTEST = '''"""Fixtures for the acceptance checks. Written by Poiesis, and rewritten every round."""
import os

import httpx
import pytest

BASE = os.environ.get("BASE_URL", "http://localhost").rstrip("/")
TOKEN = os.environ.get("SERVICE_TOKEN", "")


@pytest.fixture
def api():
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    with httpx.Client(base_url=BASE, headers=headers, timeout=60) as client:
        yield client


@pytest.fixture
def sign_in():
    clients = []

    def as_persona(username):
        r = httpx.post(f"{BASE}/api/auth/sign-in", json={"username": username}, timeout=30)
        assert r.status_code == 200, f"signing in as {username}: {r.status_code} {r.text}"
        client = httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {r.json()['token']}"}, timeout=60)
        clients.append(client)
        return client

    yield as_persona
    for c in clients:
        c.close()
'''


def enabled() -> bool:
    return bool(pack().get("build", {}).get("acceptance", False))


def _file(story_id: str) -> str:
    return f"{DIR}/test_{re.sub(r'[^a-z0-9]+', '_', story_id.lower())}.py"


def _story_of(path: str) -> str:
    m = re.search(r"test_([a-z]+\d+)", path.lower())
    return m.group(1).upper() if m else ""


def _stories(state: RunState) -> list[dict[str, Any]]:
    """Stories built green or amber this round: the ones whose criteria should hold."""
    built = {r.get("story_id"): r.get("status") for r in (state.get("test_report") or {}).get("stories", [])}
    wanted = {e.get("id") for e in (state.get("sprint") or {}).get("stories", [])}
    return [s for s in (state.get("backlog") or {}).get("stories", [])
            if s.get("id") in wanted and built.get(s.get("id")) not in ("dropped", "blocked")]


def _personas(state: RunState) -> str:
    d = state.get("domain") or {}
    people = d.get("personas") or []
    if not people:
        return "This application has no sign-in: use `api` only.\n"
    return ("PERSONAS for `sign_in(username)`:\n" + "\n".join(
        f"- {p.get('username')}: {p.get('full_name')}, {p.get('title')} — roles {', '.join(p.get('roles') or [])}"
        for p in people) + "\n")


def _brief_for(state: RunState, story: dict[str, Any]) -> str:
    inv = {it["id"]: it for it in state.get("requirements") or []}
    items = [inv[r] for r in sorted(req.story_mentions(story)) if r in inv]
    return req.describe(items) if items else "(none named)"


async def _write_checks(state: RunState, run_id: str, story: dict[str, Any], grounding: str) -> str | None:
    sid = str(story.get("id"))
    rel = _file(sid)
    criteria = "\n".join(f"{i}. {c}" for i, c in enumerate(story.get("acceptance_criteria") or [], 1))
    prompt = (
        f"STORY {sid}: {story.get('title')}\n{story.get('narrative', '')}\n\nACCEPTANCE CRITERIA:\n{criteria}\n\n"
        f"REQUIREMENTS OF THE BRIEF THIS STORY DELIVERS:\n{_brief_for(state, story)}\n\n"
        + _personas(state) + "\n" + route_contract(run_id) + "\n" + grounding
        + f"\n\nWrite {rel}."
    )
    # Keyed by everything it was shown: a replay after the app or the prompt changed writes afresh.
    key = f"acceptance:{sid}:{hashlib.sha1(prompt.encode()).hexdigest()[:10]}"
    try:
        reply = await remember(run_id, key, lambda: ACCEPTANCE.json(prompt, max_tokens=7000))
    except (ReplyTruncated, UnparseableReply):
        return None
    body = next((v for k, v in (reply.get("files") or {}).items() if k.endswith(".py") and isinstance(v, str)), "")
    if "def test_" not in body:
        return None
    # A field no response has is the commonest wrong check (DupeGuard's filtered the review queue
    # on a `state` it does not carry): caught here, before it runs, and handed back once.
    unknown = samples.unknown_reads(body, samples.known_fields(run_id))
    if unknown:
        fix_key = f"{key}:fields:{','.join(unknown)}"
        try:
            fixed = await remember(run_id, fix_key, lambda: ACCEPTANCE.json(
                prompt + f"\n\nYOUR FILE:\n{body}\n\nIt reads fields that no response and no table has: "
                + ", ".join(unknown) + ". They do not exist. Read only the fields LIVE RESPONSES shows, and return "
                "the corrected file.", max_tokens=7000))
            better = next((v for k, v in (fixed.get("files") or {}).items() if k.endswith(".py") and "def test_" in str(v)), "")
            if better:
                body = better
        except (ReplyTruncated, UnparseableReply):
            pass
    repo.write_files(run_id, {rel: body})
    return rel


def _junit(run_id: str) -> list[dict[str, Any]]:
    path = repo.workspace_path(run_id) / ".poiesis" / "acceptance.xml"
    if not path.is_file():
        return []
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return []
    out = []
    for case in tree.iter("testcase"):
        bad = case.find("failure") if case.find("failure") is not None else case.find("error")
        out.append({"name": case.get("name", ""), "file": case.get("classname", "").replace(".", "/") + ".py",
                    "passed": bad is None and case.find("skipped") is None,
                    "message": ((bad.get("message") or "") + "\n" + (bad.text or ""))[:1500] if bad is not None else ""})
    return out


async def _run(run_id: str, target: str) -> list[dict[str, Any]]:
    service, port = runtime.entry_service(run_id)
    token = runtime.service_token(run_id) if (repo.workspace_path(run_id) / "backend" / "app" / "kernel").is_dir() else ""
    (repo.workspace_path(run_id) / ".poiesis" / "acceptance.xml").unlink(missing_ok=True)
    await run_in_sandbox(
        run_id,
        "pip install --quiet --disable-pip-version-check --root-user-action=ignore pytest httpx >/dev/null 2>&1; "
        f"python -m pytest {target} --confcutdir={DIR} -q -p no:cacheprovider --tb=short "
        "--junitxml=.poiesis/acceptance.xml 2>&1 | tail -40",
        timeout=900, network_name=f"{runtime.project_name(run_id)}_default",
        env={"BASE_URL": f"http://{service}:{port}", "SERVICE_TOKEN": token},
    )
    return _junit(run_id)


async def _triage(run_id: str, state: RunState, story: dict[str, Any], rel: str,
                  failures: list[dict[str, Any]], round_: int, grounding: str) -> dict[str, str]:
    """Correct the checks that misread the API; return {test: finding} for what the app gets wrong."""
    text = "\n\n".join(f"### {f['name']}\n{f['message']}" for f in failures)
    key = f"acceptance:triage:{story.get('id')}:{round_}:{hashlib.sha1(text.encode()).hexdigest()[:10]}"
    criteria = "\n".join(f"- {c}" for c in story.get("acceptance_criteria") or [])
    try:
        reply = await remember(run_id, key, lambda: ACCEPTANCE.json(
            f"TRIAGE these failures of the acceptance checks for story {story.get('id')}: {story.get('title')}.\n\n"
            f"CRITERIA:\n{criteria}\n\nTHE FILE {rel}:\n{repo.read(run_id, rel, 20000)}\n\n"
            f"FAILURES AGAINST THE RUNNING APP:\n{text[:9000]}\n\n{_personas(state)}\n{route_contract(run_id)}\n{grounding}",
            max_tokens=7000, schema=schemas.ACCEPTANCE_TRIAGE))
    except (ReplyTruncated, UnparseableReply):
        return {f["name"]: f["message"].splitlines()[0][:300] for f in failures}
    body = next((v for k, v in (reply.get("files") or {}).items() if k.endswith(".py") and "def test_" in str(v)), "")
    if body:
        repo.write_files(run_id, {rel: body})
    return {v["test"]: v.get("finding", "") for v in reply.get("verdicts") or [] if v.get("verdict") == "app_wrong"}


async def check_acceptance(state: RunState, run_id: str) -> dict[str, Any]:
    """Write, run and triage the acceptance checks; returns the record kept on the deployment."""
    stories = _stories(state)
    if not stories:
        return {"ran": False, "reason": "no built stories"}
    repo.write_files(run_id, {f"{DIR}/conftest.py": CONFTEST})
    await emit(run_id, f"Checking {len(stories)} story(ies)' acceptance criteria against the running app",
               agent="tester", stage="deploy")
    by_story = {str(s.get("id")): s for s in stories}
    grounding = samples.allowed_values(run_id) + await samples.live_samples(run_id)
    written = []
    for s in stories:
        rel = _file(str(s.get("id")))
        if not (repo.workspace_path(run_id) / rel).is_file():
            rel = await _write_checks(state, run_id, s, grounding)
        if rel:
            written.append(rel)
    if not written:
        return {"ran": False, "reason": "no checks could be written"}
    cases = await _run(run_id, DIR)
    round_ = int(state.get("repair_attempts", 0)) + int(state.get("human_rebuilds", 0))
    confirmed: dict[str, list[dict[str, str]]] = {}
    unproven: dict[str, list[dict[str, str]]] = {}
    failing_by_file: dict[str, list[dict[str, Any]]] = {}
    for c in cases:
        if not c["passed"]:
            failing_by_file.setdefault(c["file"], []).append(c)
    for rel, fails in failing_by_file.items():
        story = by_story.get(_story_of(rel))
        if story is None:
            continue
        app_wrong = await _triage(run_id, state, story, rel, fails, round_, grounding)
        rerun = {c["name"]: c for c in await _run(run_id, rel)}
        for name, c in rerun.items():
            if c["passed"]:
                continue
            if name in app_wrong:
                confirmed.setdefault(str(story.get("id")), []).append({"test": name, "finding": app_wrong[name]})
            else:
                # The triage blamed the check and could not correct it: nothing is proven either way.
                unproven.setdefault(str(story.get("id")), []).append(
                    {"test": name, "why": c["message"].splitlines()[0][:200] if c["message"] else ""})
        for c in cases:
            if c["file"] == rel and c["name"] in rerun:
                c["passed"] = rerun[c["name"]]["passed"]
    # Blocking only when the pack says so: a check a local model got wrong, triaged as the
    # app's fault, would send correct code into rework to satisfy it. By default the failures
    # are evidence for the Reviewer and the release gate.
    severity = "blocker" if pack().get("build", {}).get("acceptance_blocking", False) else "major"
    findings = [{
        "severity": severity, "story_id": sid, "file": _file(sid),
        "finding": f"Acceptance check {f['test']} fails against the running app: {f['finding']}",
        "required_fix": "Make the story do what its acceptance criterion states; the check calls the API "
                        "the way a person using the app would.",
    } for sid, items in confirmed.items() for f in items]
    passed = sum(1 for c in cases if c["passed"])
    record = {"ran": True, "total": len(cases), "passed": passed, "files": written,
              "failing": {sid: [f["test"] for f in items] for sid, items in confirmed.items()},
              "unproven": {sid: [f["test"] for f in items] for sid, items in unproven.items()},
              "findings": findings}
    repo.commit(run_id, f"test(acceptance): {passed}/{len(cases)} acceptance checks pass against the running app")
    await emit(run_id, f"Acceptance checks: {passed} of {len(cases)} pass against the running app"
                       + (f"; failing in {', '.join(sorted(confirmed))}" if confirmed else "")
                       + (f"; not proven either way in {', '.join(sorted(unproven))}" if unproven else ""),
               agent="tester", stage="deploy", level="warn" if confirmed else "info",
               data={k: v for k, v in record.items() if k != "findings"})
    # The stakeholder opens the app on its demonstration data, not on what the checks did.
    await runtime.deploy(run_id, fresh=True)
    return record
