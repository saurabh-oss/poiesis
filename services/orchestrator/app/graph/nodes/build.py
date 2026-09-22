"""Stage 7-8: implement and verify each sprint story, with a bounded repair loop.

The Developer and Tester are separate agents on purpose. The Tester never sees the
Developer's reasoning, only the story and the resulting code, so it cannot be talked
into agreeing that the implementation is correct.

"Verified" means more than pytest. The suite exercises only the backend, and a
story once went green, was reviewed and was released with a page that threw on
load. Every attempt now also runs the platform's frontend checks (workspace/
checks.py): each screen must parse, load, export a title and a render function,
call only routes the API serves, and exist at all. Their findings are appended to
the same output the repair loop hands back to the Developer.
"""
from __future__ import annotations

import ast
import re
from typing import Any

from ...agents.base import DEVELOPER, TESTER
from ...config import pack
from ... import telemetry
from ...events import emit
from ...integrations import gitremote, tracker
from ...llm import ReplyTruncated, UnparseableReply
from ...reuse.retriever import render_for_prompt, render_lessons
from ...workspace import repo
from ...workspace.checks import (
    mount_bare_routers,
    platform_checks,
    preserve_shared,
    regenerate_registry,
    test_issues,
)
from ...workspace.interface import (
    EDITABLE,
    excerpt,
    import_contract,
    reference,
    route_contract,
    story_files,
)
from ...workspace.runner import (
    ExecResult,
    preflight,
    pytest_command,
    run_in_sandbox,
    sandbox_timeout,
)
from ..gates import raise_gate
from ..memo import remember
from ..state import RunState
from ..store import save_artifact, set_stage
from .scaffold import PROTECTED, refresh_platform_files


def _story(state: RunState, story_id: str) -> dict[str, Any]:
    for s in state["backlog"].get("stories", []):
        if s.get("id") == story_id:
            return s
    return {"id": story_id, "title": story_id, "acceptance_criteria": []}


def _findings_for(state: RunState, story_id: str) -> str:
    """What the Reviewer said last round, so a rework pass is not a blind retry.

    Without this the Developer receives byte-identical input to the round that was
    rejected, and produces the same code. Findings are matched to the story by id
    where the Reviewer named one, and unattributed blockers go to every story.
    """
    review = state.get("review") or {}
    findings = [
        *(review.get("blocking_findings") or []),
        *(review.get("advisory_findings") or []),
    ]
    if not findings:
        return ""

    relevant = [
        f for f in findings
        if story_id in str(f.get("story_id") or "") or not f.get("story_id")
    ]
    if not relevant:
        return ""

    lines = "\n".join(
        f"- [{f.get('severity', 'advisory')}] {f.get('file', 'unknown file')}: "
        f"{f.get('finding', '')}"
        + (f"\n  Required fix: {f['required_fix']}" if f.get("required_fix") else "")
        for f in relevant[:10]
    )
    return (
        "\n\nTHE PREVIOUS INCREMENT WAS REJECTED. These findings, from the Reviewer and "
        f"from the platform's check of the running app, are binding:\n{lines}\n"
        f"Reviewer's rationale: {str(review.get('verdict_rationale', ''))[:600]}\n"
        "Return the corrected implementation. Do not modify tests."
    )


def _skeleton(state: RunState) -> str:
    """Tell the Developer what already exists, so it extends rather than replaces."""
    sc = state.get("scaffold") or {}
    if not sc:
        return ""
    services = ", ".join(
        f"{s.get('name')}:{s.get('port')}" if s.get("port") else str(s.get("name"))
        for s in sc.get("services", [])
    )
    deployable = "\n".join(f"- {d}" for d in sc.get("definition_of_deployable", []))
    return (
        f"\n\nAPPLICATION SKELETON (already written, already boots — extend it, do not "
        f"recreate it):\n"
        f"archetype: {sc.get('archetype')}\n"
        f"services: {services or 'none'}\n"
        f"entrypoint: {sc.get('entrypoint')}\n"
        f"This increment is only deployable when:\n{deployable}\n"
    )


def _context(state: RunState, story: dict[str, Any], *, first: bool = True) -> str:
    """Everything the Developer needs, inside a 12k-token local context.

    The worked examples are shown on a first pass at a story; once the story has
    files of its own, those are shown instead, because they are what a repair
    builds on and the budget cannot hold both comfortably.
    """
    run_id = state["run_id"]
    tree = repo.tree(run_id, limit=50)
    own = story_files(run_id, story["id"])
    examples = reference(run_id) if first and "YOUR STORY'S FILES" not in own else ""
    return (
        f"STORY {story['id']}: {story.get('title','')}\n"
        f"{story.get('narrative','')}\n\n"
        "ACCEPTANCE CRITERIA:\n"
        + "\n".join(f"- {c}" for c in story.get("acceptance_criteria", []))
        + f"\n\nARCHITECTURE:\n{str(state['architecture'].get('components', []))[:2500]}\n"
        f"\nREUSE PLAN (binding):\n{str(state['architecture'].get('reuse_plan', []))[:1200]}\n"
        f"\nPORTFOLIO:\n{render_for_prompt(state.get('portfolio') or {'reuse_candidates': [], 'house_stack': [], 'prior_decisions': []}, limit=3)}\n"
        + _skeleton(state)
        + "\nCURRENT WORKSPACE FILES:\n" + ("\n".join(tree) or "(empty)")
        # Without the contracts the Developer rewrites every file from memory and
        # cannot see what the workspace already exports — which is how three
        # repair attempts reproduced the same invented import.
        + import_contract(run_id)
        + route_contract(run_id)
        + examples
        + excerpt(run_id, EDITABLE)
        + own
        + render_lessons(state.get("lessons_by_story", {}).get(story["id"], []))
        + _findings_for(state, story["id"])
    )


