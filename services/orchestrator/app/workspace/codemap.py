"""Pictures of a generated codebase, drawn by ArchiLens.

ArchiLens (https://github.com/saurabh-oss/archilens) reads a repository with
tree-sitter and draws it at several zoom levels: modules and how they depend on
each other (L1), the classes inside one module (L2) and request flows (L3). On
its own it groups files by their top two folders, which turns a generated app
into three boxes with no arrows. Poiesis knows the shape exactly — every screen,
which endpoints it calls, which story each belongs to, which service runs what —
so it hands ArchiLens that shape and lets it do the analysis and the drawing.

ArchiLens's AI features (module summaries, request flows, pattern detection)
accept any client with `complete_with_tool`. Poiesis passes its own, backed by
the platform's local model through the same one-call-at-a-time gate as every
other agent, so no hosted model is ever called.

Two pictures ArchiLens has no input for are drawn here directly: the runtime
topology (from docker-compose.yml and the gateway's nginx.conf) and the data
model (from db/init.sql).

The result is one JSON document per run at .poiesis/codemap.json.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

import yaml

from .. import llm, telemetry
from ..db import Artifact, Run, session
from .checks import _API_CALL, _COMMENTS, _model_columns, _normalise, _route_pattern, stories_in, story_screens
from .interface import _schema_fields, _top_level, declared_routes, strip_sql_comments
from .repo import workspace_path

log = logging.getLogger("poiesis.codemap")

OUT = (".poiesis", "codemap.json")
ROUTERS = ("backend", "app", "routers")

# The platform's own files, grouped the way a reader thinks about them.
_PLATFORM_GROUPS: list[tuple[str, str, str, tuple[str, ...]]] = [
    # (module id, name, kind, files)
    ("module:frontend/shell", "App shell & UI kit", "shell",
     ("frontend/app.js", "frontend/ui.js", "frontend/index.html", "frontend/styles.css",
      "frontend/screens/index.js")),
    ("module:backend/core", "API service core", "core",
     ("backend/app/main.py", "backend/app/routes.py", "backend/app/db.py",
      "backend/app/routers/__init__.py")),
    ("module:backend/generic", "Generic data API", "generic",
     ("backend/app/routers/resources.py", "backend/app/data_main.py")),
    ("module:backend/model", "Data model", "model",
     ("backend/app/models.py", "backend/app/schemas.py")),
]
_EXAMPLE_FILES = {"frontend/screens/example.js", "backend/app/routers/examples.py"}

# Adobe Spectrum: one hue per kind of box, the same in every picture.
_KIND_STYLE = {
    "screen": "fill:#0265dc,stroke:#0054b6,color:#fff",
    "api": "fill:#4046ca,stroke:#3236a3,color:#fff",
    "generic": "fill:#7e84fa,stroke:#5c61d8,color:#fff",
    "core": "fill:#464646,stroke:#222,color:#fff",
    "shell": "fill:#6d6d6d,stroke:#464646,color:#fff",
    "model": "fill:#0fb5ae,stroke:#0a8f89,color:#fff",
    "db": "fill:#f68511,stroke:#c46a0d,color:#fff",
    "actor": "fill:#eb1000,stroke:#b30c00,color:#fff",
    "gateway": "fill:#222,stroke:#000,color:#fff",
}

_jobs: dict[str, asyncio.Task] = {}
_status: dict[str, dict[str, Any]] = {}


# ---- public ---------------------------------------------------------------------

def load(run_id: str) -> dict[str, Any] | None:
    path = workspace_path(run_id).joinpath(*OUT)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status(run_id: str) -> dict[str, Any]:
    job = _jobs.get(run_id)
    live = dict(_status.get(run_id) or {})
    live["running"] = bool(job and not job.done())
    return live


def schedule(run_id: str, *, ai: bool) -> None:
    """Draw the run's codebase in the background; a newer request replaces an older one."""
    old = _jobs.get(run_id)
    if old and not old.done():
        old.cancel()
    _jobs[run_id] = asyncio.create_task(_job(run_id, ai))


