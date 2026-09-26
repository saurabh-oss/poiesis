"""Self-test for the core engine. Makes no model calls and needs no Ollama, no
Jira, no GitHub: fakes answer over httpx mock transports, Qdrant runs in
memory, and the Git remote is a bare repository on disk.

What it proves:
  1. every agent schema is valid JSON Schema and accepts a well-formed reply;
  2. the native Ollama client streams, constrains to a schema, thinks only for
     the roles allowed to, recovers from a budget spent thinking, and reports
     truncation and a missing model as the distinct errors they are;
  3. every model call and span lands in the trace tables with its run, step
     and agent attached, without any call site naming them;
  4. the engine drives one run at a time, queues the next, cancels either, and
     starts the queued one when a slot frees;
  5. a run's workspace is pushed to a Git remote as it is built and tagged at
     release, and on GitHub the repository is created and a pull request opened;
  6. vector recall finds the lesson that applies by meaning;
  7. the observability API serves what was recorded.

    docker compose exec orchestrator python -m app.selftest_core

Everything it creates is removed at the end, pass or fail.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx

from . import llm, telemetry
from .agents import schemas
from .agents.base import DEVELOPER
from .config import settings
from .db import LLMCall, Run, Span, session
from .graph import engine
from .graph.memo import remember
from .graph.store import set_stage
from .integrations import gitremote
from .kg import vectors
from .reuse.retriever import _merge, normalise_terms
from .workspace import repo

PASSED: list[str] = []
FAILED: list[str] = []


def expect(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    print(("  ok   " if condition else "  FAIL ") + label + (f"  -- {detail}" if detail and not condition else ""))


# ---- a fake Ollama ------------------------------------------------------------------

class FakeOllama:
    """Answers /api/chat as Ollama does, streaming NDJSON. Scripted per test."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.script: list[dict] = []   # each: {content, thinking, done_reason, status}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/embed":
            body = json.loads(request.content)
            texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
            return httpx.Response(200, json={"embeddings": [_bow(t) for t in texts]})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "fake:latest"}]})
        body = json.loads(request.content)
        self.requests.append(body)
        step = self.script.pop(0) if self.script else {"content": '{"ok": true}'}
        if step.get("status", 200) != 200:
            return httpx.Response(step["status"], json={"error": step.get("error", "model not found")})
        lines = []
        for piece in [step.get("thinking", "")[i:i + 5] for i in range(0, len(step.get("thinking", "")), 5)]:
            lines.append(json.dumps({"message": {"role": "assistant", "content": "", "thinking": piece}, "done": False}))
        content = step.get("content", "")
        for piece in [content[i:i + 7] for i in range(0, len(content), 7)]:
            lines.append(json.dumps({"message": {"role": "assistant", "content": piece}, "done": False}))
        lines.append(json.dumps({"message": {"role": "assistant", "content": ""}, "done": True,
                                 "done_reason": step.get("done_reason", "stop"),
                                 "prompt_eval_count": 123, "eval_count": max(1, len(content) // 4),
                                 "eval_duration": 2_000_000_000, "prompt_eval_duration": 500_000_000,
                                 "load_duration": 100_000_000}))
        return httpx.Response(200, content="\n".join(lines).encode() + b"\n",
                              headers={"content-type": "application/x-ndjson"})


def _bow(text: str, dim: int = 64) -> list[float]:
    """A deterministic bag-of-words embedding: enough for 'similar' to mean similar."""
    vec = [0.0] * dim
    for word in text.lower().split():
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


# ---- a fake GitHub ------------------------------------------------------------------

class FakeGitHub:
    def __init__(self) -> None:
        self.repos: dict[str, dict] = {}
        self.branches: dict[str, set[str]] = {}
        self.pulls: list[dict] = []
        self.calls: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.method} {path}")
        if path == "/user":
            return httpx.Response(200, json={"login": "acme"})
        if path == "/user/repos" and request.method == "POST":
            body = json.loads(request.content)
            full = f"acme/{body['name']}"
            self.repos[full] = {"full_name": full, "html_url": f"https://github.com/{full}",
                                "default_branch": "main", "size": 0}
            self.branches[full] = set()
            return httpx.Response(201, json=self.repos[full])
        parts = path.strip("/").split("/")
        if parts[0] == "repos" and len(parts) >= 3:
            full = f"{parts[1]}/{parts[2]}"
            if len(parts) == 3:
                repo_ = self.repos.get(full)
                return httpx.Response(200, json=repo_) if repo_ else httpx.Response(404, json={"message": "Not Found"})
            if parts[3] == "branches":
                return httpx.Response(200 if parts[4] in self.branches.get(full, set()) else 404, json={})
            if parts[3] == "pulls" and request.method == "GET":
                head = request.url.params.get("head", "")
                return httpx.Response(200, json=[p for p in self.pulls if f"acme:{p['head']}" == head])
            if parts[3] == "pulls" and request.method == "POST":
                body = json.loads(request.content)
                pr = {"number": len(self.pulls) + 1, "html_url": f"https://github.com/{full}/pull/{len(self.pulls) + 1}",
                      "head": body["head"], "base": body["base"], "title": body["title"]}
                self.pulls.append(pr)
                return httpx.Response(201, json=pr)
        return httpx.Response(404, json={"message": f"unhandled {request.method} {path}"})


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True).stdout


def _run_row(title: str) -> str:
    with session() as s:
        run = Run(title=title, status="queued")
        s.add(run)
        s.commit()
        return run.id


def _drop_runs(ids: list[str]) -> None:
    with session() as s:
        for rid in ids:
            row = s.get(Run, rid)
            if row is not None:
                s.delete(row)
        s.commit()


# ---- the tests ----------------------------------------------------------------------

async def test_schemas() -> None:
    print("\n[1] agent schemas")
    from jsonschema import Draft202012Validator
    for name, schema in schemas.ALL.items():
        try:
            Draft202012Validator.check_schema(schema)
            expect(f"schema '{name}' is valid JSON Schema", True)
        except Exception as exc:  # noqa: BLE001
            expect(f"schema '{name}' is valid JSON Schema", False, str(exc)[:200])
    impl = {"files": {"backend/app/routers/x.py": "router = 1"}, "commit_message": "feat: x",
            "manual_steps": [], "blocked_reason": None, "reasoning": "short"}
    Draft202012Validator(schemas.IMPLEMENTATION).validate(impl)
    expect("a well-formed Developer reply validates", True)
    review = {"dimensions": {k: {"score": 80, "notes": ""} for k in
                             ("acceptance_criteria_met", "reuse_compliance", "test_adequacy",
                              "maintainability", "operational_safety")},
              "blocking_findings": [], "advisory_findings": [], "verdict": "ship", "verdict_rationale": "fine"}
    Draft202012Validator(schemas.REVIEW).validate(review)
    expect("a well-formed Reviewer reply validates", True)
    bad = list(Draft202012Validator(schemas.REVIEW).iter_errors({**review, "verdict": "maybe"}))
    expect("an invented verdict is rejected by the schema", bool(bad))


