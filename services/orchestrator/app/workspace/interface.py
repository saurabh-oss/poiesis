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


_LEADING_NOISE = re.compile(r"\A(?:\s|--[^\n]*\n|/\*[\s\S]*?\*/)*")
_INSERT_HEAD = re.compile(r"\AINSERT\s+INTO\s+([A-Za-z_]\w*)", re.I)


def _sql_statements(sql: str) -> list[str]:
    """Split on semicolons that are not inside a quoted string or a comment.

    Seed rows are prose written by a model - "the charge failed; I was billed
    twice" - so splitting on every semicolon tears statements in half. Comments
    matter for the same reason: a model labels its seed block with a line like
    "-- 42 tickets; every status", and an apostrophe or semicolon in there would
    otherwise be read as SQL.
    """
    out, start, i, quote = [], 0, 0, ""
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:  # '' escapes a quote
                    i += 1
                else:
                    quote = ""
        elif ch in "'\"":
            quote = ch
        elif sql.startswith("--", i):
            i = sql.find("\n", i)
            if i < 0:
                break
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end < 0 else end + 1
        elif ch == ";":
            statement = sql[start:i + 1].strip()
            if statement:
                out.append(statement)
            start = i + 1
        i += 1
    tail = sql[start:].strip()
    if tail:
        out.append(tail)
    return out


def _seed_rows(statements: list[str]) -> int:
    """Roughly how many rows a table's INSERTs carry.

    One statement is not one row: models write a table's whole seed as a single
    INSERT with a tuple per line, so counting statements would score 42 tickets
    and 5 tickets identically.
    """
    return sum(len(re.findall(r"\)\s*,\s*\(", s)) + 1 for s in statements)


def _inserts_by_table(sql: str) -> dict[str, list[str]]:
    """Every INSERT statement in `sql`, grouped by the table it writes to."""
    grouped: dict[str, list[str]] = {}
    for statement in _sql_statements(sql):
        # A statement carries the comment block the model wrote above it.
        head = _INSERT_HEAD.match(statement[_LEADING_NOISE.match(statement).end():])
        if head:
            grouped.setdefault(head.group(1).lower(), []).append(statement)
    return grouped


_TABLE_DEF = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_]\w*)\s*\((.*?)\)\s*;", re.I | re.S)
_INSERT_COLS = re.compile(r"INSERT\s+INTO\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*VALUES\s*", re.I)
_CONSTRAINT = {"PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK"}


def _top_level(text: str, sep: str = ",") -> list[str]:
    """Split on `sep` outside parentheses and quoted strings."""
    parts, cur, depth, quote = [], [], 0, ""
    for ch in text:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = ""
            continue
        if ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _table_columns(sql: str) -> dict[str, dict[str, bool]]:
    """table -> {column: whether an INSERT must supply it}, from every CREATE TABLE."""
    out: dict[str, dict[str, bool]] = {}
    for m in _TABLE_DEF.finditer(sql):
        cols: dict[str, bool] = {}
        for part in _top_level(m.group(2)):
            words = part.split()
            if not words or words[0].upper() in _CONSTRAINT:
                continue
            upper = part.upper()
            generated = "SERIAL" in upper or "IDENTITY" in upper or "PRIMARY KEY" in upper
            cols[words[0].strip('"').lower()] = ("NOT NULL" in upper and "DEFAULT" not in upper
                                                  and not generated)
        out[m.group(1).lower()] = cols
    return out


def _value_tuples(rest: str) -> tuple[list[str], str]:
    """The `(...)` tuples at the start of `rest`, and whatever follows them (ON CONFLICT ...)."""
    tuples, i, n = [], 0, len(rest)
    while i < n:
        while i < n and rest[i] in " \t\r\n,":
            i += 1
        if i >= n or rest[i] != "(":
            break
        depth, quote, j = 0, "", i
        while j < n:
            ch = rest[j]
            if quote:
                quote = "" if ch == quote else quote
            elif ch in "'\"":
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        tuples.append(rest[i + 1:j])
        i = j + 1
    return tuples, rest[i:].strip()


def _adapt_insert(statement: str, columns: dict[str, bool]) -> tuple[str | None, list[str], list[str]]:
    """Fit an INSERT written for an older version of its table to the table as it is now.

    Returns (the adapted statement, columns dropped, required columns it cannot
    fill). Values for columns the table no longer has are removed; a column the
    table now requires and the rows never had cannot be invented, so the
    statement is refused (None) rather than restored into a file that would then
    fail when Postgres runs it.
    """
    head = _INSERT_COLS.search(statement)
    if not head:
        return statement, [], []  # no column list: nothing to line up, keep it as written
    names = [c.strip().strip('"') for c in head.group(2).split(",")]
    lowered = [c.lower() for c in names]
    missing = [c for c, required in columns.items() if required and c not in lowered]
    if missing:
        return None, [], missing
    keep = [i for i, c in enumerate(lowered) if c in columns]
    dropped = [names[i] for i in range(len(names)) if i not in keep]
    if not dropped:
        return statement, [], []
    tuples, tail = _value_tuples(statement[head.end():])
    rows = []
    for t in tuples:
        values = _top_level(t)
        if len(values) != len(names):
            return None, [], ["(a row whose values do not line up with its column list)"]
        rows.append("(" + ", ".join(values[i].strip() for i in keep) + ")")
    prefix = statement[:head.start()]
    rebuilt = (f"{prefix}INSERT INTO {head.group(1)} ({', '.join(names[i] for i in keep)}) VALUES\n    "
               + ",\n    ".join(rows) + ("\n" + tail if tail and tail != ";" else ""))
    return rebuilt.rstrip().rstrip(";") + ";", dropped, []


def _schema_only(body: str) -> str:
    """init.sql as the Developer needs to see it: every table, none of the rows.

    A seeded demonstration database is tens of kilobytes of INSERTs. Clipped to a
    few hundred characters and captioned "return it complete, keeping everything
    already in it", it asked for something impossible: the model saw the schema
    and faithfully returned the schema, dropping every seeded row, on every single
    repair attempt. It needs the columns to write correct queries; it never needs
    the rows. So it is shown the schema in full and told the rows are kept for it.
    """
    schema = [s for s in _sql_statements(body) if "INSERT INTO" not in s.upper()]
    counts = {t: _seed_rows(v) for t, v in _inserts_by_table(body).items()}
    held = ", ".join(f"{n} in {t}" for t, n in sorted(counts.items()) if n) or "none yet"
    empty = sorted(t for t in _table_columns(body) if not counts.get(t) and t != "example")
    return (
        "\n".join(schema)
        + f"\n\n-- Seeded rows currently in this file, kept by the platform: {held}.\n"
        "-- They are NOT shown here and you must NOT reproduce them. Return init.sql\n"
        "-- with the table definitions only; the rows above are preserved for you,\n"
        "-- fitted to your table definitions if you change them.\n"
        + (f"-- These tables have NO rows: {', '.join(empty)}. If your story's screens\n"
           "-- read one of them, seed it here with INSERT statements for that table only.\n"
           if empty else "")
        + "-- If you add a NOT NULL column to a seeded table, give it a DEFAULT, or its\n"
        "-- existing rows cannot be kept.\n"
    )


def _blocks(run_id: str, paths: list[tuple[str, int]]) -> list[str]:
    root = workspace_path(run_id)
    blocks: list[str] = []
    for rel, budget in paths:
        target = root / rel
        if not target.is_file():
            continue
        body = target.read_text(encoding="utf-8", errors="replace")
        if rel.endswith("init.sql"):
            blocks.append(f"### {rel}\n{_schema_only(body)}")
            continue
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
