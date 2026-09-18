"""What the workspace actually exports, read from the workspace.

Both the Developer and the Tester were inventing imports — independently guessing
`from backend.app.db import get_db`, a module path that does not exist and a
symbol that was never defined. Neither agent was ever shown a file's contents, so
neither could discover that the scaffold exports `get_session`. Three repair
attempts reproduced the same wrong line because each one regenerated the file
from memory.

Parsing the real files and handing the agents a verified list of importable names
and routes costs a few hundred characters — which matters on a 12k local context —
and removes the entire class of error.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .repo import workspace_path

# Where a generated application keeps its importable Python.
PACKAGE_DIR = ("backend", "app")
ROUTERS_DIR = ("backend", "app", "routers")
SCREENS_DIR = ("frontend", "screens")
EXAMPLE_ROUTER = "examples.py"
EXAMPLE_SCREEN = "example.js"
REGISTRY = "index.js"

# main.py mounts every router here. A route declared "/items" is served at
# "/api/items", and the two agents were disagreeing about that: the Developer
# declared the short form and the Tester requested it verbatim, so every call
# returned 404 while both files looked correct in isolation.
ROUTER_PREFIX = "/api"


def _public_names(source: str) -> list[str]:
    """Top-level classes and functions, excluding private ones."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.append(target.id)
    return names


def router_files(run_id: str) -> list[Path]:
    """Every file that declares endpoints: the base routes.py plus one router per story.

    The worked example counts only until a real router exists — the same rule
    routers/__init__.py applies at runtime, so the contract and the app agree.
    """
    root = workspace_path(run_id)
    files: list[Path] = []
    base = root.joinpath(*PACKAGE_DIR, "routes.py")
    if base.is_file():
        files.append(base)
    routers = root.joinpath(*ROUTERS_DIR)
    if routers.is_dir():
        modules = sorted(p for p in routers.glob("*.py") if not p.name.startswith("_"))
        real = [p for p in modules if p.name != EXAMPLE_ROUTER]
        files += real or modules
    return files


def import_contract(run_id: str) -> str:
    """A verified import block for the prompt, or "" when there is no package yet."""
    package = workspace_path(run_id).joinpath(*PACKAGE_DIR)
    if not package.is_dir():
        return ""

    modules: list[tuple[str, list[str]]] = []
    for path in sorted(package.glob("*.py")):
        if path.name in ("__init__.py", "main.py", "routes.py"):
            continue
        names = _public_names(path.read_text(encoding="utf-8", errors="replace"))
        if names:
            modules.append((path.stem, names[:14]))
    if not modules:
        return ""

    in_routers = "\n".join(f"  from ..{m} import {', '.join(n)}" for m, n in modules)
    from_tests = "\n".join(f"  from app.{m} import {', '.join(n)}" for m, n in modules)
    return (
        "\nVERIFIED IMPORTS — these names exist in this workspace right now. Use them "
        "exactly; anything else fails at import time.\n"
        f"Inside backend/app/routers/<your router>.py (one package down, so two dots):\n{in_routers}\n"
        f"From a file in tests/:\n{from_tests}\n"
        "  from app.main import app\n"
        "There is no `backend.app` package path. Never import it.\n"
    )


_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _status_code(deco: ast.Call) -> int:
    """The success status an endpoint returns. FastAPI's default is 200.

    Reported because agents disagreed about it the same way they disagreed about
    paths: the idiomatic 201 on create and a test expecting 200, or the reverse.
    """
    for kw in deco.keywords:
        if kw.arg != "status_code":
            continue
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
            return kw.value.value
        if isinstance(kw.value, ast.Attribute):  # status.HTTP_201_CREATED
            digits = "".join(ch for ch in kw.value.attr if ch.isdigit())
            if digits:
                return int(digits[:3])
    return 200


_NOT_A_BODY = {"db", "session", "request", "response"}