async def test_requirements() -> None:
    """The brief as a checklist, on the enterprise DupeGuard run's failures: a backlog with no story
    for the screen M10, and a domain that simplified its rules and never tested their numbers."""
    print("\n[1b] requirements of the brief")
    from . import requirements as req
    from .graph.nodes.product import merge_additions
    evidence = [{"id": "f1", "content": (
        "Capability | What the stakeholder sees\n"
        "M1 | Duplicate Command Center | Headline numbers for the last 30 days\n"
        "M10 | Accuracy and settings | The thresholds in force, editable\n"
        "BR-01 Auto-close | Score ≥ 85 (auto-close threshold) | Close the newer ticket\n"
        "BR-10: A cluster of 5 or more duplicates within 24 hours is flagged.\n"
        "FR-09 | Scan all open tickets and apply BR-01 to BR-06 | Must | M4\n"
        "AC-8 (M10) Given the thresholds, when changed from 85 to 80, then the screen shows the effect.\n"
        "NFR-01 | A duplicate scan of 1,000 open tickets completes in under 10 seconds.\n"
        "Our engineers in M14 say the router shows a red light.")}]
    defined = req.defined_ids(evidence)
    ids = [d["id"] for d in defined]
    expect("the ids the brief defines are found, a mid-sentence mention is not",
           ids == ["M1", "M10", "BR-01", "BR-10", "FR-09", "AC-8", "NFR-01"], str(ids))
    expect("a figure keeps its thousands and loses its section reference",
           req.numbers_in("1,000 tickets in under 10 seconds (see 4.2)") == ["1000", "10"],
           str(req.numbers_in("1,000 tickets in under 10 seconds (see 4.2)")))
    brief = evidence[0]["content"] + "\nThe score weights are 55 / 20 / 15 / 10."
    modelled = [{"id": "M1", "kind": "capability", "title": "Command Center", "statement": "", "numbers": []},
                {"id": "BR-01", "kind": "rule", "title": "Auto-close", "statement": "", "numbers": ["85", "99"]},
                {"id": "REQ-1", "kind": "rule", "title": "Confidence score", "statement": "weighted sum",
                 "numbers": ["55", "20", "15", "10"]}]
    inv = req.merge(defined, modelled, brief)
    by = {i["id"]: i for i in inv}
    expect("an id the model left out is put back, classified like its family",
           by.get("M10", {}).get("kind") == "capability" and by.get("FR-09", {}).get("kind") == "functional",
           str({k: v["kind"] for k, v in by.items()}))
    expect("a number the brief never states is dropped", by["BR-01"]["numbers"] == ["85"], str(by["BR-01"]["numbers"]))
    expect("an unnumbered rule the model found is kept", "REQ-1" in by)

    backlog = {"epics": [{"id": "E1", "title": "Duplicate detection", "outcome": "find duplicates"},
                         {"id": "E4", "title": "Audit & Accuracy Monitoring", "outcome": "accuracy and settings"}],
               "stories": [{"id": "S1", "epic_id": "E1", "title": "Command Center", "covers": ["M1"],
                            "acceptance_criteria": ["a", "b"]},
                           {"id": "S2", "epic_id": "E1", "title": "Scan", "covers": ["FR-09"],
                            "acceptance_criteria": ["a", "b"]}],
               "not_covered": [{"id": "M10", "reason": "later"}, {"id": "AC-8", "reason": ""}]}
    cov = req.backlog_coverage(inv, backlog, domain_layer=True)
    expect("a screen the brief names with no story is missing, whatever reason is given",
           "M10" in cov["missing"], str(cov["missing"]))
    expect("an acceptance criterion without a story or a reason is missing", "AC-8" in cov["missing"])
    expect("rules are left to the domain layer when the pack has one", "BR-01" not in cov["missing"])
    superseded = [{**i, "superseded_by": "the director's brief asks for sign-in"} if i["id"] == "AC-8" else i for i in inv]
    expect("a requirement a later instruction replaced needs no story",
           "AC-8" not in req.backlog_coverage(superseded, backlog, domain_layer=True)["missing"])
    expect("without a domain layer a rule needs a story",
           "BR-01" in req.backlog_coverage(inv, backlog, domain_layer=False)["missing"])
    added = merge_additions(backlog, {"stories": [
        {"id": "S1", "epic_id": "E9", "title": "Accuracy and settings screen", "narrative": "accuracy thresholds",
         "covers": ["M10", "AC-8"], "acceptance_criteria": ["a", "b"], "depends_on": ["S1", "S77"]},
        {"id": "S2", "epic_id": "E1", "title": "Thin", "covers": ["x"], "acceptance_criteria": ["a"]}]})
    new = next(s for s in backlog["stories"] if s["id"] == added[0])
    expect("added stories get fresh ids, a known epic and only known dependencies; a thin one is refused",
           added == ["S3"] and new["epic_id"] == "E4" and new["depends_on"] == ["S1"], str((added, new)))
    cov = req.backlog_coverage(inv, backlog, domain_layer=True)
    expect("once a story delivers them, the screen and its criterion are covered",
           "M10" not in cov["missing"] and "AC-8" not in cov["missing"], str(cov["missing"]))

    rules_py = ('AUTO_CLOSE = 85\n@rule("BR-01", "Auto-close")\ndef auto(s): return s >= AUTO_CLOSE\n'
                'def keywords(): return "outage, down"  # Simplified for MVP\n')
    tests = ("def test_br_01_closes_at_threshold():\n    assert rules.auto(rules.AUTO_CLOSE)\n"
             "def test_br_10_suggests():\n    assert rules.suggest(5, 24)\n")
    gaps = req.domain_gaps(inv, ["BR-01", "BR-10"], tests, {"backend/app/domain/rules.py": rules_py})
    text = "\n".join(gaps)
    expect("a rule the brief states that the domain never registers is named", "REQ-1" in text, text[:300])
    expect("a test that reads the rule's constant instead of the brief's number is caught",
           "BR-01's tests never state the brief's number(s) 85" in text, text[:300])
    expect("tests that state the brief's numbers pass the check", "BR-10's tests" not in text)
    expect("a rule that admits a simplification is refused", "Simplified for MVP" in text)
    built = {"S1": "green", "S2": "red"}
    d = req.delivery(inv, backlog, built, domain_layer=True)
    expect("delivery names what no green story delivers, and why",
           {g["id"] for g in d["not_delivered"]} >= {"FR-09", "M10"} and "M1" in d["delivered"]
           and any("S2 red" in g["why"] for g in d["not_delivered"]), str(d)[:300])
    from .graph.nodes import acceptance
    from .workspace import samples
    expect("an acceptance check file names its story",
           acceptance._story_of("acceptance/test_s12.py") == "S12" and acceptance._file("S4") == "acceptance/test_s4.py")
    tmp_run = "selftest-allowed-values"
    root = repo.workspace_path(tmp_run)
    (root / "db").mkdir(parents=True, exist_ok=True)
    (root / "db" / "init.sql").write_text(
        "CREATE TABLE IF NOT EXISTS ticket (\n  id SERIAL PRIMARY KEY,\n"
        "  status VARCHAR(40) NOT NULL DEFAULT 'New',  -- New|Open|Duplicate\n"
        "  product_area VARCHAR(40) NOT NULL DEFAULT '', -- Broadband|TV|Mobile\n  subject TEXT -- free text\n);\n"
        "INSERT INTO ticket (status) VALUES ('New'); -- a|b\n", encoding="utf-8")
    listed = samples.allowed_values(tmp_run)
    expect("allowed values come from init.sql's comments, per table and column, and nothing else",
           "ticket.status: New|Open|Duplicate" in listed and "ticket.product_area: Broadband|TV|Mobile" in listed
           and "subject" not in listed and "a|b" not in listed, listed)
    shutil.rmtree(root, ignore_errors=True)
    from jsonschema import Draft202012Validator
    Draft202012Validator(schemas.BACKLOG).validate({**backlog, "stories": [
        {**s, "narrative": s.get("narrative", "x"), "value": 3, "estimate": 3, "risk": "low"} for s in backlog["stories"]]})
    expect("a backlog with covers and not_covered validates", True)


async def test_seed_loops() -> None:
    """DupeGuard's rerun: ticket → known issue → cluster → ticket, a loop no table order can satisfy."""
    print("\n[1c] demonstration data over tables that refer to each other in a loop")
    from .workspace.seedspec import expand_spec
    tables = {"ticket": {"subject": True, "known_issue_id": False}, "cluster": {"original_ticket_id": True},
              "known_issue": {"title": True, "cluster_id": False}}
    spec = {"tables": [
        {"table": "ticket", "count": 40, "columns": {
            "subject": {"kind": "catalogue", "values": ["a", "b", "c"]},
            "known_issue_id": {"kind": "ref", "table": "known_issue", "null_share": 0.5}}},
        {"table": "cluster", "count": 2, "columns": {"original_ticket_id": {"kind": "ref", "table": "ticket"}}},
        {"table": "known_issue", "count": 2, "columns": {
            "title": {"kind": "catalogue", "values": ["x", "y"]}, "cluster_id": {"kind": "ref", "table": "cluster"}}}]}
    rows, issues, _ = expand_spec(spec, tables)
    ids = [r["known_issue_id"] for r in rows["ticket"]]
    expect("a nullable reference to a later table is filled once every table has rows",
           not issues and {x for x in ids if x} <= {1, 2} and any(ids) and not all(ids), str((issues, ids))[:300])
    tables["ticket"]["known_issue_id"] = True
    _, issues, _ = expand_spec(spec, tables)
    expect("a NOT NULL reference to a later table still asks for the other order",
           any("earlier in the list" in i for i in issues), str(issues))


async def test_llm_client(fake: FakeOllama, rid: str) -> None:
    print("\n[2] native Ollama client")
    s = settings()
    s.poiesis_llm_profile = "local"
    s.poiesis_local_think_roles = "reasoning"
    llm.use_transport(fake.transport())
    token = telemetry.current_run.set(rid)
    try:
        fake.script = [{"content": '{"files": {"a.py": "x = 1"}, "commit_message": "feat"}'}]
        out = await DEVELOPER.json("STORY S1", max_tokens=100)
        req = fake.requests[-1]
        expect("streamed reply is assembled and parsed", out.get("files", {}).get("a.py") == "x = 1")
        expect("the Developer's schema constrains the reply", req.get("format") == schemas.IMPLEMENTATION)
        expect("the coding role does not think", req.get("think") is False)
        expect("num_ctx and keep_alive are sent with every request",
               req["options"].get("num_ctx") == s.poiesis_local_num_ctx and "keep_alive" in req)
        expect("the local floor raises a small budget (the coding floor for the Developer)",
               req["options"]["num_predict"] == s.poiesis_local_coding_min_tokens)

        fake.script = [{"content": '{"terms": ["x"]}', "thinking": "let me think"}]
        await llm.complete_json(role="reasoning", system="s", user="u", schema=schemas.TERMS)
        req = fake.requests[-1]
        expect("the reasoning role thinks first", req.get("think") is True)
        expect("thinking gets extra budget", req["options"]["num_predict"]
               == s.poiesis_local_min_tokens + s.poiesis_local_think_budget)

        fake.script = [{"content": "", "thinking": "..." * 50, "done_reason": "length"},
                       {"content": '{"terms": ["recovered"]}'}]
        n = len(fake.requests)
        out = await llm.complete_json(role="reasoning", system="s", user="u", schema=schemas.TERMS)
        expect("a budget spent thinking is retried once without thinking",
               out.get("terms") == ["recovered"] and len(fake.requests) == n + 2
               and fake.requests[-1].get("think") is False)

        fake.script = [{"content": '{"files": {"db/init.sql": "INSERT INTO t VALUES (1), (2', "done_reason": "length"},
                       {"content": '{"files": {"db/init.sql": "complete"}}'}]
        n = len(fake.requests)
        out = await llm.complete_json(role="coding", system="s", user="u", schema=schemas.IMPLEMENTATION)
        expect("a reply cut off mid-file is asked again with double the budget, not patched up",
               out["files"]["db/init.sql"] == "complete" and len(fake.requests) == n + 2
               and fake.requests[-1]["options"]["num_predict"] == min(2 * s.poiesis_local_coding_min_tokens,
                                                                    s.poiesis_local_max_tokens),
               str(fake.requests[-1]["options"]))

        fake.script = [{"content": "", "done_reason": "length"}]
        n = len(fake.requests)
        try:
            await llm.complete(role="coding", system="s", user="u")
            expect("an exhausted reply raises ReplyTruncated", False)
        except llm.ReplyTruncated:
            expect("an exhausted reply raises ReplyTruncated", True)
        expect("and is not retried", len(fake.requests) == n + 1)

        fake.script = [{"status": 404, "error": "model 'nope' not found"}]
        n = len(fake.requests)
        try:
            await llm.complete(role="coding", system="s", user="u")
            expect("a missing model raises ModelUnavailable", False)
        except llm.ModelUnavailable as exc:
            expect("a missing model raises ModelUnavailable", "ollama pull" in str(exc))
        expect("and is not retried either", len(fake.requests) == n + 1)

        fake.script = [{"status": 500, "error": "an error was encountered while running the model: CUDA error"},
                       {"content": '{"a": 2}'}]
        n = len(fake.requests)
        out = await llm.complete_json(role="coding", system="s", user="u")
        expect("a model-server crash is retried and the retry's reply is used",
               out == {"a": 2} and len(fake.requests) == n + 2)

        fake.script = [{"content": "<think>hmm</think>{\"a\": 1}"}]
        out = await llm.complete_json(role="coding", system="s", user="u")
        expect("inline <think> blocks are stripped", out == {"a": 1})

        fake.script = [{"content": '{"a": 1}'}]
        await llm.complete_json(role="coding", system="s", user="x" * 200_000)
        req = fake.requests[-1]
        expect("a prompt that would not fit grows num_ctx for that call instead of being cut",
               req["options"]["num_ctx"] > s.poiesis_local_num_ctx and req["options"]["num_ctx"] % 4096 == 0,
               str(req["options"]))

        vecs = await llm.embed(["seed rows", "other"])
        expect("embeddings come back one per text", len(vecs) == 2 and len(vecs[0]) == 64)
    finally:
        telemetry.current_run.reset(token)