def ai_wanted() -> bool:
    from ..config import pack
    return bool(((pack() or {}).get("codemap") or {}).get("ai", False))


def available() -> bool:
    try:
        import archilens  # noqa: F401
        return True
    except ImportError:
        return False


# ---- the job --------------------------------------------------------------------

async def _job(run_id: str, ai: bool) -> None:
    _status[run_id] = {"stage": "reading the code", "error": ""}
    try:
        previous = load(run_id)
        doc = await asyncio.to_thread(_static, run_id)
        _write(run_id, doc)
        if not ai:
            _status[run_id] = {"stage": "done", "error": ""}
            return
        # The local model is shared with the build. Wait until the run is no
        # longer being driven, so these calls never slow a story down.
        from ..graph import engine
        while engine.is_busy(run_id):
            _status[run_id] = {"stage": "waiting for the run to go idle", "error": ""}
            await asyncio.sleep(20)
        doc["ai"] = {"status": "running", "model": llm.local_name(llm.model_for("fast"))}
        _write(run_id, doc)
        loop = asyncio.get_running_loop()
        await asyncio.to_thread(_explain, run_id, doc, loop, previous)
        doc["ai"]["status"] = "done"
        doc["ai"]["finished_at"] = _now()
        _write(run_id, doc)
        _status[run_id] = {"stage": "done", "error": ""}
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — a picture that fails must not fail anything else
        log.exception("code map for %s failed", run_id)
        _status[run_id] = {"stage": "failed", "error": f"{type(exc).__name__}: {exc}"[:500]}
        doc = load(run_id)
        if doc and (doc.get("ai") or {}).get("status") == "running":
            doc["ai"]["status"] = "failed"
            doc["ai"]["error"] = _status[run_id]["error"]
            _write(run_id, doc)


def _write(run_id: str, doc: dict[str, Any]) -> None:
    path = workspace_path(run_id).joinpath(*OUT)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, default=str), encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---- static analysis (ArchiLens + what Poiesis knows) ----------------------------

