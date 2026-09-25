"""Ground truth for anything that writes checks against a running application.

The first acceptance checks written for DupeGuard called `api.post(path, {...})`, created
tickets already "Open" in a product area the app does not have, and asserted a `counts`
field the scan never returns: the writer had the routes but not what they answer or which
values the data takes. So before any check is written, the platform asks the running app
itself: every GET it serves is called once on the app's own network and its answer kept,
and every column whose init.sql comment lists its allowed values is listed.
"""
from __future__ import annotations

import json
import re

from . import deployment as runtime
from . import repo
from .interface import declared_routes
from .runner import run_in_sandbox

SAMPLER = r'''
import json, os
import httpx
base = os.environ.get("BASE_URL", "").rstrip("/")
token = os.environ.get("SERVICE_TOKEN", "")
paths = json.load(open(".poiesis/sample_paths.json"))


def shape(v, depth=0):
    """A value's structure: which keys exist and what they hold, so a check never guesses a field."""
    if isinstance(v, dict):
        if depth >= 2:
            return "{" + ", ".join(list(v)[:25]) + "}"
        return "{" + ", ".join(f"{k}: {shape(x, depth + 1)}" for k, x in list(v.items())[:30]) + "}"
    if isinstance(v, list):
        return f"list[{len(v)}] of " + (shape(v[0], depth + 1) if v else "nothing")
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return type(v).__name__
    if v is None:
        return "null"
    return "str"


def example(v):
    first = v[0] if isinstance(v, list) and v else v
    return json.dumps(first, default=str)[:450]


out = {}
with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"} if token else {}, timeout=30) as c:
    for p in paths:
        try:
            r = c.get(p)
            try:
                body = r.json()
                out[p] = {"status": r.status_code, "shape": shape(body), "example": example(body)}
            except ValueError:
                out[p] = {"status": r.status_code, "shape": "text", "example": r.text[:300]}
        except Exception as exc:
            out[p] = {"status": 0, "shape": "unreachable", "example": str(exc)[:200]}
json.dump(out, open(".poiesis/samples.json", "w"))
'''

_TABLE = re.compile(r"\s*CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)", re.IGNORECASE)
_COMMENTED = re.compile(r"\s*(\w+)\s+[A-Za-z].*--\s*(\S.*\|.*)$")


_COLUMN = re.compile(r"\s*(\w+)\s+([A-Za-z]+)", re.IGNORECASE)


def allowed_values(run_id: str) -> str:
    """Each column whose init.sql comment lists its allowed values (`status … -- New|Open|Closed`),
    and the columns a new record must be given (NOT NULL, no default)."""
    sql = repo.read(run_id, "db/init.sql", 400000)
    lines: list[str] = []
    required: dict[str, list[str]] = {}
    table = ""
    for line in sql.splitlines():
        m = _TABLE.match(line)
        if m:
            table = m.group(1)
            continue
        if line.lstrip().upper().startswith(("INSERT", ")", "CREATE INDEX", "SELECT")):
            table = ""
            continue
        if not table:
            continue
        m = _COMMENTED.match(line)
        if m:
            lines.append(f"- {table}.{m.group(1)}: {m.group(2).strip()}")
        col = _COLUMN.match(line)
        upper = line.split("--")[0].upper()
        if col and "NOT NULL" in upper and "DEFAULT" not in upper and "PRIMARY KEY" not in upper \
                and col.group(1).upper() not in ("CONSTRAINT", "PRIMARY", "UNIQUE", "FOREIGN"):
            required.setdefault(table, []).append(col.group(1))
    out = ""
    if lines:
        out += ("ALLOWED VALUES (use only these; leave a status column out when creating a record, it starts in "
                "its first state, and move it only through the app's own endpoints):\n" + "\n".join(lines[:60]) + "\n")
    if required:
        out += ("REQUIRED WHEN CREATING (NOT NULL with no default; a POST without them fails):\n"
                + "\n".join(f"- {t}: {', '.join(cols)}" for t, cols in required.items()) + "\n")
    return out


_READ_KEY = re.compile(r"""(?:\.get\(\s*|\[\s*)["']([A-Za-z_]\w*)["']""")
_SHAPE_KEY = re.compile(r"([A-Za-z_]\w*):")


def known_fields(run_id: str) -> set[str]:
    """Every field name the app's data or responses have: sampled shapes, tables, route bodies."""
    from .interface import model_tables
    names: set[str] = set()
    for cols in model_tables(run_id).values():
        names |= set(cols)
    path = repo.workspace_path(run_id) / ".poiesis" / "samples.json"
    try:
        for v in json.loads(path.read_text(encoding="utf-8")).values():
            names |= set(_SHAPE_KEY.findall(str(v.get("shape", ""))))
            names |= set(re.findall(r'"([A-Za-z_]\w*)":', str(v.get("example", ""))))
    except (OSError, ValueError):
        pass
    return names


def unknown_reads(source: str, known: set[str]) -> list[str]:
    """Fields a check reads from a response that no response or table has."""
    ignore = {"detail", "token", "json", "text", "status_code", "rule"}
    return sorted({k for k in _READ_KEY.findall(source or "") if k not in known and k not in ignore})


def _token(run_id: str) -> str:
    kernel = repo.workspace_path(run_id) / "backend" / "app" / "kernel"
    return runtime.service_token(run_id) if kernel.is_dir() else ""


async def live_samples(run_id: str) -> str:
    """What the running app answers on each GET it serves, called once on its own network."""
    paths: list[str] = []
    for r in declared_routes(run_id):
        if r["method"] != "GET" or "{" in r["path"] or r["path"].endswith("/resources"):
            continue
        paths.append(r["path"] + ("?limit=2" if r.get("generic") else ""))
    paths = list(dict.fromkeys(paths))[:60]
    if not paths:
        return ""
    tools = repo.workspace_path(run_id) / ".poiesis"
    tools.mkdir(exist_ok=True)
    (tools / "sample_paths.json").write_text(json.dumps(paths), encoding="utf-8")
    (tools / "sampler.py").write_text(SAMPLER, encoding="utf-8", newline="\n")
    (tools / "samples.json").unlink(missing_ok=True)
    service, port = runtime.entry_service(run_id)
    await run_in_sandbox(
        run_id, "pip install --quiet --disable-pip-version-check --root-user-action=ignore httpx >/dev/null 2>&1; "
                "python .poiesis/sampler.py",
        timeout=300, network_name=f"{runtime.project_name(run_id)}_default",
        env={"BASE_URL": f"http://{service}:{port}", "SERVICE_TOKEN": _token(run_id)})
    try:
        samples = json.loads((tools / "samples.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return ("LIVE RESPONSES — what the running app answers right now on each GET: its status, the shape of the "
            "body (a field that is not in the shape does not exist) and its first record:\n"
            + "\n".join(f"GET {p} -> {v.get('status')}\n  shape: {str(v.get('shape', ''))[:1200]}\n"
                        f"  first: {str(v.get('example', ''))[:450]}" for p, v in samples.items())
            + "\n")