async def test_tracing(rid: str) -> None:
    print("\n[3] traces")
    with session() as s:
        calls = s.query(LLMCall).filter(LLMCall.run_id == rid).order_by(LLMCall.started_at).all()
    expect("every model call was recorded for the run", len(calls) >= 6, f"{len(calls)} rows")
    first = calls[0] if calls else None
    expect("the call knows which agent asked", bool(first and first.agent == "developer"))
    expect("prompt, reply, tokens and duration are kept",
           bool(first and first.prompt.startswith("STORY S1") and first.response and
                first.prompt_tokens == 123 and first.duration_ms >= 0))
    statuses = {c.status for c in calls}
    expect("truncated and failed calls are marked as such", {"truncated", "error"} <= statuses, str(statuses))
    expect("thinking is stored with the call", any(c.think and c.thinking for c in calls))

    token = telemetry.current_run.set(rid)
    try:
        await remember(rid, "step:one", lambda: _traced_span())
        try:
            async with telemetry.span("sandbox", "boom"):
                raise RuntimeError("pytest exploded")
        except RuntimeError:
            pass
        await set_stage(rid, "build")
        await set_stage(rid, "deploy")
        await set_stage(rid, "done", status="complete")
    finally:
        telemetry.current_run.reset(token)
    with session() as s:
        spans = s.query(Span).filter(Span.run_id == rid).all()
    kinds = {(x.kind, x.name, x.status, x.step) for x in spans}
    expect("a span inside remember() carries the memo step", ("checks", "inside", "ok", "step:one") in kinds, str(kinds)[:300])
    expect("an exception marks the span failed and is re-raised", any(x.name == "boom" and x.status == "error" for x in spans))
    stage_names = [x.name for x in spans if x.kind == "stage"]
    expect("stage spans open and close from set_stage() alone", stage_names.count("build") == 1 and "deploy" in stage_names, str(stage_names))
    payload, _ = telemetry.metrics_payload()
    expect("Prometheus exposition includes model calls and spans",
           b"poiesis_llm_calls_total" in payload and b"poiesis_span_seconds" in payload)


async def _traced_span() -> dict:
    async with telemetry.span("checks", "inside"):
        return {"ok": True}


class FakeGraph:
    """Drives like the compiled graph, but waits on an event instead of working."""

    def __init__(self) -> None:
        self.gates: dict[str, asyncio.Event] = {}

    async def astream(self, payload, config, stream_mode="updates"):
        rid = config["configurable"]["thread_id"]
        ev = self.gates.setdefault(rid, asyncio.Event())
        await ev.wait()
        yield {}

    async def aget_state(self, config):
        return SimpleNamespace(next=(), tasks=[], values={})


async def test_engine(ids: list[str]) -> None:
    print("\n[4] engine: one driver at a time")
    settings().poiesis_max_concurrent_runs = 1
    fake = FakeGraph()
    engine._graph = fake
    r1, r2, r3 = ids
    try:
        expect("the first run drives at once", await engine.start(r1, "one") is True)
        expect("the second is queued", await engine.start(r2, "two") is False and engine.queued() == [r2])
        for _ in range(40):   # the status flips on a worker thread; give it a moment under load
            await asyncio.sleep(0.05)
            with session() as s:
                if s.get(Run, r1).status == "running" and s.get(Run, r2).status == "scheduled":
                    break
        with session() as s:
            expect("a queued run is marked scheduled", s.get(Run, r2).status == "scheduled")
            expect("a driving run is marked running", s.get(Run, r1).status == "running")
        expect("a queued run counts as busy", engine.is_busy(r2))
        expect("cancelling a queued run dequeues it", await engine.cancel(r2) == "dequeued" and engine.queued() == [])
        await engine.start(r3, "three")
        expect("cancelling a driving run", await engine.cancel(r1) == "cancelled")
        await asyncio.sleep(0.2)
        with session() as s:
            expect("...marks it cancelled and keeps its stage", s.get(Run, r1).status == "cancelled")
        expect("...and starts the queued run", r3 in engine.active() and engine.queued() == [], str(engine.stats()))
        fake.gates.setdefault(r3, asyncio.Event()).set()
        await asyncio.sleep(0.2)
        expect("a finished driver leaves the table", r3 not in engine.active())
        expect("a cancelled run can be retried", await engine.retry(r1) is True)
        fake.gates[r1].set()
        await asyncio.sleep(0.2)
    finally:
        for ev in fake.gates.values():
            ev.set()
        await asyncio.sleep(0.05)
        engine._graph = None


async def test_gitremote(rid: str, tmp: Path) -> None:
    print("\n[5] git remote")
    s = settings()
    remotes = tmp / "remotes"
    remotes.mkdir()
    bare = remotes / "selftest-app.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    s.git_remote_template = f"file://{bare.as_posix().replace('selftest-app', '{slug}')}"
    s.git_token = ""
    s.github_owner = ""
    state = {"run_id": rid, "title": "t", "vision": {"product_name": "Selftest App"}}
    repo.init_workspace(rid)
    try:
        await gitremote.on_workspace_ready(rid, state)
        refs = _git(bare, "for-each-ref", "--format=%(refname)")
        branch = gitremote.branch_for(rid)
        expect("the scaffold is pushed to run/<id>", f"refs/heads/{branch}" in refs, refs)
        repo.write_files(rid, {"a.txt": "one"})
        repo.commit(rid, "feat(S1): a")
        await gitremote.on_story_result(rid, state, {"story_id": "S1", "status": "green"})
        head = _git(repo.workspace_path(rid), "rev-parse", "HEAD").strip()
        remote_head = _git(bare, "rev-parse", branch).strip()
        expect("each story result pushes the commits so far", head == remote_head)
        await gitremote.on_release(rid, state, {"status": "released", "version": "0.2.0"})
        refs = _git(bare, "for-each-ref", "--format=%(refname)")
        expect("release pushes a tag", f"refs/tags/v0.2.0-{rid[:8]}" in refs, refs)
        expect("a plain remote gets its default branch fast-forwarded", "refs/heads/main" in refs, refs)
        m = gitremote.mapping(rid)
        expect("the mapping reports the branch and tag", m["branch"] == branch and m["release"].get("tag", "").startswith("v0.2.0"))
        expect("the web URL is derived for a person", gitremote.web_url("git@github.com:acme/x.git") == "https://github.com/acme/x"
               and gitremote.web_url("https://github.com/acme/x.git") == "https://github.com/acme/x")
        expect("the token never reaches the remote's stored URL",
               "secret" not in _git(repo.workspace_path(rid), "remote", "get-url", "origin"))

        # GitHub: repository creation and the pull request, with pushes recorded, not sent.
        gh = FakeGitHub()
        gitremote.use_transport(gh.transport())
        s.git_remote_template = "https://github.com/acme/poiesis-{slug}.git"
        s.git_token = "secret"
        s.github_owner = "acme"
        pushes: list[str] = []

        async def fake_push(run_id: str, refspec: str, *extra: str) -> str:
            pushes.append(refspec)
            return ""
        real_push = gitremote._push
        gitremote._push = fake_push  # type: ignore[assignment]
        rid2 = _run_row("git two")
        try:
            repo.init_workspace(rid2)
            state2 = {"run_id": rid2, "title": "t", "vision": {"product_name": "Hub App"}}
            await gitremote.on_workspace_ready(rid2, state2)
            expect("a missing GitHub repository is created", "acme/poiesis-hub-app" in gh.repos and "POST /user/repos" in gh.calls)
            await gitremote.on_release(rid2, state2, {"status": "released", "version": "0.1.0", "release_notes_markdown": "notes"})
            expect("a new repository gets its default branch from the first release",
                   any(p.endswith(":refs/heads/main") for p in pushes) and not gh.pulls, str(pushes))
            gh.branches["acme/poiesis-hub-app"].add("main")
            from .graph.memo import forget
            await forget(rid2, "git:release")
            await gitremote.on_release(rid2, state2, {"status": "released", "version": "0.2.0", "release_notes_markdown": "notes"})
            expect("once main exists a pull request is opened", len(gh.pulls) == 1 and gh.pulls[0]["base"] == "main", str(gh.pulls))
            await gitremote.on_release(rid2, state2, {"status": "released", "version": "0.2.0", "release_notes_markdown": "notes"})
            expect("a replayed release does not open a second one", len(gh.pulls) == 1)
            expect("the mapping shows the pull request", gitremote.mapping(rid2)["pull_request"].get("number") == 1)
            expect("a failing push never raises", await gitremote.on_story_result(rid2, state2, {"story_id": "S9"}) is None)
        finally:
            gitremote._push = real_push  # type: ignore[assignment]
            repo.destroy(rid2)
            _drop_runs([rid2])
    finally:
        gitremote.use_transport(None)
        s.git_remote_template = ""
        s.git_token = ""
        s.github_owner = ""
        repo.destroy(rid)