def _static(run_id: str) -> dict[str, Any]:
    from archilens.config import AnalysisConfig, ArchiLensConfig
    from archilens.engine import analyze_repository
    from archilens.models import ArchEdge, ArchNode, DiagramLevel, EdgeType, NodeType

    root = workspace_path(run_id)
    title, stories = _run_facts(run_id)
    routes = [r for r in declared_routes(run_id) if r.get("file") not in _EXAMPLE_FILES]
    screens = _screens(run_id, routes)
    routers = sorted(
        p.relative_to(root).as_posix() for p in root.joinpath(*ROUTERS).glob("*.py")
        if p.name not in {"__init__.py", "resources.py", "examples.py"}
    )

    config = ArchiLensConfig(
        project_name=title,
        project_type="microservices",
        analysis=AnalysisConfig(
            entry_points=[{"pattern": r, "type": "http_handler"} for r in routers],
            exclude=AnalysisConfig().exclude + [
                "**/.poiesis/**", ".poiesis/*", "tests/*", "**/tests/**", "conftest.py",
                "**/fonts/**", "db/*", *sorted(_EXAMPLE_FILES),
            ],
        ),
    )
    snapshot = analyze_repository(root, config, use_ai=False, git_ref=_git_ref(root))

    # Replace ArchiLens's folder-based modules with the app's real parts.
    loc = {f: _lines(root / f) for f in _all_files(root)}
    modules: list[dict[str, Any]] = []
    owner: dict[str, str] = {}

    for s in screens:
        mid = f"module:frontend/screens/{Path(s['file']).stem}"
        modules.append({"id": mid, "name": s["title"], "kind": "screen", "files": [s["file"]],
                        "stories": s["stories"], "subtitle": s["subtitle"], "calls": s["calls"]})
        owner[s["file"]] = mid
    for rel in routers:
        mid = f"module:backend/routers/{Path(rel).stem}"
        name = Path(rel).stem.replace("_", " ").title() + " API"
        modules.append({"id": mid, "name": name, "kind": "api", "files": [rel],
                        "endpoints": [f"{r['method']} {r['path']}" for r in routes if r.get("file") == rel]})
        owner[rel] = mid
    for mid, name, kind, files in _PLATFORM_GROUPS:
        present = [f for f in files if f in loc]
        if not present:
            continue
        mod = {"id": mid, "name": name, "kind": kind, "files": present}
        if kind == "generic":
            bases: dict[str, set[str]] = {}
            for r in routes:
                if r.get("file", "").endswith("resources.py"):
                    base = r["path"].split("/{")[0]
                    bases.setdefault(base, set()).add(r["method"])
            mod["endpoints"] = [f"{'/'.join(sorted(ms))} {b}" for b, ms in sorted(bases.items())]
        modules.append(mod)
        for f in present:
            owner[f] = mid
    tables = _tables(root)
    if tables:
        modules.append({"id": "module:db", "name": f"PostgreSQL · {len(tables)} tables", "kind": "db",
                        "files": ["db/init.sql"] if "db/init.sql" in loc else [],
                        "tables": sorted(tables)})

    for m in modules:
        m["loc"] = sum(loc.get(f, 0) for f in m["files"])

    # Stories become ArchiLens capabilities: a story's screen, and the routers only it calls.
    route_owner = {(r["method"], r["path"]): owner.get(r.get("file") or "", "module:backend/generic")
                   for r in routes}
    callers: dict[str, set[str]] = {}
    http: dict[tuple[str, str], list[str]] = {}
    for s in screens:
        src = owner[s["file"]]
        for call in s["calls"]:
            target = route_owner.get((call["method"], call["route"])) if call.get("route") else None
            if target:
                http.setdefault((src, target), []).append(f"{call['method']} {call['route']}")
                callers.setdefault(target, set()).add(src)
    by_id = {m["id"]: m for m in modules}
    capability_map: dict[str, list[str]] = {}
    for s in screens:
        for sid in s["stories"][:1]:
            label = f"{sid} " + re.sub(r"[^A-Za-z0-9 ]", "", stories.get(sid) or s["title"]).strip()[:48]
            own = [owner[s["file"]]]
            own += sorted(t for t, cs in callers.items()
                          if cs == {owner[s["file"]]} and by_id.get(t, {}).get("kind") == "api")
            capability_map.setdefault(label, [])
            capability_map[label] += [m for m in own if m not in capability_map[label]]
    for label, ids in capability_map.items():
        for mid in ids:
            by_id[mid].setdefault("capability", label)

    classes = [n for n in snapshot.nodes if n.level == DiagramLevel.COMPONENT]
    new_nodes: list[ArchNode] = []
    for m in modules:
        node = ArchNode(id=m["id"], name=_label(m["name"]), node_type=NodeType.DATABASE if m["kind"] == "db"
                        else NodeType.MODULE, level=DiagramLevel.MODULE,
                        file_path=", ".join(m["files"]), lines_of_code=m["loc"],
                        capability=m.get("capability"), description=m.get("subtitle", ""))
        new_nodes.append(node)
    for c in classes:
        parent = owner.get((c.file_path or "").replace("\\", "/"))
        if not parent:
            continue
        c.parent = parent
        new_nodes.append(c)
        next(n for n in new_nodes if n.id == parent).children.append(c.id)
    # Endpoints and screen calls as components, so summaries see what a module does.
    for m in modules:
        for ep in m.get("endpoints", [])[:30]:
            fid = f"fn:{m['id']}:{ep}"
            new_nodes.append(ArchNode(id=fid, name=ep, node_type=NodeType.FUNCTION,
                                      level=DiagramLevel.COMPONENT, parent=m["id"]))

    edges: list[ArchEdge] = [e for e in snapshot.edges if e.edge_type == EdgeType.INHERITANCE]
    for (src, tgt), calls in http.items():
        edges.append(ArchEdge(source=src, target=tgt, edge_type=EdgeType.HTTP,
                              label=f"{len(set(calls))} endpoint" + ("s" if len(set(calls)) > 1 else ""),
                              weight=len(calls)))
    for m in modules:
        if m["kind"] in {"api", "generic"}:
            text = "\n".join(_read(root / f) for f in m["files"])
            if re.search(r"from\s+(?:app|\.\.?)\.?(?:models|schemas)\b|from\s+\.\.?\s+import\s+[^\n]*\b(models|schemas)\b", text):
                edges.append(ArchEdge(source=m["id"], target="module:backend/model",
                                      edge_type=EdgeType.DEPENDENCY, label="imports"))
    if "module:db" in by_id and "module:backend/model" in by_id:
        edges.append(ArchEdge(source="module:backend/model", target="module:db",
                              edge_type=EdgeType.DATA_FLOW, label="SQL"))
    if "module:frontend/shell" in by_id and "module:backend/generic" in by_id:
        edges.append(ArchEdge(source="module:frontend/shell", target="module:backend/generic",
                              edge_type=EdgeType.HTTP, label="search"))

    snapshot.nodes = new_nodes
    snapshot.edges = edges
    snapshot.capability_map = capability_map

    members = {cls: sorted(cols, key=lambda c: (c != "id", c)) for cls, cols in
                ((c, cs) for c, cs in _model_columns(run_id).values())}
    members.update({k: v for k, v in _schema_fields(run_id).items() if v})
    views = {
        "topology": _topology(root, title),
        "modules": _module_view(snapshot, by_id),
        "data": _er_view(root),
    }
    for m in modules:
        m["mid"] = _sanitize(m["id"])
        m["l2"] = _component_view(snapshot, m["id"], members)

    languages: dict[str, int] = {}
    for f, n in loc.items():
        lang = {".py": "Python", ".js": "JavaScript", ".sql": "SQL", ".css": "CSS",
                ".html": "HTML"}.get(Path(f).suffix)
        if lang:
            languages[lang] = languages.get(lang, 0) + n

    return {
        "run_id": run_id,
        "title": title,
        "generated_at": _now(),
        "git_ref": snapshot.git_ref,
        "engine": f"ArchiLens {_version()}",
        "ai": {"status": "off"},
        "stats": {
            "files": len(loc), "loc": sum(loc.values()), "modules": len(modules),
            "screens": len(screens), "endpoints": len(routes),
            "story_endpoints": sum(len(m.get("endpoints", [])) for m in modules if m["kind"] == "api"),
            "tables": len(tables), "classes": len(classes), "languages": languages,
            "unserved_calls": sum(1 for s in screens for c in s["calls"] if not c["route"]),
        },
        "views": views,
        "modules": modules,
        "capabilities": capability_map,
        "flows": [],
        "patterns": [],
        "snapshot": json.loads(snapshot.model_dump_json()),
    }