async def _recall_lessons(state: RunState, scope: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    from ...reuse.retriever import lessons_for
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in scope:
        story = _story(state, entry["id"])
        text = f"{story.get('title', '')} {story.get('narrative', '')} " + " ".join(story.get("acceptance_criteria") or [])
        hits = await lessons_for(text, limit=4)
        out[story["id"]] = [{"lesson": h.get("lesson"), "score": h.get("score")} for h in hits
                            if (h.get("score") or 0) >= 0.45]
    return out


def _rework_scope(state: RunState) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """On a rework pass, rebuild only what the checks or the Reviewer actually faulted.

    Returns (stories to build, prior results to carry forward). Re-running a whole
    sprint to fix one story costs a full round of Developer and Tester calls and
    risks regressing work that already passed.
    """
    entries = state["sprint"].get("stories", [])
    if not state.get("repair_attempts"):
        return entries, []

    prior = {r["story_id"]: r for r in (state.get("test_report") or {}).get("stories", [])}
    blocking = (state.get("review") or {}).get("blocking_findings") or []
    if any(not f.get("story_id") for f in blocking):
        return entries, []  # a blocker nobody attributed to a story: rebuild all

    faulted = {str(f.get("story_id")) for f in blocking}
    # "dropped" is a stakeholder decision at the failed_story gate, not a fault to
    # retry — rebuilding it would silently overrule "Drop this story" on the very
    # next rework pass.
    faulted |= {sid for sid, r in prior.items() if r.get("status") not in ("green", "dropped")}

    scope = [e for e in entries if e["id"] in faulted]
    if not scope:
        return entries, []
    carried = [prior[e["id"]] for e in entries if e["id"] not in faulted and e["id"] in prior]
    return scope, carried


# Where a story's own files live; an empty file returned here is a deletion.
_DELETABLE = ("backend/app/routers/", "frontend/screens/")
_COMMENT_LINE = re.compile(r"^\s*(#|//|--)")
_TIDY_SUFFIXES = (".py", ".js", ".ts", ".sql")


def _tidy(files: dict[str, Any]) -> dict[str, str]:
    """Collapse degenerate repetition before it is committed.

    A 14B model can fall into a loop appending the same comment; one routes.py
    reached about 30KB of repeated "--- other endpoints below this line ---"
    blocks. That spends output tokens (and truncates the JSON reply that carries
    the file) and poisons the file excerpt the next prompt is built from.
    Comments carry no behaviour, so a repeated comment line is dropped after its
    first appearance, and runs of blank lines are held to two.
    """
    tidied: dict[str, str] = {}
    for path, body in files.items():
        text = body if isinstance(body, str) else str(body or "")
        if not path.endswith(_TIDY_SUFFIXES):
            tidied[path] = text
            continue
        seen: set[str] = set()
        kept: list[str] = []
        blanks = 0
        for line in text.splitlines():
            if _COMMENT_LINE.match(line):
                key = line.strip()
                if key in seen:
                    continue
                seen.add(key)
            if line.strip():
                blanks = 0
            else:
                blanks += 1
                if blanks > 2:
                    continue
            kept.append(line)
        tidied[path] = "\n".join(kept) + ("\n" if text.endswith("\n") else "")
    return tidied


def _guard(
    state: RunState, files: dict[str, str]
) -> tuple[dict[str, str], list[str]]:
    """Drop edits to files the deployment depends on.

    Returns (files to write, refused paths). The Developer is told not to touch
    these; this is what happens when it does anyway.
    """
    protected = set((state.get("scaffold") or {}).get("protected") or ())
    if not protected:
        return files, []
    if "backend/app/main.py" in protected:
        # A web-app workspace: files protected since it was bootstrapped count too.
        protected |= set(PROTECTED)
    keep = {k: v for k, v in files.items() if k.lstrip("./") not in protected}
    refused = [k for k in files if k not in keep]
    return keep, refused


def _refused_note(refused: list[str]) -> str:
    if not refused:
        return ""
    return (
        f"\nYOUR EDITS TO {', '.join(refused)} WERE REFUSED: those files are read-only "
        "scaffold and were left as they are. Put the code in your story's own files — "
        "backend/app/routers/<resource>.py and frontend/screens/<resource>.js.\n"
    )


async def _mount_bare(run_id: str, sid: str) -> None:
    """Move a router declared at "/" to the path its screen and tests call. See checks.py."""
    for note in mount_bare_routers(run_id):
        await emit(run_id, f"{sid}: {note}", agent="governance", stage="build", level="warn")


async def _apply(
    run_id: str, state: RunState, sid: str, files: dict[str, Any], message: str,
) -> tuple[list[str], str | None, list[str]]:
    """Write a Developer reply: guarded, tidied, shared files kept whole, registry rebuilt.

    Returns (written paths, commit sha, refused paths).
    """
    proposed, refused = _guard(state, _tidy(files))
    if refused:
        await emit(
            run_id, f"{sid}: refused {len(refused)} edit(s) to read-only scaffold files: "
                    + ", ".join(refused),
            agent="developer", stage="build", level="warn", data={"refused": refused},
        )
    proposed, restored = preserve_shared(run_id, proposed)
    if restored:
        await emit(
            run_id, f"{sid}: the rewrite dropped definitions other code still uses; kept "
                    + ", ".join(restored),
            agent="governance", stage="build", level="warn", data={"restored": restored},
        )
    # A Developer that duplicated a router had no way to remove the stale copy, so
    # the duplicate-route check could only fail, round after round. An empty file
    # in the story's own area now deletes it (protected files never reach here).
    removed = [rel for rel, body in proposed.items()
               if not str(body).strip()
               and rel.replace("\\", "/").lstrip("./").startswith(_DELETABLE)]
    for rel in removed:
        proposed.pop(rel)
        repo.remove(run_id, rel)
    if removed:
        await emit(run_id, f"{sid}: removed {', '.join(removed)}",
                   agent="developer", stage="build", data={"removed": removed})
    written = repo.write_files(run_id, proposed)
    await _mount_bare(run_id, sid)
    # ES modules cannot list a directory, so the shell reads a generated registry.
    # Rebuilt after every write so a new screen is live on the next check.
    regenerate_registry(run_id)
    sha = repo.commit(run_id, message)
    return written, sha, refused


async def _tests_for(
    run_id: str, sid: str, rnd: int, story: dict[str, Any], impl: dict[str, Any]
) -> dict[str, Any]:
    """The Tester's pass over one story.

    It receives the same verified contracts as the Developer. Both agents were
    independently inventing the same non-existent symbols and the same wrong URLs,
    so the suite could not go green no matter how good the logic was. It sees the
    backend files only: the suite cannot exercise a screen, and the frontend is
    verified by the platform instead.
    """
    backend = {p: c for p, c in (impl.get("files") or {}).items()
               if isinstance(c, str) and (p.startswith("backend/") or p.endswith(".sql"))}
    return await remember(run_id, f"tests:{sid}:r{rnd}", lambda: TESTER.json(
        f"STORY {sid}: {story.get('title','')}\n"
        "ACCEPTANCE CRITERIA:\n"
        + "\n".join(f"- {c}" for c in story.get("acceptance_criteria", []))
        + import_contract(run_id)
        + route_contract(run_id)
        + "\n\nIMPLEMENTATION FILES:\n"
        + "\n\n".join(f"### {p}\n{c[:2500]}" for p, c in backend.items()),
        max_tokens=4000,
    ))


def _unsound_test_names(issues: list[str]) -> set[str]:
    """The test functions the platform itself judged impossible, by name."""
    return {m.group(1) for m in (re.search(r"::(test_\w+)", i) for i in issues) if m}


async def _sound_tests(
    run_id: str, state: RunState, sid: str, rnd: int, story: dict[str, Any],
    impl: dict[str, Any], revisions: int = 2,
) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    """The Tester's suite, revised until it is at least *possible* to pass.

    The Developer may not edit tests — that rule is what stops a model writing
    tests that pass — so a test asserting something no implementation can do
    used to be unfixable by anyone until the Tester was asked again, which only
    happened after three Developer repairs had already been spent on code that
    was never wrong. Checking the suite the moment it is written, and handing
    the Tester its own findings, spends one cheap revision instead of a story.

    Returns (the Tester's reply, the files written, the unsound tests that
    survived every revision — reported so the Reviewer sees the gap rather than
    the Developer being blamed for it).
    """
    try:
        tests = await _tests_for(run_id, sid, rnd, story, impl)
    except ValueError as exc:
        await emit(run_id, f"{sid}: the Tester's reply could not be parsed — {exc}",
                   agent="tester", stage="build", level="error")
        return {"files": {}, "criteria_covered": [], "criteria_not_covered": []}, {}, []

    files: dict[str, str] = {}
    problems: list[str] = []
    for attempt in range(revisions + 1):
        files, _ = _guard(state, _tidy(tests.get("files", {})))
        repo.write_files(run_id, files)
        paths = sorted(p for p in files if p.startswith("tests/"))
        problems = test_issues(run_id, paths)
        if not problems or attempt == revisions:
            break
        await emit(
            run_id,
            f"{sid}: {len(problems)} test(s) cannot pass as written — asking the Tester to "
            "revise before the Developer sees them",
            agent="tester", stage="build", level="warn", data={"problems": problems},
        )
        try:
            tests = await remember(run_id, f"tests:{sid}:r{rnd}:fix{attempt}", lambda: TESTER.json(
                f"STORY {sid}: {story.get('title','')}\n"
                "ACCEPTANCE CRITERIA:\n"
                + "\n".join(f"- {c}" for c in story.get("acceptance_criteria", []))
                + import_contract(run_id)
                + route_contract(run_id)
                + "\n\nTHESE TESTS CANNOT PASS AS WRITTEN. The platform checked them against "
                "the routes the API actually serves, before running them:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\n\nCURRENT TEST FILES:\n"
                + "\n\n".join(f"### {p}\n{repo.read(run_id, p)[:3000]}" for p in paths)
                + "\n\nRewrite only what those findings name. A criterion the API genuinely "
                "cannot demonstrate belongs in `criteria_not_covered` with the reason, not in a "
                "test that must fail. Return the complete test files.",
                max_tokens=4000,
            ))
        except ValueError:
            break  # keep the version already on disk

    if problems:
        await emit(
            run_id,
            f"{sid}: {len(problems)} test(s) still cannot pass; recorded as uncovered rather "
            "than failing the story on them",
            agent="tester", stage="build", level="warn", data={"problems": problems},
        )
    return tests, files, problems


async def _implement_with_recovery(
    run_id: str, state: RunState, story: dict[str, Any], rnd: int,
) -> dict[str, Any] | None:
    """The Developer's first pass at a story, with one recovery attempt.

    `DEVELOPER.json` already retries twice internally at a nudged temperature, so
    a story that lands here failed *that* twice too — usually because the file
    content it was writing (HTML with quoted attributes, a JS string literal)
    broke the JSON before `files` ever closed. Before this, that single failure
    marked the story permanently red with zero files and moved on.

    Feeding back exactly what came through — not a generic "try again" — is what
    makes the second attempt likely to differ from the first two.
    """
    sid = story["id"]
    try:
        return await remember(
            run_id, f"impl:{sid}:r{rnd}",
            lambda: DEVELOPER.json(_context(state, story), max_tokens=5500),
        )
    except ReplyTruncated as exc:
        # Nothing came back at all: the reply was too long, not malformed. Telling
        # this one to escape its quotes would waste the retry on the wrong repair.
        advice = (
            f"\n\nYOUR PREVIOUS REPLY WAS CUT OFF: it used its entire {exc.budget}-token "
            "budget and returned nothing at all. It was too long, not malformed. Write "
            "less, not differently. Return only the files this story actually needs to "
            "change. If a file holds a large amount of seed data, keep the rows compact — "
            "one INSERT with a tuple per line, one short sentence per description, no "
            "commentary between statements. Drop `reasoning` to a single short sentence."
        )
        await emit(
            run_id, f"{sid}: the Developer's reply was cut off by the {exc.budget}-token "
                    "budget — asking again for a shorter one",
            agent="developer", stage="build", level="warn", data={"budget": exc.budget},
        )
    except UnparseableReply as exc:
        advice = (
            "\n\nYOUR PREVIOUS REPLY COULD NOT BE READ AS JSON. It broke off around:\n"
            f"…{exc.raw[-1200:]}\n\n"
            "The likely cause is an unescaped double-quote inside a file's content — "
            "JS string literals and HTML attributes need \\\" inside a JSON string, not "
            "a bare \". Prefer single quotes in JavaScript. Put `files` first in the "
            "object. Keep `reasoning` to one short sentence this time."
        )
        await emit(
            run_id, f"{sid}: the Developer's reply could not be parsed as JSON — asking once more",
            agent="developer", stage="build", level="warn",
            data={"raw_preview": exc.raw[:4000]},
        )

    try:
        return await remember(
            run_id, f"impl:{sid}:r{rnd}:retry",
            lambda: DEVELOPER.json(_context(state, story) + advice, max_tokens=5500),
        )
    except UnparseableReply as exc:
        await emit(
            run_id, f"{sid}: still unparseable after a second attempt",
            agent="developer", stage="build", level="error",
            data={"raw_preview": exc.raw[:4000]},
        )
        return None


async def _repair_once(
    run_id: str, state: RunState, story: dict[str, Any], failed: ExecResult,
    key: str, label: str, extra: str = "",
) -> tuple[bool, list[str], list[str]]:
    """One Developer repair against the current failure.

    Returns (whether a usable reply came back, paths it tried to edit that were
    refused, paths it wrote).
    """
    sid = story["id"]
    prompt = (
        _context(state, story, first=False)
        + "\n\nYOUR PREVIOUS IMPLEMENTATION FAILED ITS CHECKS. The pytest output comes "
        "first. A 'PLATFORM CHECKS' section after it lists problems the platform found "
        "by loading your frontend. Fix those in your screen or router.\n"
        f"{failed.stdout[-6000:]}\n{failed.stderr[-800:]}\n"
        + extra
        + "\nReturn the corrected implementation files only, each complete. "
        "Do not modify the tests."
    )
    try:
        fix = await remember(run_id, key, lambda: DEVELOPER.json(prompt, max_tokens=5000))
    except UnparseableReply as exc:
        # A first implementation already got a targeted second attempt; a repair
        # did not, so one broken reply ended every remaining repair for the story.
        preview = exc.raw[-1000:]
        await emit(run_id, f"{sid}: the repair reply could not be parsed as JSON — asking once more",
                   agent="developer", stage="build", level="warn",
                   data={"raw_preview": exc.raw[:4000]})
        try:
            fix = await remember(run_id, f"{key}:retry", lambda: DEVELOPER.json(
                prompt
                + "\n\nYOUR PREVIOUS REPLY COULD NOT BE READ AS JSON. It broke off around:\n"
                f"…{preview}\n\nEscape every double quote inside file content as \\\" and every "
                "newline as \\n, prefer single quotes in JavaScript, put `files` first, and keep "
                "`reasoning` to one sentence.",
                max_tokens=5000,
            ))
        except ValueError as again:
            await emit(run_id, f"{sid}: repair reply unparseable twice, stopping repairs — {again}",
                       agent="developer", stage="build", level="error")
            return False, [], []
    except ValueError as exc:
        await emit(run_id, f"{sid}: repair reply unparseable, stopping repairs — {exc}",
                   agent="developer", stage="build", level="error")
        return False, [], []
    impl_files = {k: v for k, v in (fix.get("files") or {}).items()
                  if not k.startswith("tests/")}
    written, _, refused = await _apply(run_id, state, sid, impl_files, f"fix({sid}): {label}")
    return True, refused, written


_TEST_FN = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)", re.M)