async def test_vectors() -> None:
    print("\n[6] vector recall")
    from qdrant_client import QdrantClient
    settings().poiesis_vectors = True
    vectors.use_client(QdrantClient(":memory:"))
    real_embed = vectors.embed

    async def fake_embed(texts):
        return [_bow(t) for t in texts]
    vectors.embed = fake_embed  # type: ignore[assignment]
    try:
        n = await vectors.upsert("lessons", [
            vectors.lesson_item("r1", "S1", "Seed every table a screen reads in db/init.sql", "screens that list rows"),
            vectors.lesson_item("r1", "S2", "Mount the router with the prefix its screen calls", "routers"),
            vectors.lesson_item("r2", "S3", "Give NOT NULL columns a DEFAULT so seed rows survive", "init.sql"),
        ])
        expect("lessons are embedded and stored", n == 3)
        hits = await vectors.search("lessons", "the screen reads a table with no seed rows in init.sql", limit=2)
        expect("the lesson that applies comes back first", bool(hits) and "Seed every table" in hits[0]["lesson"], str(hits)[:200])
        counts = await vectors.counts()
        expect("counts report the collection", counts.get("lessons") == 3)
        merged = _merge([{"component_id": "a", "component": "A"}],
                        [{"component_id": "a"}, {"component_id": "b", "component": "B", "score": 0.7}])
        expect("hybrid merge keeps graph hits first and adds semantic ones once",
               [m["component_id"] for m in merged] == ["a", "b"] and merged[1].get("via") == "semantic")
        expect("search terms are normalised for Lucene",
               normalise_terms(["session_storage", "PdfParsing"]) == ["session storage", "pdf parsing"])
    finally:
        vectors.embed = real_embed  # type: ignore[assignment]
        vectors.use_client(None)


async def test_failures() -> None:
    print("\n[6b] failure distillation and coaching")
    from .workspace import failures
    raw = (
        "WARNING: Running pip as the 'root' user can result in broken permissions\n"
        "/usr/local/lib/python3.12/site-packages/starlette/routing.py:73: in app\n"
        "    response = await f(request)\n"
        "backend/app/routers/shifts.py:20: in start_shift\n"
        "    return shift\n"
        "E   fastapi.exceptions.ResponseValidationError: 1 validation errors:\n"
        "E     {'type': 'missing', 'loc': ('response', 'agent_name'), 'msg': 'Field required'}\n"
        "=============================== warnings summary ===============================\n"
        "  DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated\n"
        "FAILED tests/test_s1.py::test_start_shift - fastapi.exceptions.ResponseValidationError\n"
        "1 failed, 10 passed, 1 warning in 0.38s\n"
    )
    d = failures.distill(raw)
    expect("framework frames and pip noise are removed", "site-packages" not in d and "pip as the 'root'" not in d
           and "DeprecationWarning" not in d)
    expect("the application's own frame, the E lines and the summary survive",
           "backend/app/routers/shifts.py:20" in d and "'agent_name'" in d and "1 failed, 10 passed" in d)
    hint = failures.coach(raw)
    expect("a missing response field gets a named, actionable hint", "`agent_name`" in hint and "response schema" in hint)
    expect("a NameError names the symbol", "`Depends`" in failures.coach("E   NameError: name 'Depends' is not defined"))
    expect("clean output gets no coaching", failures.coach("3 passed in 0.2s") == "")
    reworded = failures.for_developer(
        "tests/test_x.py::test_a expects status [201] from POST /api/tickets/import-csv, which the "
        "route declares as [200]. Assert the status the contract states.")
    expect("a status drift is reworded as the route change the Developer can make",
           "status_code=201" in reworded and "Assert the status" not in reworded, reworded)
    expect("a JavaScript syntax error gets a hint",
           "closing `)`" in failures.coach("SyntaxError: missing ) after argument list"))
    expect("failed tests are listed by node id", failures.failed_tests(raw) == ["tests/test_s1.py::test_start_shift"])

    # A test importing a name the (protected) module does not define is caught wherever it sits.
    from .workspace import checks
    rid = _run_row("selftest imports")
    try:
        root = repo.init_workspace(rid)
        (root / "backend" / "app").mkdir(parents=True)
        (root / "backend" / "app" / "db.py").write_text("def get_session():\n    pass\n", encoding="utf-8")
        (root / "tests").mkdir()
        (root / "tests" / "test_q.py").write_text(
            "from app.db import get_session\n\n\ndef test_a(client):\n    from app.db import SessionLocal\n"
            "    assert client.get('/health').status_code == 200\n\n\n"
            "def test_b(client, db_session):\n    client.session.add(1)\n    db_session.commit()\n"
            "    assert client.post('/x', json={}).status_code == 201\n\n\n"
            "def test_c(client):\n    from app.db import Base, engine\n    with Session(engine) as s:\n"
            "        s.commit()\n", encoding="utf-8")
        (root / "db").mkdir()
        (root / "db" / "init.sql").write_text(
            "CREATE TABLE ticket (id INT, subject TEXT);\nINSERT INTO ticket (id, subject) VALUES (1, 'a'), (2, 'b');\n"
            "CREATE TABLE customer (id INT);\nINSERT INTO customer VALUES (1),(2),(3),(4),(5),(6);\n", encoding="utf-8")
        story = {"id": "S9", "acceptance_criteria": [
            "Given I open the app, when the dashboard loads, then I see at least 150 tickets and 5 customers.",
            "Given a story, then it has at least 2 acceptance criteria and at least 3 columns."]}
        seed = checks.criteria_seed_issues(rid, story)
        expect("a criterion promising at least N rows is checked against init.sql",
               len(seed) == 1 and "150 tickets" in seed[0] and "2 row(s)" in seed[0], str(seed)[:300])
        expect("counts that are met, small numbers and non-data nouns are ignored",
               not any("into `customer`" in i or "into `criteria`" in i or "into `columns`" in i for i in seed))
        merged, lost = checks.merge_requirements(
            "fastapi==0.115.6\npsycopg[binary]==3.2.3\n", "fastapi\npsycopg2-binary\nalembic\n")
        expect("a rewritten requirements.txt keeps the scaffold's pinned driver and the story's additions",
               lost == ["psycopg"] and "psycopg[binary]==3.2.3" in merged and "alembic" in merged
               and "psycopg2-binary" in merged and merged.count("fastapi") == 1, merged)
        (root / "frontend" / "screens").mkdir(parents=True)
        (root / "frontend" / "screens" / "example.js").write_text("export default {title:'x', render(){}}", encoding="utf-8")
        (root / "frontend" / "screens" / "things.js").write_text("export default {title:'t', story:'S1', render(){}}", encoding="utf-8")
        checks.regenerate_registry(rid)
        reg = (root / "frontend" / "screens" / "index.js").read_text(encoding="utf-8")
        expect("git history of a file is readable", isinstance(repo.history(rid, "db/init.sql"), list))
        expect("the screen registry loads each screen on its own and records a failure instead of raising",
               'import("./things.js")' in reg and "catch (err)" in reg and "import s0" not in reg
               and "example.js" not in reg)
        (root / "backend" / "app" / "models.py").write_text(
            "from sqlalchemy import Integer, String\nfrom sqlalchemy.orm import Mapped, mapped_column\n\n"
            "class Ticket:\n    id: Mapped[int] = mapped_column(Integer, primary_key=True)\n"
            "    title: Mapped[str] = mapped_column(String(200))\n"
            "    product_area: Mapped[str] = mapped_column(String(40))\n"
            "    status: Mapped[str] = mapped_column(String(20), default='Open')\n"
            "    note: Mapped[str | None] = mapped_column(String(200), nullable=True)\n", encoding="utf-8")
        (root / "tests" / "test_order.py").write_text(
            "def test_f(client):\n    agents = client.get('/api/agents').json()\n"
            "    assert len(agents) > 0\n    agent_id = agents[0]['id']\n"
            "    client.post('/api/shift/start', json={'agent_id': agent_id})\n\n\n"
            "def test_g(client):\n    client.post('/api/agents', json={'name': 'a'})\n"
            "    agents = client.get('/api/agents').json()\n    assert len(agents) > 0\n", encoding="utf-8")
        (root / "backend" / "app" / "routers").mkdir(parents=True, exist_ok=True)
        (root / "backend" / "app" / "routers" / "imports.py").write_text(
            "from fastapi import APIRouter\nrouter = APIRouter()\n\n\n@router.post('/tickets/import-csv')\n"
            "def import_csv():\n    return []\n", encoding="utf-8")
        (root / "backend" / "app" / "routers" / "queue.py").write_text(
            "from fastapi import APIRouter\nrouter = APIRouter()\n\n\n@router.get('/triage-queue')\n"
            "def queue():\n    return []\n", encoding="utf-8")
        (root / "tests" / "test_foreign.py").write_text(
            "def test_h(client):\n    client.post('/api/tickets/import-csv', files={'f': ('a.csv', b'x')})\n"
            "    assert client.get('/api/triage-queue').status_code == 200\n", encoding="utf-8")
        foreign = checks.test_issues(rid, ["tests/test_foreign.py"], {"backend/app/routers/queue.py"})
        expect("a test that creates data through another story's endpoint is caught",
               any("test_foreign.py::test_h" in i and "belongs to another story" in i for i in foreign), str(foreign)[:300])
        expect("the same test passes when the route is the story's own",
               not any("belongs to another story" in i for i in
                       checks.test_issues(rid, ["tests/test_foreign.py"], {"backend/app/routers/imports.py"})))
        from .workspace.interface import own_routes_note
        note = own_routes_note(rid, {"backend/app/routers/queue.py"})
        expect("the Tester is shown the story's own routes", "GET /api/triage-queue" in note and "import-csv" not in note, note)
        (root / "tests" / "test_seeded.py").write_text(
            "def test_i(client):\n    customers = client.get('/api/customers').json()\n"
            "    assert len(customers) > 0\n", encoding="utf-8")
        seeded_ok = checks.test_issues(rid, ["tests/test_seeded.py"])
        expect("a non-empty assertion on a table init.sql seeds is not flagged",
               not any("non-empty" in i for i in seeded_ok), str(seeded_ok)[:300])
        from .workspace.interface import seeded_note
        expect("the Tester is told what the test database starts with",
               "customer (6 rows)" in seeded_note(rid) and "ticket (2 rows)" in seeded_note(rid), seeded_note(rid))
        order = checks.test_issues(rid, ["tests/test_order.py"])
        expect("a POST after the non-empty assertion does not count as seeding",
               any("test_order.py::test_f" in i and "non-empty" in i for i in order), str(order)[:300])
        expect("a POST before it does", not any("test_g" in i and "non-empty" in i for i in order), str(order)[:300])
        (root / "tests" / "test_seed.py").write_text(
            "from app.models import Ticket\n\n\ndef test_d(client, db_session):\n"
            "    db_session.add(Ticket(title='x', status='Open'))\n    db_session.commit()\n\n\n"
            "def test_e(client, db_session):\n    db_session.add(Ticket(title='x', product_area='Billing'))\n"
            "    db_session.commit()\n", encoding="utf-8")
        req = checks.required_columns(rid)
        expect("required columns are read from the models (no defaults, not nullable, not the key)",
               req.get("Ticket") == {"title", "product_area"}, str(req))
        seeds = checks.test_issues(rid, ["tests/test_seed.py"])
        expect("a test seeding a row without a required column is caught",
               any("test_seed.py::test_d" in i and "`product_area`" in i for i in seeds), str(seeds)[:300])
        expect("a complete seed passes", not any("test_e" in i for i in seeds), str(seeds)[:300])
        found = checks.test_issues(rid, ["tests/test_q.py"])
        expect("an invented import inside a test function is caught and attributed to the test",
               any("test_q.py::test_a" in i and "SessionLocal" in i and "get_session" in i for i in found), str(found)[:300])
        expect("a real import passes", not any("get_session` from" in i for i in found))
        expect("a test reaching for client.session is caught and told about db_session",
               any("test_q.py::test_b" in i and "client.session" in i and "db_session" in i for i in found), str(found)[:300])
        expect("client.get and client.post are not flagged", not any("client.get" in i or "client.post" in i for i in found))
        from .graph.nodes.build import _failing_test_source
        shown = _failing_test_source(rid, "FAILED tests/test_q.py::test_b - AttributeError\n1 failed")
        expect("a failing test's source is shown to the Developer verbatim",
               "def test_b(client, db_session):" in shown and "def test_a" not in shown, shown[:200])
        expect("a test that builds its own Session from app.db.engine is caught",
               any("test_q.py::test_c" in i and "own database session" in i for i in found), str(found)[-300:])
        expect("...and the coach explains the resulting error",
               "engine()" in failures.coach("E   AttributeError: '_lru_cache_wrapper' object has no attribute 'connect'"))
    finally:
        repo.destroy(rid)
        _drop_runs([rid])