# ---- AI (ArchiLens's prompts, the platform's local model) ------------------------

class _LocalModel:
    """ArchiLens's AI client interface, answered by the platform's local model."""

    def __init__(self, run_id: str, loop: asyncio.AbstractEventLoop):
        self.run_id, self.loop = run_id, loop

    def _run(self, coro_fn, step: str = "") -> Any:
        async def traced():
            telemetry.current_run.set(self.run_id)
            telemetry.current_stage.set("codemap")
            telemetry.current_agent.set("archilens")
            telemetry.current_step.set(step)
            return await coro_fn()
        return asyncio.run_coroutine_threadsafe(traced(), self.loop).result()

    def complete(self, prompt: str, max_tokens: int = 4096) -> str:
        return self._run(lambda: llm.complete(role="fast", system="You are a software architect.",
                                              user=prompt, max_tokens=max_tokens))

    def complete_with_tool(self, prompt: str, tool: dict[str, Any], max_tokens: int = 1024) -> dict | None:
        system = (f"You are a software architect. {tool.get('description', '')} Reply with one JSON "
                  "object that matches the schema; use plain names a stakeholder understands.")
        try:
            out = self._run(lambda: llm.complete_json(role="fast", system=system, user=prompt,
                                                      max_tokens=max(max_tokens, 1500),
                                                      schema=tool["input_schema"]), tool["name"])
        except Exception as exc:  # noqa: BLE001 — ArchiLens skips an item it gets None for
            log.warning("local model failed on %s: %s", tool["name"], exc)
            return None
        return out if isinstance(out, dict) else None


