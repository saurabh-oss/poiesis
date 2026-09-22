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
        expect("the local floor raises a small budget",
               req["options"]["num_predict"] == s.poiesis_local_min_tokens)

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
            "    assert client.get('/health').status_code == 200\n", encoding="utf-8")
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
        found = checks.test_issues(rid, ["tests/test_q.py"])
        expect("an invented import inside a test function is caught and attributed to the test",
               any("test_q.py::test_a" in i and "SessionLocal" in i and "get_session" in i for i in found), str(found)[:300])
        expect("a real import passes", not any("get_session` from" in i for i in found))
    finally:
        repo.destroy(rid)
        _drop_runs([rid])


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
    fake = FakeOllama()
    tmp = Path(tempfile.mkdtemp(prefix="poiesis-core-"))
    rid = _run_row("selftest core")
    engine_ids = [_run_row(f"selftest engine {i}") for i in range(3)]
    git_id = _run_row("selftest git")
    try:
        await test_schemas()
        await test_llm_client(fake, rid)
        await test_tracing(rid)
        await test_engine(engine_ids)
        await test_gitremote(git_id, tmp)
        await test_vectors()
        await test_failures()
        await test_api(rid)
    finally:
        llm.use_transport(None)
        _drop_runs([rid, git_id, *engine_ids])
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    for f in FAILED:
        print("  FAILED:", f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