async def test_foundation() -> None:
    print("\n[6c] demonstration data and the generic data API")
    from .workspace import seeding
    from .workspace.interface import declared_routes, generic_routes, plural, route_contract
    from .workspace import checks
    tables = {"agent": {"id": False, "name": True, "team": False},
              "ticket": {"id": False, "subject": True, "agent_id": False, "created_at": False}}
    rows = {
        "agent": [{"name": "Priya Nair", "team": "Billing"}, {"name": "Tom O'Neil", "team": None}],
        "ticket": [{"subject": f"Charged twice for invoice INV-{i}", "agent_id": 1 + i % 2,
                    "created_at": f"2024-03-{1 + i % 20:02d}T09:00:00+00:00"} for i in range(40)],
    }
    sql, issues = seeding.rows_to_sql(rows, tables)
    expect("rows become INSERT statements with quotes escaped and NULLs",
           "INSERT INTO agent (name, team) VALUES" in sql and "'Tom O''Neil', NULL" in sql and not issues, str(issues))
    expect("every row is counted the way the platform counts seed rows",
           checks._seed_rows(checks._inserts_by_table(sql)["ticket"]) == 40)
    _, issues = seeding.rows_to_sql({"ticket": [{"subject": "x", "colour": "red"}], "nothing": []}, tables)
    expect("an unknown column and an unknown table are reported",
           any("colour" in i for i in issues) and any("`nothing`" in i for i in issues), str(issues))
    _, issues = seeding.rows_to_sql({"agent": [{"id": 5, "name": "A"}]}, tables)
    expect("explicit ids that are not 1..N are refused", any("leave `id` out" in i for i in issues), str(issues))
    _, issues = seeding.rows_to_sql({"agent": [{"team": "Billing"}]}, tables)
    expect("a NOT NULL column never filled is reported", any("name" in i and "never filled" in i for i in issues), str(issues))
    dull = {"ticket": [{"subject": "Payment failed for order", "created_at": "2024-03-01"} for _ in range(30)]}
    q = seeding.quality_issues(dull, ["Given the app, when opened, then I see at least 150 tickets"])
    expect("repetitive text is flagged", any("distinct" in i for i in q), str(q))
    expect("rows all on one day are flagged", any("distinct day" in i for i in q), str(q))
    expect("a criterion's minimum count is checked", any("at least 150 tickets" in i for i in q), str(q))
    expect("varied data passes", seeding.quality_issues(rows, ["at least 25 tickets"]) == [],
           str(seeding.quality_issues(rows, ["at least 25 tickets"])))
    bad = "SUBJECTS = [\n    ('Charged twice', 'The customer's card was charged twice'),\n]\n"
    expect("an apostrophe in a single-quoted string is named with its line and the fix",
           "line 2" in seeding.syntax_issue(bad) and "double" in seeding.syntax_issue(bad), seeding.syntax_issue(bad))
    expect("a script that parses has no syntax issue", seeding.syntax_issue("def rows():\n    return {}\n") == "")
    from .workspace import seedspec
    spec = {"tables": [
        {"table": "agent", "count": 5, "columns": {"name": {"kind": "person_name"}}},
        {"table": "customer", "count": 25, "columns": {"name": {"kind": "company_name"},
                                                       "plan": {"kind": "choices", "choices": {"Free": 5, "Business": 3, "Enterprise": 2}}}},
        {"table": "ticket", "count": 150,
         "records": [{"subject": f"Subject number {i} about a real problem", "body": f"Body {i} with two sentences. Really.",
                      "product_line": ["Billing", "Mobile App", "Integrations"][i % 3]} for i in range(36)],
         "columns": {"customer_id": {"kind": "ref", "table": "customer"},
                     "customer_name": {"kind": "lookup", "via": "customer_id", "field": "name"},
                     "status": {"kind": "choices", "choices": {"open": 4, "triaged": 5, "resolved": 3}},
                     "priority": {"kind": "choices", "choices": {"P1": 1, "P2": 3, "P3": 5, "P4": 2}},
                     "arrival_time": {"kind": "time", "days_back": 30},
                     "triaged_at": {"kind": "time", "after": "arrival_time", "hours_min": 0.2, "hours_max": 8,
                                    "only_when": {"column": "status", "in": ["triaged", "resolved"]}},
                     "assignee_id": {"kind": "ref", "table": "agent", "only_when": {"column": "status", "in": ["triaged", "resolved"]}},
                     "ref": {"kind": "sequence", "prefix": "TD-", "start": 1000}}},
    ]}
    spec_tables = {"agent": {"id": False, "name": True},
                   "customer": {"id": False, "name": True, "plan": True},
                   "ticket": {"id": False, "subject": True, "body": True, "product_line": True, "customer_id": True,
                              "customer_name": True, "status": False, "priority": True, "arrival_time": True,
                              "triaged_at": False, "assignee_id": False, "ref": False}}
    rows, issues, derived = seedspec.expand_spec(spec, spec_tables)
    expect("a spec expands into the requested rows", not issues and {t: len(r) for t, r in rows.items()} ==
           {"agent": 5, "customer": 25, "ticket": 150}, str(issues)[:300])
    t = rows.get("ticket") or [{}]
    expect("records are reused with generated columns and look-ups resolve",
           len({x["subject"] for x in t}) == 36 and all(x["customer_name"] == rows["customer"][x["customer_id"] - 1]["name"] for x in t))
    expect("only_when leaves untriaged tickets unassigned",
           all((x["assignee_id"] is None and x["triaged_at"] is None) for x in t if x["status"] == "open")
           and any(x["assignee_id"] is not None for x in t if x["status"] != "open"))
    expect("a timestamp after another comes after it",
           all(x["triaged_at"] > x["arrival_time"] for x in t if x["triaged_at"]))
    expect("a sequence counts up", t[0]["ref"] == "TD-1000" and t[1]["ref"] == "TD-1001")
    named, _, _ = seedspec.expand_spec({"tables": [{"table": "agent", "count": 5, "columns": {
        "name": {"kind": "catalogue", "values": ["Ana", "Ben", "Cyd", "Dee", "Eli"]}}}]}, spec_tables)
    expect("a catalogue as long as the table gives one value each",
           [a["name"] for a in named["agent"]] == ["Ana", "Ben", "Cyd", "Dee", "Eli"])
    stamped_tables = {**spec_tables, "ticket": {**spec_tables["ticket"], "created_at": False, "updated_at": False}}
    st_rows, _, _ = seedspec.expand_spec(spec, stamped_tables)
    expect("created_at follows the row's earliest timestamp when the spec leaves it out",
           all(x["created_at"] == x["arrival_time"] for x in st_rows["ticket"])
           and all(x["updated_at"] == max(v for v in (x["arrival_time"], x.get("triaged_at")) if v) for x in st_rows["ticket"]))
    expect("the expanded rows pass the seed quality checks",
           seeding.quality_issues(rows, ["at least 150 tickets", "about 25 named customers"], spec_tables, derived) == [],
           str(seeding.quality_issues(rows, ["at least 150 tickets"], spec_tables, derived))[:300])
    _, bad_issues, _ = seedspec.expand_spec({"tables": [{"table": "ticket", "count": 3, "columns": {"colour": {"kind": "const", "value": 1}}}]}, spec_tables)
    expect("an unknown column and an uncovered NOT NULL column are reported",
           any("colour" in i for i in bad_issues) and any("subject" in i and "NOT NULL" in i for i in bad_issues), str(bad_issues)[:300])
    selfref, selfref_issues, _ = seedspec.expand_spec({"tables": [{"table": "ticket", "count": 8, "columns": {
        "subject": {"kind": "catalogue", "values": [f"s{i}" for i in range(8)]},
        "original_ticket_id": {"kind": "ref", "table": "ticket"}}}]},
        {"ticket": {"subject": True, "original_ticket_id": False}})
    ids = [r["original_ticket_id"] for r in selfref["ticket"]]
    expect("a table that refers to itself points at its own earlier rows (the first at none)",
           not selfref_issues and ids[0] is None and all(v is None or 1 <= v <= i for i, v in enumerate(ids)),
           f"{selfref_issues} {ids}")
    expect("the reply schema constrains the table names and kinds",
           seedspec.spec_schema(["ticket"])["properties"]["tables"]["items"]["properties"]["table"]["enum"] == ["ticket"])
    volume = "Data set | Volume | Characteristics\nEmployees | at least 120 | 6 departments\nLicence seats | at least 400 | x"
    q2 = seeding.quality_issues({"employee": [{"name": f"P{i}"} for i in range(25)],
                                 "license_seat": [{"x": 1}] * 10}, [volume])
    expect("a BRD volume table is enforced as a minimum count",
           any("120" in i and "`employee`" in i for i in q2) and any("400" in i and "`license_seat`" in i for i in q2), str(q2)[:300])
    dated, _, _ = seedspec.expand_spec({"tables": [{"table": "ticket", "count": 3,
        "records": [{"subject": "s", "body": "b", "product_line": "x", "customer_id": 1, "customer_name": "c",
                     "priority": "P3", "arrival_time": "2025-01-01T00:00:00+00:00"}],
        "columns": {"triaged_at": {"kind": "time", "after": "arrival_time", "days_min": 1095, "days_max": 1095},
                    "status": {"kind": "time", "after": "missing_col", "days_back": 5}}}]}, spec_tables)
    expect("days_min/days_max offset a date, and an anchor nothing fills falls back to the window",
           dated["ticket"][0]["triaged_at"].startswith("2028-01-01") and dated["ticket"][0]["status"] is not None)
    hist = {"assignment_history": [{"employee_id": 1 + i % 5, "note": f"Checked out laptop number {i} to staff"} for i in range(30)]}
    expect("a history table's reference is not required to be empty on some rows",
           not any("assignment_history.employee_id" in i for i in seeding.quality_issues(
               hist, [], {"assignment_history": {"employee_id": False, "note": False}})))
    models, estate_issues, _ = seedspec.expand_spec({"tables": [{"table": "agent", "count": 320,
        "records": [{"name": m} for m in ["Dell Latitude 5440", "ThinkPad T14", "MacBook Pro 14", "iPhone 15"]],
        "columns": {}}]}, spec_tables)
    expect("a short catalogue of models reused over many rows is not called copies",
           not any("copies" in i for i in estate_issues) and len(models["agent"]) == 320, str(estate_issues)[:200])
    titles = {"agent": [{"name": ["Senior Accountant", "Warehouse Supervisor", "IT Technician"][i % 3]} for i in range(60)]}
    expect("short categorical text (job titles) may repeat", seeding.quality_issues(titles, []) == [],
           str(seeding.quality_issues(titles, []))[:200])
    gappy = {"employee": [{"full_name": "Ines Costa", "email": None}, {"full_name": "Kwame Mensah", "email": "k@x.io"}]}
    notes = seeding.fill_required(gappy, {"employee": {"id": False, "full_name": True, "email": True}})
    expect("a last-attempt data set gets its required gaps filled",
           gappy["employee"][0]["email"] == "ines.costa@example.com" and gappy["employee"][1]["email"] == "k@x.io"
           and notes == ["employee.email: filled 1 empty required value(s)"], str(notes))
    from .agents.base import DEVELOPER as _DEV
    expect("the Developer reads the UX playbook after its own instructions",
           "UX PLAYBOOK" in _DEV.system and _DEV.system.index("You are the Developer") < _DEV.system.index("UX PLAYBOOK"))
    banned = [pat for pat, _ in checks._BANNED if "alert|confirm|prompt" in pat.pattern][0]
    expect("ui.confirm() is allowed and a bare confirm() is not",
           not banned.search("await ui.confirm('Delete?')") and banned.search("if (confirm('Delete?'))")
           and banned.search("window.confirm('x')"))
    expect("plural mirrors the generic router",
           (plural("ticket"), plural("incident_audit_entry"), plural("status"), plural("agents")) ==
           ("tickets", "incident-audit-entries", "status", "agents"))

    rid = _run_row("selftest foundation")
    try:
        root = repo.init_workspace(rid)
        (root / "backend" / "app" / "routers").mkdir(parents=True)
        (root / "backend" / "app" / "routers" / "resources.py").write_text("router = None\n", encoding="utf-8")
        (root / "backend" / "app" / "models.py").write_text(
            "class Ticket(Base):\n    __tablename__ = 'ticket'\n    id: Mapped[int]\n    subject: Mapped[str]\n\n"
            "class Incident(Base):\n    __tablename__ = 'incident'\n    id: Mapped[int]\n", encoding="utf-8")
        (root / "db").mkdir()
        (root / "db" / "init.sql").write_text(
            "CREATE TABLE IF NOT EXISTS ticket (id SERIAL PRIMARY KEY, subject VARCHAR(200) NOT NULL);\n"
            "CREATE TABLE IF NOT EXISTS incident (id SERIAL PRIMARY KEY);\n", encoding="utf-8")
        g = generic_routes(rid)
        expect("the generic API's routes are derived from models.py",
               {(r["method"], r["path"]) for r in g} >= {("GET", "/api/tickets"), ("PATCH", "/api/tickets/{item_id}"),
                                                          ("POST", "/api/incidents"), ("GET", "/api/resources")})
        expect("they are part of the verified routes", any(r["path"] == "/api/tickets" for r in declared_routes(rid)))
        contract = route_contract(rid)
        expect("the Developer is told the generic API and the row shape",
               "THE GENERIC DATA API" in contract and "/api/tickets   row shape {id, subject}" in contract, contract[:400])
        seeding.write_seed_section(rid, "INSERT INTO ticket (subject) VALUES\n  ('a');\n")
        seeding.write_seed_section(rid, "INSERT INTO ticket (subject) VALUES\n  ('b'),\n  ('c');\n")
        text = (root / "db" / "init.sql").read_text(encoding="utf-8")
        expect("the seed section is rewritten, not appended twice",
               text.count(seeding.SEED_MARKER) == 1 and "('a')" not in text and "('c')" in text)
        expect("the tables are read without the seed section", set(seeding.tables_in(rid)) == {"ticket", "incident"})
        (root / "frontend" / "screens").mkdir(parents=True)
        (root / "frontend" / "screens" / "tickets.js").write_text(
            "export default { title: 'Tickets', story: 'S1', async render(root, { api, ui }) {"
            " const rows = await api('/tickets?sort=-id'); root.append(ui.table({ rows, columns: [] })); } };\n",
            encoding="utf-8")
        static = checks.static_issues(rid, "S1", True, set())
        expect("a screen calling the generic API passes the route check",
               not any("does not serve" in i for i in static), str(static)[:300])
        (root / "frontend" / "screens" / "leavers.js").write_text(
            "export default { title: 'Leavers', story: 'S1', async render(root, { api, ui }) {"
            " const rows = await api('/tickets?status=leaver&sort=-id'); root.append(ui.table({ rows, columns: [] })); } };\n",
            encoding="utf-8")
        static = checks.static_issues(rid, "S1", True, set())
        expect("a generic-API filter on a column the table lacks is caught",
               any("leavers.js" in i and "status" in i and "422" in i for i in static), str(static)[:300])
        (root / "frontend" / "screens" / "leavers.js").unlink()
        (root / "frontend" / "screens" / "ticket_detail.js").write_text(
            "export default { title: 'Ticket', story: 'S1', async render(root, { api, h, params, ui }) {"
            " const id = params[0]; if (!id) { root.append(ui.empty('No ticket selected')); return; }"
            " const t = await api(`/tickets/${id}`); root.append(h('p', {}, t.subject)); } };\n", encoding="utf-8")
        (root / "frontend" / "screens" / "ticket_detail.js").write_text(
            "export default { title: 'Ticket', story: 'S1', async render(root, { api, h, params, ui }) {"
            " let id = params && params[0]; if (!id) { const m = location.hash.match(/x/); if (m) { id = m[1]; } }"
            " if (!id) { root.append(h('div', { class: 'panel' }, h('strong', {}, 'No ticket selected'))); return; }"
            " const t = await api(`/tickets/${id}`); root.append(h('p', {}, t.subject)); } };\n", encoding="utf-8")
        static = checks.static_issues(rid, "S1", True, set())
        expect("a guard whose empty state is built with nested h() props is still caught",
               any("ticket_detail.js" in i and "opened without an id" in i for i in static), str(static)[:300])
        (root / "frontend" / "screens" / "ticket_detail.js").write_text(
            "export default { title: 'Ticket', story: 'S1', async render(root, { api, h, params, ui }) {"
            " const id = params[0]; if (!id) { root.append(ui.empty('No ticket selected')); return; }"
            " const t = await api(`/tickets/${id}`); root.append(h('p', {}, t.subject)); } };\n", encoding="utf-8")
        (root / "frontend" / "screens" / "ticket_detail.js").write_text(
            "export default { title: 'Ticket', story: 'S1', async render(root, { api, h, params, ui }) {"
            " if (!params || params.length === 0) { root.append(ui.empty('No ticket selected')); return; }"
            " const t = await api(`/tickets/${params[0]}`); root.append(h('p', {}, t.subject)); } };\n", encoding="utf-8")
        static = checks.static_issues(rid, "S1", True, set())
        expect("a `!params || params.length === 0` guard is caught too",
               any("ticket_detail.js" in i and "opened without an id" in i for i in static), str(static)[:300])
        (root / "frontend" / "screens" / "ticket_detail.js").write_text(
            "export default { title: 'Ticket', story: 'S1', async render(root, { api, h, params, ui }) {"
            " const id = params[0]; if (!id) { root.append(ui.empty('No ticket selected')); return; }"
            " const t = await api(`/tickets/${id}`); root.append(h('p', {}, t.subject)); } };\n", encoding="utf-8")
        static = checks.static_issues(rid, "S1", True, set())
        expect("a screen that gives up without an id is caught before deploy",
               any("ticket_detail.js" in i and "opened without an id" in i for i in static), str(static)[:300])
        (root / "frontend" / "screens" / "ticket_detail.js").write_text(
            "export default { title: 'Ticket', story: 'S1', async render(root, { api, h, params, ui }) {"
            " const id = params[0]; if (!id) { const rows = await api('/tickets'); root.append(ui.table({ rows, columns: [] })); return; }"
            " const t = await api(`/tickets/${id}`); root.append(h('p', {}, t.subject)); } };\n", encoding="utf-8")
        static = checks.static_issues(rid, "S1", True, set())
        expect("one that shows the list instead is fine",
               not any("opened without an id" in i for i in static), str(static)[:300])
        (root / "frontend" / "screens" / "status.js").write_text(
            "export default { title: 'Status', story: 'S1', async render(root, { api, h, ui }) {"
            " const id = params[0]; const rows = await api('/incidents'); root.append(ui.table({ rows, columns: [] }));"
            " if (id) navigate('#/x'); } };\n", encoding="utf-8")
        static = checks.static_issues(rid, "S1", True, set())
        expect("a screen using params and navigate without receiving them is caught",
               any("status.js" in i and "`params`" in i and "`navigate`" in i for i in static), str(static)[:300])
        (root / "backend" / "app" / "routers" / "broken.py").write_text(
            "from fastapi import Depends\n\n\n@router.get('/broken')\ndef broken():\n    return []\n", encoding="utf-8")
        static = checks.static_issues(rid, "S1", True, {"backend/app/routers/broken.py"})
        expect("a router file that never creates its router is caught statically",
               any("broken.py" in i and "never creates the router" in i for i in static), str(static)[:300])
        expect("an import failure is attributed to the file the traceback names",
               list(checks.smoke_failures_by_file(rid, [{"path": "(import)", "status": 500, "file": "backend/app/routers/broken.py"}]))
               == ["backend/app/routers/broken.py"])
        (root / "backend" / "app" / "routers" / "incidents.py").write_text(
            "from fastapi import APIRouter\nrouter = APIRouter()\n\n\n@router.get('/tickets')\ndef mine():\n    return []\n",
            encoding="utf-8")
        expect("a story router that shadows a generic path owns its failure",
               list(checks.smoke_failures_by_file(rid, [{"path": "/api/tickets", "status": 500}])) == ["backend/app/routers/incidents.py"])
        (root / "backend" / "app" / "routers" / "incidents.py").unlink()
        (root / "backend" / "app" / "routers" / "stray.py").write_text(
            "from fastapi import APIRouter\nrouter = APIRouter()\n\n\n@router.get('/strays')\ndef ok():\n    return []\n\n\n"
            "@router.get('/{stray_id}')\ndef one(stray_id: int):\n    return {}\n", encoding="utf-8")
        notes = checks.neutralise_bare_routes(rid, ["backend/app/routers/stray.py"])
        after = (root / "backend" / "app" / "routers" / "stray.py").read_text(encoding="utf-8")
        expect("a stray root route loses its decorator and the proper route stays",
               len(notes) == 1 and "/{stray_id}" in notes[0] and "@router.get('/strays')" in after
               and "@router.get('/{stray_id}')" not in after and "def one(" in after, str(notes)[:200])
        expect("the smoke failures map to the router that serves the path",
               list(checks.smoke_failures_by_file(rid, [{"path": "/api/tickets", "status": 500}])) == ["backend/app/routers/resources.py"])
        (root / "backend" / "app" / "routers" / "metrics.py").write_text(
            "from fastapi import APIRouter\nfrom sqlalchemy import func\nrouter = APIRouter()\n\n\n"
            "@router.get('/metrics/dashboard')\ndef dashboard():\n    return {'open': 1}\n", encoding="utf-8")
        (root / "frontend" / "screens" / "dashboard.js").write_text(
            "export default { title: 'Dashboard', story: 'S2', async render(root, { api }) {"
            " root.append(JSON.stringify(await api('/metrics/dashboard'))); } };\n", encoding="utf-8")
        rewrite = ("from fastapi import APIRouter\nrouter = APIRouter()\n\n\n"
                   "@router.get('/metrics/weekly')\ndef weekly():\n    return []\n")
        kept, notes = checks.preserve_routes(rid, {"backend/app/routers/metrics.py": rewrite})
        merged = kept["backend/app/routers/metrics.py"]
        expect("a router rewrite keeps the endpoint another screen calls",
               "/metrics/dashboard" in merged and "/metrics/weekly" in merged and "from sqlalchemy import func" in merged
               and any("GET /metrics/dashboard" in n for n in notes), str(notes)[:300])
        kept2, notes2 = checks.preserve_routes(rid, {"backend/app/routers/metrics.py": rewrite,
                                                     "frontend/screens/dashboard.js": "export default {}"})
        expect("a route only the rewriting story's own screen called is not forced back",
               kept2["backend/app/routers/metrics.py"] == rewrite and not notes2, str(notes2))
        original = (root / "backend" / "app" / "routers" / "metrics.py").read_text(encoding="utf-8")
        kept3, notes3 = checks.preserve_routes(rid, {"backend/app/routers/metrics.py": ""})
        expect("another story cannot delete a router a screen still calls",
               kept3["backend/app/routers/metrics.py"] == original and any("not deleted" in n for n in notes3), str(notes3))
        kept4, _ = checks.preserve_routes(rid, {"backend/app/routers/metrics.py": "",
                                                "frontend/screens/dashboard.js": "export default {}"})
        expect("a story may still delete a router only its own screens called",
               kept4["backend/app/routers/metrics.py"] == "")
    finally:
        _drop_runs([rid])
        shutil.rmtree(repo.workspace_path(rid), ignore_errors=True)