def _unchanged(previous: dict[str, Any] | None, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Modules of the previous map whose code is the same now: their explanations still hold."""
    if not previous or previous.get("git_ref") != doc.get("git_ref"):
        return {}
    now = {m["id"]: m for m in doc["modules"]}
    return {m["id"]: m for m in previous.get("modules", [])
            if m["id"] in now and m.get("loc") == now[m["id"]].get("loc") and m.get("files") == now[m["id"]].get("files")}


def _explain(run_id: str, doc: dict[str, Any], loop: asyncio.AbstractEventLoop,
             previous: dict[str, Any] | None = None) -> None:
    from archilens.ai import detect_patterns, generate_module_summaries, infer_process_flows
    from archilens.models import ArchSnapshot, DiagramLevel, ProcessFlow

    root = workspace_path(run_id)
    client = _LocalModel(run_id, loop)
    snapshot = ArchSnapshot.model_validate(doc["snapshot"])
    by_id = {m["id"]: m for m in doc["modules"]}
    same = _unchanged(previous, doc)
    old_flows = {f["id"]: f for f in (previous or {}).get("flows", []) if f.get("raw")}

    for mid, old in same.items():
        if old.get("summary"):
            by_id[mid]["summary"] = old["summary"]
            by_id[mid]["responsibility"] = old.get("responsibility", "")
    todo = snapshot.model_copy(deep=True)
    todo.nodes = [n for n in todo.nodes
                  if not (n.level == DiagramLevel.MODULE and by_id.get(n.id, {}).get("summary"))]
    if any(n.level == DiagramLevel.MODULE for n in todo.nodes):
        _status[run_id] = {"stage": "summarising each module", "error": ""}
        summaries = generate_module_summaries(todo, client, max_workers=2)
        for mid, s in summaries.items():
            if mid in by_id and s:
                by_id[mid]["summary"] = s.get("summary", "")
                by_id[mid]["responsibility"] = s.get("responsibility", "")
        _write(run_id, doc)

    entry = [m for m in doc["modules"] if m["kind"] == "api"]
    for i, m in enumerate(entry, 1):
        reused = [f for f in old_flows.values() if f.get("module") == m["id"]] if m["id"] in same else []
        if reused:
            for f in reused:
                flow = ProcessFlow.model_validate(f["raw"])
                doc["flows"].append({**f, "mermaid": _sequence(flow)})
                m.setdefault("flows", []).append(f["id"])
            continue
        _status[run_id] = {"stage": f"tracing request flows ({i}/{len(entry)})", "error": ""}
        rel = m["files"][0]
        context = ("Endpoints: " + "; ".join(m.get("endpoints", [])) + "\nCalled by screens: "
                   + ", ".join(by_id[e["source"]]["name"] for e in doc["snapshot"]["edges"]
                               if e["target"] == m["id"] and e["source"] in by_id)
                   + "\nTables: " + ", ".join((by_id.get("module:db") or {}).get("tables", [])))
        flows = infer_process_flows([{"path": rel, "language": "python", "entry_type": "http_handler",
                                      "dependencies": context}], client, root)
        for f in flows:
            doc["flows"].append({
                "id": f.id, "name": f.name, "trigger": f.trigger, "description": f.description,
                "module": m["id"], "steps": len(f.steps),
                "mermaid": _sequence(f), "raw": json.loads(f.model_dump_json()),
            })
            m.setdefault("flows", []).append(f.id)
        _write(run_id, doc)

    _status[run_id] = {"stage": "naming the architectural patterns", "error": ""}
    try:
        from archilens.engine import _build_directory_tree
        tree = _build_directory_tree(root, max_depth=3)
    except Exception:  # noqa: BLE001
        tree = ""
    doc["patterns"] = [p.value for p in detect_patterns(snapshot, tree, client)]


# ---- facts about the run ----------------------------------------------------------

def _run_facts(run_id: str) -> tuple[str, dict[str, str]]:
    with session() as s:
        run = s.get(Run, run_id)
        title = (run.title if run else "") or run_id
        backlog = (s.query(Artifact).filter(Artifact.run_id == run_id, Artifact.kind == "backlog")
                   .order_by(Artifact.version.desc()).first())
        stories = {st.get("id"): st.get("title", "") for st in ((backlog.body or {}).get("stories") or [])} \
            if backlog else {}
    return title, stories


_TITLE = re.compile(r"""\btitle\s*:\s*(['"`])([^'"`\n]{1,80})\1""")
_SUBTITLE = re.compile(r"""\bsubtitle\s*:\s*(['"`])([^'"`\n]{1,160})\1""")
# api("/x", { method: "POST", body }) — the method sits in the options after the path.
_METHOD_OPTION = re.compile(r"""\s*,\s*\{[^{}]*?\bmethod\s*:\s*['"`](\w+)""")


def _screens(run_id: str, routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = workspace_path(run_id)
    patterns = [(r["method"], _route_pattern(r["path"]), r["path"]) for r in routes]
    out = []
    for path in story_screens(run_id):
        text = path.read_text(encoding="utf-8", errors="replace")
        code = _COMMENTS.sub(" ", text)
        title = _TITLE.search(code)
        subtitle = _SUBTITLE.search(code)
        calls, seen = [], set()
        for m in _API_CALL.finditer(code):
            opts = _METHOD_OPTION.match(code, m.end())
            method = (m.group(2) or (opts.group(1) if opts else "GET")).upper()
            called = _normalise(m.group(4))
            route = next((p for meth, rx, p in patterns if meth == method and rx.match(called)), None)
            if (method, called) not in seen:
                seen.add((method, called))
                calls.append({"method": method, "path": called, "route": route})
        out.append({"file": path.relative_to(root).as_posix(),
                    "title": title.group(2) if title else path.stem.replace("_", " ").title(),
                    "subtitle": subtitle.group(2) if subtitle else "",
                    "stories": stories_in(text), "calls": calls})
    return out


def _all_files(root: Path) -> list[str]:
    keep = {".py", ".js", ".sql", ".css", ".html", ".conf", ".yml", ".yaml"}
    out = []
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if not p.is_file() or p.suffix not in keep:
            continue
        if rel.parts[0] in {".git", ".poiesis", "tests"} or "__pycache__" in rel.parts \
                or "node_modules" in rel.parts or rel.name == "conftest.py":
            continue
        if rel.as_posix() in _EXAMPLE_FILES:
            continue
        out.append(rel.as_posix())
    return sorted(out)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _lines(path: Path) -> int:
    return sum(1 for line in _read(path).splitlines() if line.strip())


def _git_ref(root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _version() -> str:
    try:
        return metadata.version("archilens")
    except metadata.PackageNotFoundError:
        return "?"


# ---- drawing ---------------------------------------------------------------------

_FENCE = re.compile(r"```mermaid\s*\n(.*?)```", re.S)


def _fenced(markdown: str) -> str:
    m = _FENCE.search(markdown or "")
    return m.group(1).rstrip() if m else ""


def _sanitize(raw: str) -> str:
    from archilens.generators.mermaid import _sanitize_id
    return _sanitize_id(raw)


def _theme(mermaid: str) -> str:
    """ArchiLens's default blues become the Spectrum palette."""
    mermaid = re.sub(r"^\s*classDef .*$\n?", "", mermaid, flags=re.M)
    if mermaid.startswith("flowchart"):
        mermaid += "\n    classDef module " + _KIND_STYLE["screen"] + "\n    classDef small " + _KIND_STYLE["api"]
    return mermaid


def _sequence(flow) -> str:
    """ArchiLens's L3 sequence diagram, from a flow cleaned so Mermaid accepts it.

    A model names participants freely ("Database (ticket table)") and ArchiLens
    turns the name into the Mermaid id, where brackets and dashes do not parse;
    it also opens an activation on every message and never closes one.
    """
    from archilens.generators.mermaid import generate_process_flow

    def name(text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 _]", " ", text or "")).strip()[:40] or "System"

    def words(text: str | None) -> str | None:
        if not text:
            return text
        return re.sub(r"\s+", " ", text.replace(";", ",").replace("#", "no. ").replace("%", " percent")
                      .replace("<", "‹").replace(">", "›")).strip()[:120]

    clean = flow.model_copy(deep=True)
    for st in clean.steps:
        st.actor, st.target = name(st.actor), name(st.target)
        st.action, st.data, st.condition = words(st.action) or "", words(st.data), words(st.condition)
    body = _fenced(generate_process_flow(clean))
    body = body.replace("->>+", "->>")
    return "sequenceDiagram\n    autonumber" + body[len("sequenceDiagram"):] if body.startswith("sequenceDiagram") else body


def _label(text: str) -> str:
    return text.replace('"', "'").replace("<", "‹").replace(">", "›")


def _module_view(snapshot, by_id: dict[str, dict[str, Any]]) -> str:
    """ArchiLens's L1 drawing, with HTTP calls dotted and each kind in its own colour."""
    from archilens.generators.mermaid import generate_module_architecture
    from archilens.models import EdgeType

    drawn = snapshot.model_copy(deep=True)
    for n in drawn.nodes:
        n.ai_summary = None  # summaries belong in the side panel, not in the boxes
    drawn.edges = [e for e in drawn.edges if e.edge_type == EdgeType.DEPENDENCY]
    body = _theme(_fenced(generate_module_architecture(drawn)))
    # Top to bottom: the story groups sit side by side above the shared APIs, the
    # model and the database, which fits a screen; left to right stacks nine
    # groups into one column too tall to read.
    lines = body.replace("flowchart LR", "flowchart TB", 1).splitlines()
    for e in snapshot.edges:
        if e.source in by_id and e.target in by_id:
            s, t = _sanitize(e.source), _sanitize(e.target)
            if e.edge_type == EdgeType.HTTP:
                lines.append(f"    {s} -.->|{_label(e.label)}| {t}")
            elif e.edge_type == EdgeType.DATA_FLOW:
                lines.append(f"    {s} ==>|{_label(e.label)}| {t}")
    kinds: dict[str, list[str]] = {}
    for mid, m in by_id.items():
        kinds.setdefault(m["kind"], []).append(_sanitize(mid))
    for kind, style in _KIND_STYLE.items():
        lines.append(f"    classDef {kind} {style}")
    for kind, ids in kinds.items():
        if kind in _KIND_STYLE:
            lines.append(f"    class {','.join(ids)} {kind}")
    return "\n".join(lines)


def _component_view(snapshot, module_id: str, members: dict[str, list[str]]) -> str | None:
    """ArchiLens's L2 class diagram, with each class's columns or fields as its members.

    ArchiLens lists only the file a class lives in; for the data model the
    interesting part is what each table and schema holds, which Poiesis knows.
    """
    from archilens.generators.mermaid import generate_component_detail
    from archilens.models import NodeType

    if not any(n.parent == module_id and n.node_type in (NodeType.CLASS, NodeType.INTERFACE)
               for n in snapshot.nodes):
        return None
    body = _theme(_fenced(generate_component_detail(snapshot, module_id) or ""))
    if not body:
        return None

    def fill(m: re.Match) -> str:
        fields = members.get(m.group(2))
        if not fields:
            return m.group(0)
        shown = [f"        +{f}" for f in fields[:12]] + ([f"        +{len(fields) - 12} more"] if len(fields) > 12 else [])
        return m.group(1) + "\n".join(shown) + "\n"

    return _CLASS_BLOCK.sub(fill, body)


_CLASS_BLOCK = re.compile(r"(^\s*class (\w+) \{\n)(?:\s*\+[^\n]*\n)*", re.M)


def _topology(root: Path, title: str) -> str:
    """The services docker compose starts and how a request travels between them."""
    try:
        compose = yaml.safe_load(_read(root / "docker-compose.yml")) or {}
    except yaml.YAMLError:
        compose = {}
    services = compose.get("services") or {}
    nginx = _read(root / "frontend" / "nginx.conf")
    lines = ["flowchart LR", '    visitor(["Visitor · browser"]):::actor']
    roles = {"frontend": ("gateway", "Gateway · nginx", "screens, UI kit, /api proxy"),
             "backend": ("api", "api service", "story endpoints + generic data API"),
             "data": ("generic", "data service", "generic data API only"),
             "db": ("db", "PostgreSQL", "seeded from db/init.sql")}
    for name, svc in services.items():
        kind, label, note = roles.get(name, ("core", name, ""))
        shape = f'[("{label}<br/><small>{note}</small>")]' if kind == "db" \
            else f'["{label}<br/><small>{note}</small>"]'
        lines.append(f"    svc_{_sanitize(name)}{shape}:::{kind}")
    for name, svc in services.items():
        if (svc or {}).get("ports"):
            lines.append(f"    visitor -->|HTTP| svc_{_sanitize(name)}")
    for target in re.findall(r"proxy_pass\s+http://([a-z0-9_-]+)", nginx) + \
            re.findall(r"set\s+\$\w+\s+http://([a-z0-9_-]+)", nginx):
        if target in services and "frontend" in services:
            arrow = "-.->|fallback|" if target == "data" else "-->|/api|"
            line = f"    svc_frontend {arrow} svc_{_sanitize(target)}"
            if line not in lines:
                lines.append(line)
    for name, svc in services.items():
        env = (svc or {}).get("environment") or {}
        url = env.get("DATABASE_URL", "") if isinstance(env, dict) else " ".join(env)
        host = re.search(r"@([a-z0-9_-]+):\d+", str(url))
        if host and host.group(1) in services:
            lines.append(f"    svc_{_sanitize(name)} ==>|SQL| svc_{_sanitize(host.group(1))}")
    lines += [f"    classDef {k} {v}" for k, v in _KIND_STYLE.items()]
    return "\n".join(lines)


_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)\s*\((.*?)\)\s*;", re.I | re.S)
_REF = re.compile(r"REFERENCES\s+([A-Za-z_]\w*)", re.I)


def _tables(root: Path) -> dict[str, list[tuple[str, str, str, str]]]:
    """table -> [(column, type, PK/FK marker, referenced table)], from db/init.sql."""
    sql = strip_sql_comments(_read(root / "db" / "init.sql"))
    out: dict[str, list[tuple[str, str, str]]] = {}
    for name, body in _CREATE.findall(sql):
        if name.lower() == "example":
            continue
        cols = []
        for part in _top_level(body):
            bits = part.strip().split()
            if len(bits) < 2 or bits[0].upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK"}:
                continue
            typ = re.sub(r"\W", "", bits[1].split("(")[0]).lower() or "text"
            ref = _REF.search(part)
            key = "PK" if "PRIMARY" in part.upper() else ("FK" if ref else "")
            cols.append((bits[0].strip('"'), typ, key, ref.group(1) if ref else ""))
        out[name] = cols
    return out


def _er_view(root: Path) -> str:
    tables = _tables(root)
    if not tables:
        return ""
    lines = ["erDiagram"]
    links: list[str] = []
    for name, cols in tables.items():
        lines.append(f"    {name} {{")
        for col, typ, key, ref in cols[:20]:
            target = ref or _implied_reference(col, name, tables)
            marker = key or ("FK" if target else "")
            lines.append(f"        {typ} {col}{' ' + marker if marker else ''}")
            if target:
                # Declared REFERENCES draw solid; a *_id column naming a table, dashed.
                links.append(f'    {target} {"||--o{" if ref else "||..o{"} {name} : "{col}"')
        if len(cols) > 20:
            lines.append(f"        text more_{len(cols) - 20}_columns")
        lines.append("    }")
    return "\n".join(lines + links)


def _implied_reference(col: str, table: str, tables: dict[str, Any]) -> str:
    """`customer_id` -> customer, `resolved_by_agent_id` -> agent, `assignee_id` -> nothing."""
    if not col.endswith("_id"):
        return ""
    stem = col[:-3]
    for t in sorted(tables, key=len, reverse=True):
        if t != table and (stem == t or stem.endswith("_" + t) or stem == t.rstrip("s")):
            return t
    return ""