def _body_schema(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """The Pydantic model an endpoint takes as its JSON body, if any."""
    for arg in fn.args.args:
        ann = arg.annotation
        if arg.arg in _NOT_A_BODY or not isinstance(ann, ast.Name):
            continue
        if ann.id[:1].isupper():
            return ann.id
    return None


def _response_model(deco: ast.Call) -> tuple[str, bool] | None:
    """The response_model an endpoint declares: (schema name, whether it is a list)."""
    for kw in deco.keywords:
        if kw.arg != "response_model":
            continue
        value = kw.value
        if isinstance(value, ast.Name):
            return value.id, False
        if (
            isinstance(value, ast.Subscript)
            and isinstance(value.value, ast.Name)
            and value.value.id in ("list", "List")
            and isinstance(value.slice, ast.Name)
        ):
            return value.slice.id, True
    return None


def _schema_fields(run_id: str) -> dict[str, list[str]]:
    """Field names of every Pydantic schema in schemas.py, keyed by class name.

    Without these the Tester guessed the response shape. It compared whole bodies
    with `==` against a shape that omitted the generated id and timestamp, so a
    correct implementation could never pass.
    """
    path = workspace_path(run_id).joinpath(*PACKAGE_DIR, "schemas.py")
    if not path.is_file():
        return {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return {}
    shapes: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            shapes[node.name] = [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id != "model_config"
            ]
    return shapes


def _shape(name: str, fields: dict[str, list[str]]) -> str:
    known = fields.get(name)
    return f"{name}{{{', '.join(known)}}}" if known else name


def _router_prefix(tree: ast.Module) -> str:
    """The prefix in `router = APIRouter(prefix="/items")`, which every route in the module shares.

    FastAPI honours it, so a contract that ignored it would report a correct
    router as serving /api/ and then flag a correct screen as calling a route
    that does not exist.
    """
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name != "APIRouter":
            continue
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                stripped = kw.value.value.strip("/")
                return f"/{stripped}" if stripped else ""
    return ""


def declared_routes(run_id: str) -> list[dict[str, Any]]:
    """Every endpoint the application serves: method, full path, shapes, owning file."""
    root = workspace_path(run_id)
    out: list[dict[str, Any]] = []
    for path in router_files(run_id):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = path.relative_to(root).as_posix()
        prefix = _router_prefix(tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)):
                    continue
                method = deco.func.attr.lower()
                if method not in _HTTP_METHODS or not deco.args:
                    continue
                first = deco.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    route = first.value if first.value.startswith("/") else "/" + first.value
                    out.append({
                        "method": method.upper(), "path": f"{ROUTER_PREFIX}{prefix}{route}",
                        "body": _body_schema(node), "reply": _response_model(deco),
                        "status": _status_code(deco), "file": rel,
                    })
    return out


def route_contract(run_id: str) -> str:
    """The URLs the application actually serves, read from its own decorators."""
    routes = declared_routes(run_id)
    if not routes:
        return ""
    fields = _schema_fields(run_id)
    lines: list[str] = []
    for r in routes:
        line = f"  {r['method']:<6} {r['path']}"
        if r["body"]:
            line += f"   body {_shape(r['body'], fields)}"
        line += f"   -> {r['status']}"
        if r["reply"]:
            name, many = r["reply"]
            shape = _shape(name, fields)
            line += f" {'list of ' + shape if many else shape}"
        line += f"   [{Path(r['file']).name}]"
        lines.append(line)
    return (
        "\nVERIFIED ROUTES — the full URLs this application serves right now. Routers are "
        f"mounted at {ROUTER_PREFIX}, so a route declared \"/x\" is served at "
        f"\"{ROUTER_PREFIX}/x\". Request these exact paths; anything else returns 404.\n"
        + "\n".join(lines)
        + "\n"
    )


def _blocks(run_id: str, paths: list[tuple[str, int]]) -> list[str]:
    root = workspace_path(run_id)
    blocks: list[str] = []
    for rel, budget in paths:
        target = root / rel
        if not target.is_file():
            continue
        body = target.read_text(encoding="utf-8", errors="replace")
        clipped = body[:budget]
        if len(body) > budget:
            clipped += f"\n… ({len(body) - budget} more characters)"
        blocks.append(f"### {rel}\n{clipped}")
    return blocks


def excerpt(run_id: str, paths: list[tuple[str, int]]) -> str:
    """Current contents of the shared files a story adds to.

    Without this the Developer emits 'complete file content' from memory on every
    repair attempt, so a fix cannot build on what is already there.
    """
    blocks = _blocks(run_id, paths)
    if not blocks:
        return ""
    return ("\nSHARED FILES — return them complete, keeping everything already in them:\n"
            + "\n\n".join(blocks) + "\n")


# The scaffold's worked examples. Shown as patterns to copy into new files; they
# are protected, so a model that "repurposes" them has its edit refused.
REFERENCE: list[tuple[str, int]] = [
    ("backend/app/routers/examples.py", 1500),
    ("frontend/screens/example.js", 1700),
]


def reference(run_id: str) -> str:
    blocks = _blocks(run_id, REFERENCE)
    if not blocks:
        return ""
    return ("\nREFERENCE — the scaffold's worked examples. Copy their shape into NEW files "
            "for your story; these two are read-only:\n" + "\n\n".join(blocks) + "\n")


# Shared files a story may add to, each with a character budget. Routes and
# screens are no longer here: each story owns its own router and screen file, so
# only the genuinely shared schema, models and SQL are shown.
EDITABLE: list[tuple[str, int]] = [
    ("backend/app/schemas.py", 1800),
    ("backend/app/models.py", 1500),
    ("db/init.sql", 900),
]


def story_files(run_id: str, story_id: str, budget: int = 2200, limit: int = 3) -> str:
    """The router and screen files this story already has, and the names others use.

    On a repair the Developer must see its own screen and router to build on them,
    and must know the other stories' file names so it does not overwrite them.
    """
    root = workspace_path(run_id)
    candidates: list[Path] = []
    routers = root.joinpath(*ROUTERS_DIR)
    if routers.is_dir():
        candidates += [p for p in sorted(routers.glob("*.py"))
                       if not p.name.startswith("_") and p.name != EXAMPLE_ROUTER]
    screens = root.joinpath(*SCREENS_DIR)
    if screens.is_dir():
        candidates += [p for p in sorted(screens.glob("*.js"))
                       if p.name not in (REGISTRY, EXAMPLE_SCREEN)]
    mine_pattern = re.compile(rf"\b{re.escape(story_id)}\b")
    mine: list[tuple[str, int]] = []
    others: list[str] = []
    for path in candidates:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        if mine_pattern.search(text):
            mine.append((rel, budget))
        else:
            others.append(rel)
    parts: list[str] = []
    if mine:
        parts.append("\nYOUR STORY'S FILES SO FAR — return their complete new contents if you change them:\n"
                     + "\n\n".join(_blocks(run_id, mine[:limit])) + "\n")
    if others:
        parts.append("\nOTHER STORIES' FILES — do not overwrite these; choose different names: "
                     + ", ".join(others) + "\n")
    return "".join(parts)