async def test_codemap(tmp: Path) -> None:
    """The ArchiLens code map: pictures Mermaid can draw, from what the code says."""
    from .workspace import codemap
    if not codemap.available():
        expect("ArchiLens is installed in the image", False)
        return
    from archilens.models import FlowStep, ProcessFlow

    flow = ProcessFlow(id="flow:x", name="Resolve", trigger="POST /api/incidents/{id}/resolve", steps=[
        FlowStep(order=1, actor="Front-end (browser)", action="POST /resolve; id=3", target="Database (ticket table)"),
        FlowStep(order=2, actor="Database (ticket table)", action="rows <updated>", target="Front-end (browser)",
                 condition="if #tickets > 0"),
    ])
    seq = codemap._sequence(flow)
    participants = [line.split()[1] for line in seq.splitlines() if line.strip().startswith("participant")]
    expect("flow participants become ids Mermaid parses", all(p.replace("_", "").isalnum() for p in participants), seq)
    expect("flow messages open no activation that never closes", "->>+" not in seq and "->>" in seq)
    expect("flow labels lose characters that end a Mermaid statement", ";" not in seq and "#" not in seq and "<" not in seq)

    tables = {"agent": [], "customer": [], "ticket": []}
    expect("customer_id points at customer", codemap._implied_reference("customer_id", "ticket", tables) == "customer")
    expect("resolved_by_agent_id points at agent", codemap._implied_reference("resolved_by_agent_id", "ticket", tables) == "agent")
    expect("assignee_id names no table, so no link is invented", codemap._implied_reference("assignee_id", "ticket", tables) == "")

    root = tmp / "cm"
    (root / "db").mkdir(parents=True)
    (root / "frontend").mkdir()
    (root / "db" / "init.sql").write_text(
        "CREATE TABLE customer (id SERIAL PRIMARY KEY, name VARCHAR(80) NOT NULL);\n"
        "CREATE TABLE ticket (id SERIAL PRIMARY KEY, subject TEXT, customer_id INTEGER REFERENCES customer(id),"
        " owner_customer_id INTEGER);\n", encoding="utf-8")
    er = codemap._er_view(root)
    expect("the data model draws declared keys solid", "customer ||--o{ ticket" in er, er)
    expect("and *_id columns naming a table dashed", "customer ||..o{ ticket" in er, er)
    (root / "docker-compose.yml").write_text(
        "services:\n  db: {image: postgres}\n  backend:\n    environment:\n"
        "      DATABASE_URL: postgresql+psycopg://a:b@db:5432/app\n"
        "  data:\n    environment: {DATABASE_URL: 'postgresql+psycopg://a:b@db:5432/app'}\n"
        "  frontend:\n    ports: ['8081:80']\n", encoding="utf-8")
    (root / "frontend" / "nginx.conf").write_text(
        "set $api_upstream http://backend:8000;\nset $data_upstream http://data:8000;\n", encoding="utf-8")
    topo = codemap._topology(root, "T")
    expect("the topology starts at the visitor's browser", "visitor -->|HTTP| svc_frontend" in topo, topo)
    expect("the gateway routes /api to the api service", "svc_frontend -->|/api| svc_backend" in topo, topo)
    expect("and falls back to the data service", "svc_frontend -.->|fallback| svc_data" in topo, topo)
    expect("both Python services talk SQL to the database",
           "svc_backend ==>|SQL| svc_db" in topo and "svc_data ==>|SQL| svc_db" in topo, topo)