def _function_source(src: str, names: set[str]) -> list[str]:
    """The original source of named top-level functions, to put back what a revision dropped."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            segment = ast.get_source_segment(src, node)
            if segment:
                out.append(segment)
    return out


async def _reconcile_tests(
    run_id: str, sid: str, rnd: int, story: dict[str, Any],
    test_paths: list[str], failed: ExecResult, attempts: int,
) -> bool:
    """One Tester revision after the Developer's repairs are spent.

    Forbidding the Developer to edit tests is right: it is what stops a model
    writing tests that pass. But it left the loop unable to converge when the
    *test* was the thing that was wrong. In a verified run the Tester read
    `return {"message": ...}` in an endpoint declaring response_model=
    LeaveRequestOut, asserted that message verbatim, and compared a whole list
    with == while omitting the generated id. Correct code could never pass, and
    the only agent allowed into the repair loop was forbidden to fix it.

    The revision is narrow, and the narrowness is enforced here rather than
    requested: only this story's own test files are accepted, never conftest or
    the smoke tests.

    A dropped test function used to reject the entire revision, which threw away
    the corrections in it as well — the story then stayed red with nobody left
    who was allowed to touch it. Now the revision lands and anything it deleted
    is put back, so "fix the test" still cannot become "delete the test"; the
    one exception is a test the platform's own checks independently judged
    impossible, where deleting it is the honest outcome and the criterion is
    reported as uncovered instead.
    """
    current = {p: repo.read(run_id, p) for p in test_paths}
    current = {p: c for p, c in current.items() if c}
    if not current:
        return False
    before = {p: set(_TEST_FN.findall(c)) for p, c in current.items()}

    try:
        revision = await remember(run_id, f"reconcile:{sid}:r{rnd}", lambda: TESTER.json(
            f"STORY {sid}: {story.get('title','')}\n"
            "ACCEPTANCE CRITERIA:\n"
            + "\n".join(f"- {c}" for c in story.get("acceptance_criteria", []))
            + import_contract(run_id)
            + route_contract(run_id)
            + f"\n\nYOUR TESTS STILL FAIL AFTER {attempts} DEVELOPER REPAIR ATTEMPTS. The "
            "Developer is not allowed to edit tests, so if a test is itself wrong, nobody "
            "else can fix it.\n\nCURRENT TEST FILES:\n"
            + "\n\n".join(f"### {p}\n{c[:3000]}" for p, c in current.items())
            + f"\n\npytest output:\n{failed.stdout.split('=== PLATFORM CHECKS')[0][-3500:]}\n\n"
            "For each failing test, decide whether the implementation is wrong or the test "
            "is wrong. A test is wrong when it contradicts VERIFIED ROUTES (path, status "
            "code, body fields or response fields), compares a whole response with ==, "
            "asserts the exact wording of an error message that FastAPI or Pydantic "
            "generates (assert the status code and the rejected field instead), asserts HTML, "
            "markup, buttons or links in an API response (the API returns data; the platform "
            "checks the screen in a real browser, so test the data behind it instead), "
            "asserts a button or link label, copies long text verbatim from the "
            "implementation (assert it is present and names the key terms instead), or "
            "asserts something no acceptance criterion asks for. Fix only those tests. "
            "Where the implementation is wrong, leave the test exactly as it is — its "
            "failure is the correct outcome.\n"
            "Keep every test function. Do not delete, skip or weaken any of them. Return the "
            "complete revised test files.",
            max_tokens=4000,
        ))
    except ValueError as exc:
        await emit(run_id, f"{sid}: the Tester's revision could not be parsed — {exc}",
                   agent="tester", stage="build", level="error")
        return False

    proposed = {p: str(c) for p, c in (revision.get("files") or {}).items() if p in current}
    if not proposed:
        return False
    allowed_to_go = _unsound_test_names(test_issues(run_id, list(current)))
    restored: list[str] = []
    for path, body in list(proposed.items()):
        dropped = (before[path] - set(_TEST_FN.findall(body))) - allowed_to_go
        if not dropped:
            continue
        kept = _function_source(current[path], dropped)
        if not kept:
            continue
        proposed[path] = body.rstrip() + "\n\n\n" + "\n\n\n".join(kept) + "\n"
        restored += sorted(dropped)
    if restored:
        await emit(
            run_id,
            f"{sid}: kept the Tester's corrections and put back "
            + ", ".join(restored) + ", which the revision had dropped",
            agent="governance", stage="build", level="warn", data={"restored": restored},
        )

    repo.write_files(run_id, _tidy(proposed))
    sha = repo.commit(run_id, f"test({sid}): revise tests against the verified contract")
    await emit(
        run_id,
        f"{sid}: Tester revised {len(proposed)} test file(s) after {attempts} failed "
        "repairs; every test function kept",
        agent="tester", stage="build", level="warn",
        data={"files": sorted(proposed), "commit": sha},
    )
    return True


# Every story's check runs these alongside its own tests: they prove the app
# boots and that no GET endpoint crashes, whoever broke it.
PLATFORM_TESTS = ("tests/test_scaffold_smoke.py", "tests/test_platform_endpoints.py")
_FAILED_FILE = re.compile(r"^(?:FAILED|ERROR) (tests/[\w./-]+?\.py)", re.M)


async def _verify(
    run_id: str, key: str, timeout: int, sid: str, require_screen: bool, own: set[str],
    story_tests: list[str],
) -> tuple[ExecResult, bool]:
    """pytest, then the platform's frontend checks, as one result the repair loop reads.

    Returns (combined result, whether pytest alone passed). The second value keeps
    the Tester out of it when only the frontend failed: its tests are not at fault.
    `own` is what this story wrote, so router findings stay with their author.

    pytest runs this story's tests and the platform's, not the whole suite. A story
    was held red through four repairs by another story's test that asserted a
    paragraph verbatim — a test it was not allowed to edit. The whole suite still
    runs once at the end of the round (_regressions), so a story that breaks
    another's tests does not go unnoticed.

    A replay reuses the recorded result rather than running the sandbox again.
    """
    root = repo.workspace_path(run_id)
    scope = [p for p in (*story_tests, *PLATFORM_TESTS) if (root / p).is_file()]

    async def _run() -> dict[str, Any]:
        async with telemetry.span("sandbox", f"pytest {sid}", story=sid, files=len(scope)) as sp:
            tests = await run_in_sandbox(run_id, pytest_command(" ".join(scope)),
                                         timeout=timeout, network=True)
            sp.set(exit_code=tests.exit_code, timed_out=tests.timed_out)
            if not tests.ok:
                sp.fail(f"pytest exited {tests.exit_code}")
        async with telemetry.span("checks", f"platform checks {sid}", story=sid) as sp:
            checks = await platform_checks(run_id, sid, require_screen, own)
            if not checks.ok:
                sp.fail("platform checks found problems")
        ok = tests.ok and checks.ok
        # Re-checked against the routes as they stand *now*, not as they stood when
        # the tests were written: a repair that drops an endpoint the tests still
        # call turns every one of them into a 405 the Developer cannot read as its
        # own doing. Saying so plainly is what gets the endpoint put back.
        drift = test_issues(run_id, story_tests) if not tests.ok else []
        return {
            "exit_code": 0 if ok else (tests.exit_code or 1),
            "stdout": tests.stdout[-3500:]
            + ("" if checks.ok else checks.stdout[:2500])
            + ("\n\n=== THE TESTS AND YOUR API NO LONGER AGREE ===\nThese tests were written "
               "against endpoints that are not there now. If the story needs them, put them "
               "back; the tests are not yours to change.\n"
               + "\n".join(f"- {d}" for d in drift[:8]) if drift else ""),
            "stderr": tests.stderr[-1500:],
            "timed_out": tests.timed_out,
            "pytest_ok": tests.ok,
        }
    r = await remember(run_id, f"verify:{key}", _run)
    return ExecResult(r["exit_code"], r["stdout"], r["stderr"], r["timed_out"]), bool(r["pytest_ok"])


async def _regressions(
    run_id: str, rnd: int, timeout: int, results: list[dict[str, Any]],
) -> None:
    """Run the whole suite once; a green story whose tests now fail goes red.

    Each story's own check runs only its tests, so a later story that broke an
    earlier story's behaviour would otherwise pass unnoticed. The broken story is
    marked red with the suite's output, which sends it to rework with the evidence.
    """
    owned = {p: r for r in results if r.get("status") == "green" for p in r.get("tests") or []}
    if not owned:
        return

    async def _run() -> dict[str, Any]:
        r = await run_in_sandbox(run_id, pytest_command(), timeout=timeout, network=True)
        return r.__dict__

    full = ExecResult(**await remember(run_id, f"test-suite:r{rnd}", _run))
    if full.ok:
        return
    for path in sorted(set(_FAILED_FILE.findall(full.stdout)) & owned.keys()):
        r = owned[path]
        if r.get("status") != "green":
            continue
        r["status"] = "red"
        r["reason"] = "its tests fail once the rest of the sprint is built"
        r["test_output"] = full.stdout[-3000:]
        await emit(run_id, f"{r['story_id']}: its tests fail once the rest of the sprint is "
                           "built — marked red so rework can fix the regression",
                   agent="tester", stage="build", level="error",
                   data={"output": full.stdout[-3000:]})


async def build(state: RunState) -> RunState:
    run_id = state["run_id"]
    await set_stage(run_id, "build")
    repo.init_workspace(run_id)

    mount_error = await preflight(run_id)
    if mount_error:
        await emit(run_id, mount_error, agent="system", stage="build", level="error")
        raise RuntimeError(mount_error)

    added = refresh_platform_files(run_id, state)
    if added:
        repo.commit(run_id, "chore(platform): add the platform's own checks")
        await emit(run_id, "Added the platform's own checks to this workspace: " + ", ".join(added),
                   agent="scaffold", stage="build", data={"files": added})

    max_repairs = pack().get("build", {}).get("max_repair_attempts", 3)
    timeout = sandbox_timeout()
    # A web-app story must be reachable in the browser; an API-only one need not be.
    require_screen = (state.get("scaffold") or {}).get("entrypoint") == "frontend"
    # The failed_story gate below replays this whole node, so every model call and
    # every sandbox run is keyed by story and attempt. `rnd` separates a genuine
    # rework round from a replay of the round that produced the gate.
    rnd = state.get("repair_attempts", 0)
    scope, results = _rework_scope(state)
    if results:
        await emit(
            run_id,
            f"Rework: rebuilding {len(scope)} of "
            f"{len(state['sprint'].get('stories', []))} stories; the rest stay as they are",
            agent="developer", stage="build",
            data={"rebuilding": [e["id"] for e in scope],
                  "carried": [r["story_id"] for r in results]},
        )

    # What past runs learned, matched to each story by meaning. One vector search
    # per story; memoised because this node replays on every failed_story gate.
    lessons_by_story = await remember(run_id, f"lessons:r{rnd}", lambda: _recall_lessons(state, scope))
    state = {**state, "lessons_by_story": lessons_by_story}
    if any(lessons_by_story.values()):
        await emit(run_id, f"Recalled lessons from past runs for "
                           f"{sum(1 for v in lessons_by_story.values() if v)} story(ies)",
                   agent="governance", stage="build", data={"lessons": lessons_by_story})

    for entry in scope:
        story = _story(state, entry["id"])
        await emit(run_id, f"Starting {story['id']}: {story.get('title','')}",
                   agent="developer", stage="build", data={"story": story})
        await tracker.on_story_started(run_id, story["id"])

        sid = story["id"]
        impl = await _implement_with_recovery(run_id, state, story, rnd)
        if impl is None:
            # Genuinely unusable, even after a targeted second attempt. This gets
            # the same decision the human gets for a story that fails its checks.
            result = {"story_id": sid, "title": story.get("title", ""),
                      "status": "red", "repair_attempts": 0,
                      "reason": "unparseable model output", "files": [],
                      "criteria_covered": [], "criteria_not_covered": [], "test_output": ""}
            results.append(result)
            decision = await raise_gate(
                run_id=run_id, kind="failed_story", stage="build",
                question=f"{sid} could not be implemented — the Developer's reply could not "
                         "be read as JSON, twice in a row. How should the sprint proceed?",
                artifact={"story": story,
                          "output": "The model's replies for this story could not be parsed "
                                    "as JSON. See the build log for what came back."},
                options=[
                    {"value": "continue", "label": "Carry on, flag it in review"},
                    {"value": "drop", "label": "Drop this story from the sprint"},
                    {"value": "abort", "label": "Stop the sprint"},
                ],
                default={"decision": "continue", "notes": ""},
            )
            if decision.get("decision") == "drop":
                result["status"] = "dropped"
                result["reason"] = decision.get("notes") or "Dropped by the stakeholder."
                await emit(run_id, f"{sid}: dropped from the sprint — {result['reason']}",
                           agent="governance", stage="build", level="warn")
            await tracker.on_story_result(run_id, result, rnd)
            await gitremote.on_story_result(run_id, state, result)
            if decision.get("decision") == "abort":
                break
            continue

        if impl.get("blocked_reason"):
            await emit(run_id, f"{story['id']} blocked: {impl['blocked_reason']}",
                       agent="developer", stage="build", level="error")
            results.append({"story_id": story["id"], "status": "blocked",
                            "reason": impl["blocked_reason"]})
            continue

        written, sha, refused = await _apply(
            run_id, state, sid, impl.get("files", {}),
            impl.get("commit_message") or f"feat: {story['id']}",
        )
        await emit(
            run_id, f"{story['id']} implemented in {len(written)} files ({sha})",
            agent="developer", stage="build",
            data={"files": written, "commit": sha, "reasoning": impl.get("reasoning", "")},
        )

        # The Tester gets the same verified imports. It was independently inventing
        # the same non-existent symbols as the Developer, so a green suite was
        # impossible before either of them wrote a line of logic. Its suite is
        # then checked against the routes the API really serves, and revised, before
        # the Developer is ever asked to satisfy it.
        tests, test_files, unsound = await _sound_tests(run_id, state, sid, rnd, story, impl)
        await _mount_bare(run_id, sid)
        repo.commit(run_id, f"test: cover {story['id']}")
        own_tests = sorted(p for p in test_files if p.startswith("tests/"))
        await emit(
            run_id,
            f"{len(tests.get('criteria_covered', []))}/"
            f"{len(story.get('acceptance_criteria', []))} criteria under test",
            agent="tester", stage="build",
            data={"covered": tests.get("criteria_covered", []),
                  "gaps": tests.get("criteria_not_covered", [])},
        )

        own = set(written)
        exec_result, pytest_ok = await _verify(
            run_id, f"{sid}:r{rnd}:a0", timeout, sid, require_screen, own, own_tests)
        attempts = 0
        while not exec_result.ok and attempts < max_repairs:
            attempts += 1
            what = ("tests pass, but the platform's frontend checks found problems"
                    if pytest_ok else "tests failing")
            await emit(
                run_id, f"{sid}: {what} — repair attempt {attempts}",
                agent="developer", stage="build", level="warn",
                data={"stdout": exec_result.stdout[-3000:]},
            )
            ok, refused, fixed = await _repair_once(
                run_id, state, story, exec_result, f"fix:{sid}:r{rnd}:a{attempts}",
                f"repair attempt {attempts}", _refused_note(refused),
            )
            own |= set(fixed)
            if not ok:
                break
            exec_result, pytest_ok = await _verify(
                run_id, f"{sid}:r{rnd}:a{attempts}", timeout, sid, require_screen, own, own_tests)

        # Repairs are spent. If the fault is in the tests, the Developer cannot fix
        # it, so the Tester gets one checked revision and the Developer one repair
        # against the result. Only when pytest itself failed: a frontend problem is
        # never the tests' fault.
        tests_revised = False
        if not exec_result.ok and not pytest_ok:
            own_tests = [p for p in test_files if p.startswith("tests/")]
            tests_revised = await _reconcile_tests(
                run_id, sid, rnd, story, own_tests, exec_result, attempts
            )
            if tests_revised:
                exec_result, pytest_ok = await _verify(
                    run_id, f"{sid}:r{rnd}:reconciled", timeout, sid, require_screen, own, own_tests)
                if not exec_result.ok:
                    attempts += 1
                    await emit(
                        run_id, f"{sid}: one repair against the revised tests",
                        agent="developer", stage="build", level="warn",
                        data={"stdout": exec_result.stdout[-3000:]},
                    )
                    ok, refused, fixed = await _repair_once(
                        run_id, state, story, exec_result, f"fix:{sid}:r{rnd}:post",
                        "repair against revised tests", _refused_note(refused),
                    )
                    own |= set(fixed)
                    if ok:
                        exec_result, pytest_ok = await _verify(
                            run_id, f"{sid}:r{rnd}:post", timeout, sid, require_screen, own, own_tests)

        status = "green" if exec_result.ok else "red"
        await emit(
            run_id, f"{story['id']} is {status} after {attempts} repair attempt(s)"
                    + ("" if exec_result.ok or not pytest_ok
                       else " — its tests pass, but its screen does not"),
            agent="tester", stage="build",
            level="info" if exec_result.ok else "error",
            data={"exit_code": exec_result.exit_code, "output": exec_result.stdout[-4000:]},
        )
        result = {
            "story_id": story["id"], "title": story.get("title", ""), "status": status,
            "repair_attempts": attempts, "tests_revised": tests_revised, "files": written,
            "tests": own_tests,
            "criteria_covered": tests.get("criteria_covered", []),
            # A test the platform judged impossible is a coverage gap, not evidence:
            # the Reviewer should see it as untested rather than as a passing story.
            "criteria_not_covered": list(tests.get("criteria_not_covered", [])) + [
                {"criterion": "(unverified)", "why": p} for p in unsound
            ],
            "test_output": exec_result.stdout[-3000:],
        }
        results.append(result)

        if not exec_result.ok:
            decision = await raise_gate(
                run_id=run_id, kind="failed_story", stage="build",
                question=f"{story['id']} still fails its checks after {attempts} repair "
                         "attempts. How should the sprint proceed?",
                artifact={"story": story, "output": exec_result.stdout[-4000:]},
                options=[
                    {"value": "continue", "label": "Carry on, flag it in review"},
                    {"value": "drop", "label": "Drop this story from the sprint"},
                    {"value": "abort", "label": "Stop the sprint"},
                ],
                default={"decision": "continue", "notes": ""},
            )
            if decision.get("decision") == "drop":
                result["status"] = "dropped"
                result["reason"] = decision.get("notes") or "Dropped by the stakeholder."
                await emit(run_id, f"{sid}: dropped from the sprint — {result['reason']}",
                           agent="governance", stage="build", level="warn")
        await tracker.on_story_result(run_id, result, rnd)
        await gitremote.on_story_result(run_id, state, result)
        if not exec_result.ok and decision.get("decision") == "abort":
            break

    await _regressions(run_id, rnd, timeout, results)
    regenerate_registry(run_id)
    repo.commit(run_id, "chore: refresh the screen registry")
    green = sum(1 for r in results if r["status"] == "green")
    report = {"stories": results, "green": green, "total": len(results)}
    await save_artifact(run_id, "test_report", "build", report)
    return {"build": {"commits": repo.tree(run_id)}, "test_report": report}