async def test_check_rules() -> None:
    """Checks that once flagged what no Developer could change (docs/CHECKS.md, 'When a check was wrong')."""
    import re
    from .workspace import checks, seeding

    own = 'async function confirm(id) { await api(`/review-queue/${id}/confirm`); }\nui.button("Confirm", { onclick: () => confirm(r.id) })'
    native = 'if (confirm("Delete this ticket?")) remove();'
    banned = checks._BANNED[0][0]
    for label, code, flagged in (("a screen's own confirm() is allowed", own, False),
                                 ("the browser's confirm() is still flagged", native, True)):
        hit = banned.search(code)
        expect(label, (bool(hit) and not checks._defines(code, hit.group(1))) == flagged)

    missing = {"status": 422, "detail": json.dumps({"detail": [
        {"type": "missing", "loc": ["query", "subject"], "msg": "Field required"},
        {"type": "missing", "loc": ["query", "product_area"], "msg": "Field required"}]})}
    stray = {"status": 422, "detail": json.dumps({"detail": [{"type": "int_parsing", "loc": ["path", "item_id"]}]})}
    expect("a GET that only lacks query parameters needs input, not a fix", checks._needs_query(missing))
    expect("a 422 from a stray root route is still a failure", not checks._needs_query(stray))
    expect("a 500 is never excused", not checks._needs_query({"status": 500, "detail": "boom"}))

    def lopsided(split: tuple[int, int, int]) -> bool:
        values = ["Residential"] * split[0] + ["Business"] * split[1] + ["Wholesale"] * split[2]
        rows = [{"id": i, "segment": v} for i, v in enumerate(values)]
        return any(re.search(r"customer\.segment:.*share one value", x) for x in seeding.quality_issues({"customer": rows}, []))
    expect("a two-value column may split 80/20 (48 Residential, 12 Business)", not lopsided((48, 12, 0)))
    expect("a two-value column split 95/5 is still lopsided", lopsided((57, 3, 0)))
    expect("a three-value column over 80% one value is still lopsided", lopsided((51, 5, 4)))
    expect("a query string built elsewhere and appended is not part of the path",
           checks._normalise("/api/audit-entries${params}") == "/api/audit-entries"
           and checks._normalise("/tickets/${id}/duplicates") == "/api/tickets/x/duplicates"
           and checks._normalise("/tickets/${id}") == "/api/tickets/x", checks._normalise("/api/audit-entries${params}"))


async def test_plane() -> None:
    """The Plane mirror's pure parts: keys that never collide, safe HTML, sane priorities."""
    from .integrations import plane
    a = plane._identifier("a3a2dd874dcb4106", "AssetHub")
    b = plane._identifier("a3a282a6f4824f73", "AssetHub")
    expect("two runs whose ids share four characters get different Plane keys", a != b, f"{a} {b}")
    expect("a Plane key is upper-case letters and digits, at most 12", all(
        k.isalnum() and k.isupper() and len(k) <= 12
        for k in (a, plane._identifier("7fdad83a77e0490b", "Triage Desk & Co. (v2)"))))
    expect("story value maps to Plane priority",
           [plane._priority({"value": v}) for v in (9, 7, 5, 2)] == ["urgent", "high", "medium", "low"]
           and plane._priority({}) == "medium")
    html = plane._story_html("r1", {"id": "S1", "narrative": "<script>x</script>",
                                    "acceptance_criteria": ["Given <b> when & then"], "estimate": 3})
    expect("story text is escaped before it becomes Plane HTML",
           "<script>" not in html and "&lt;script&gt;" in html and "&amp;" in html)
    expect("acceptance criteria become a list", "<h3>Acceptance criteria</h3><ul><li>" in html)
    expect("the Plane mirror is off without a token", not plane.configured())


async def test_api(rid: str) -> None:
    print("\n[7] observability API")
    from .main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
        expect("/health answers with the engine's state", r.status_code == 200 and "engine" in r.json())
        r = await c.get("/metrics")
        expect("/metrics serves Prometheus text", r.status_code == 200 and "poiesis_runs" in r.text)
        r = await c.get(f"/api/runs/{rid}/traces")
        body = r.json()
        expect("a run's traces list its calls and spans", r.status_code == 200 and body["calls"] and body["spans"])
        call_id = body["calls"][0]["id"]
        expect("the list leaves the prompt bodies out", "prompt" not in body["calls"][0] and body["calls"][0]["prompt_chars"] > 0)
        r = await c.get(f"/api/runs/{rid}/traces/{call_id}")
        expect("one call comes back with its prompt and reply", r.status_code == 200 and r.json()["prompt"].startswith("STORY"))
        r = await c.get(f"/api/runs/{rid}/usage")
        u = r.json()
        expect("usage adds up the run", r.status_code == 200 and u["calls"] >= 6 and "developer" in u["by_agent"] and u["stages"])
        r = await c.get(f"/api/runs/{rid}/integrations")
        expect("integrations report Jira and Git side by side", r.status_code == 200 and set(r.json()) == {"jira", "git"})
        r = await c.post(f"/api/runs/{rid}/cancel")
        expect("cancelling an idle run is a 409, not a crash", r.status_code == 409)


async def main() -> int:
    # Runs made here pass through the tracker hooks; keep them out of the real Plane.
    plane_token, settings().plane_api_token = settings().plane_api_token, ""
    fake = FakeOllama()
    tmp = Path(tempfile.mkdtemp(prefix="poiesis-core-"))
    rid = _run_row("selftest core")
    engine_ids = [_run_row(f"selftest engine {i}") for i in range(3)]
    git_id = _run_row("selftest git")
    try:
        await test_schemas()
        await test_requirements()
        await test_seed_loops()
        await test_llm_client(fake, rid)
        await test_tracing(rid)
        await test_engine(engine_ids)
        await test_gitremote(git_id, tmp)
        await test_vectors()
        await test_failures()
        await test_foundation()
        await test_codemap(tmp)
        await test_check_rules()
        await test_plane()
        await test_api(rid)
    finally:
        settings().plane_api_token = plane_token
        llm.use_transport(None)
        _drop_runs([rid, git_id, *engine_ids])
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
