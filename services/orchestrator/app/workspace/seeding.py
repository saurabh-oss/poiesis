"""Demonstration data: from a generator script to rows in db/init.sql.

A model asked to write 150 varied rows as SQL writes twenty-five copies of six
titles, and the reply is long enough to be cut off. Asked instead for a small
Python program — catalogues of realistic values, a seeded random generator,
loops that combine them — it produces more variety in a tenth of the tokens.
The platform runs that program in the sandbox, checks what came out (the
columns exist, required ones are filled, the text is varied, the counts meet
what the brief asked for), renders it as INSERT statements and keeps them in a
section of init.sql it owns. The deployed app, and the test database, open with
that data.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from .checks import _AT_LEAST, _NOT_DATA, _table_columns
from .repo import workspace_path
from .runner import ExecResult, run_in_sandbox

SEED_SCRIPT = "db/seed.py"
# A generator is a few hundred lines. Past that it is the rows written out as
# literals, which is what the reply budget cannot hold and the check refuses.
MAX_SEED_LINES = 450
MAX_SEED_CHARS = 32000
SEED_MARKER = "-- ==== DEMONSTRATION DATA — generated from db/seed.py by the platform; this section is rewritten ===="
MAX_ROWS_PER_TABLE = 5000
_CHUNK = 50

# What seed.py must look like, shown to the Data Designer and checked here.
SEED_CONTRACT = f"""\
THE CONTRACT FOR {SEED_SCRIPT}:
- A plain Python 3.12 module using only the standard library (random, datetime, itertools,
  math, string). No third-party packages: `faker` and friends are not installed.
- It defines `def rows() -> dict[str, list[dict]]` returning, for every table that needs
  data, its rows as dicts with one key per column. Tables in dependency order: a table
  comes after the tables its rows reference.
- Never include `id`. Ids are assigned 1, 2, 3 … in the order you return the rows, so refer
  to a row by its position: `"agent_id": 3` is the third agent you returned. Keep foreign
  keys inside that range.
- Dates and times are ISO-8601 strings (`"2024-03-14T09:30:00+00:00"`, `"2024-03-14"`), booleans
  are True/False, missing optional values are None. Fill every NOT NULL column.
- Deterministic: `rng = random.Random(42)`. Build the dates relative to `datetime.now()` so
  "the last 30 days" is still the last 30 days when the app is opened.
- Realistic and varied: catalogues of at least 30 distinct subjects/descriptions written like
  real customers and staff write, distinct person and company names, spread of statuses,
  priorities, plans and dates. Where the brief wants near-duplicates, write clusters of
  3–6 rows describing the same problem in different words. Never number the copies
  ("Payment failed #1", "#2"); never repeat one sentence 25 times.
- Fast: it runs in well under ten seconds and prints nothing.
- SHORT: at most 300 lines. That is the size of a generator. A file of literal rows is
  thousands of lines, is cut off before it ends, and is refused without being run. Write
  catalogues (lists of 30-40 subjects, of names, of companies) and loops that combine them.
"""


def size_issue(script: str) -> str:
    """Why a script is a dump of literals rather than a generator, or ''."""
    lines = script.count("\n") + 1
    if lines <= MAX_SEED_LINES and len(script) <= MAX_SEED_CHARS:
        return ""
    return (f"{SEED_SCRIPT} is {lines} lines / {len(script):,} characters: that is the rows written out as "
            f"literals, not a generator, and the reply was cut off before the file ended. Write at most "
            f"{MAX_SEED_LINES // 1.5:.0f} lines: catalogues of 30-40 distinct subjects, names and companies, "
            "a seeded random.Random, and loops that combine them into the counts the brief asks for.")


def _sql_value(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (dt.datetime, dt.date)):
        value = value.isoformat()
    if isinstance(value, (dict, list)):
        value = json.dumps(value)
    text = str(value).replace("\x00", "")
    return "'" + text.replace("'", "''") + "'"


def rows_to_sql(rows_by_table: dict[str, list[dict[str, Any]]], tables: dict[str, dict[str, bool]],
                ) -> tuple[str, list[str]]:
    """INSERT statements for the rows, and what is wrong with them.

    `tables` is checks._table_columns(init.sql): table -> {column: required}. A
    problem is reported, not repaired: the Data Designer gets the list back.
    """
    issues: list[str] = []
    out: list[str] = []
    for table, rows in rows_by_table.items():
        name = str(table).lower()
        if name not in tables:
            issues.append(f"`{table}` is not a table in db/init.sql (tables: {', '.join(sorted(tables)) or 'none'})")
            continue
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            issues.append(f"{table}: rows() must return a list of dicts for it")
            continue
        if not rows:
            continue
        if len(rows) > MAX_ROWS_PER_TABLE:
            issues.append(f"{table}: {len(rows)} rows is more than the {MAX_ROWS_PER_TABLE} a demonstration needs")
            rows = rows[:MAX_ROWS_PER_TABLE]
        spec = tables[name]
        ids = [r.get("id") for r in rows if "id" in r]
        if ids and ids != list(range(1, len(rows) + 1)):
            issues.append(f"{table}: leave `id` out — ids are assigned 1..{len(rows)} in order, and the ids "
                          "returned do not match that")
        columns = [c for c in dict.fromkeys(k for r in rows for k in r) if c != "id"]
        unknown = [c for c in columns if c.lower() not in spec]
        if unknown:
            issues.append(f"{table}: column(s) {', '.join(unknown)} do not exist in its CREATE TABLE "
                          f"(columns: {', '.join(spec)})")
            columns = [c for c in columns if c.lower() in spec]
        missing = [c for c, required in spec.items() if required and c not in {x.lower() for x in columns}]
        if missing:
            issues.append(f"{table}: NOT NULL column(s) {', '.join(missing)} are never filled")
        holes = {c: sum(1 for r in rows if r.get(c) is None) for c in columns
                 if spec.get(c.lower()) and any(r.get(c) is None for r in rows)}
        for c, n in holes.items():
            issues.append(f"{table}.{c} is NOT NULL but {n} row(s) leave it None")
        if not columns:
            continue
        for start in range(0, len(rows), _CHUNK):
            chunk = rows[start:start + _CHUNK]
            tuples = ",\n".join("  (" + ", ".join(_sql_value(r.get(c)) for c in columns) + ")" for r in chunk)
            out.append(f"INSERT INTO {name} ({', '.join(c.lower() for c in columns)}) VALUES\n{tuples};")
    return "\n".join(out) + ("\n" if out else ""), issues


def _texty(values: list[Any]) -> bool:
    strings = [v for v in values if isinstance(v, str)]
    return len(strings) >= len(values) * 0.8 and strings and sum(len(s) for s in strings) / len(strings) >= 12


def quality_issues(rows_by_table: dict[str, list[dict[str, Any]]], criteria: list[str]) -> list[str]:
    """Is this data a demonstration someone would believe?"""
    issues: list[str] = []
    counts = {str(t).lower(): len(r) for t, r in rows_by_table.items() if isinstance(r, list)}
    for table, rows in rows_by_table.items():
        if not isinstance(rows, list) or len(rows) < 12:
            continue
        keys = dict.fromkeys(k for r in rows if isinstance(r, dict) for k in r)
        for key in keys:
            values = [r.get(key) for r in rows if isinstance(r, dict)]
            if not _texty(values):
                continue
            distinct = len({str(v).strip().lower() for v in values})
            if distinct < max(6, len(values) * 0.35):
                issues.append(f"{table}.{key}: only {distinct} distinct values across {len(values)} rows — "
                              "write a catalogue of 30+ distinct, realistic entries and vary the wording; "
                              "only deliberate near-duplicate clusters should share a subject")
            most = max((sum(1 for v in values if str(v).strip().lower() == x) for x in
                        {str(v).strip().lower() for v in values}), default=0)
            if most > max(6, len(values) * 0.2):
                issues.append(f"{table}.{key}: one value appears {most} times in {len(values)} rows")
        for key in keys:
            if not (key.endswith("_at") or key.endswith("_date") or key in ("date", "created", "arrived")):
                continue
            days = {str(r.get(key))[:10] for r in rows if isinstance(r, dict) and r.get(key)}
            if len(rows) >= 20 and len(days) < 5:
                issues.append(f"{table}.{key}: {len(rows)} rows fall on only {len(days)} distinct day(s) — "
                              "spread them over the period the brief describes")
    for crit in criteria:
        for n, noun in _AT_LEAST.findall(str(crit)):
            need = int(n)
            word = noun.lower().replace("-", "_")
            if need < 5 or word in _NOT_DATA:
                continue
            stems = {word, word.rstrip("s"), word[:-3] + "y" if word.endswith("ies") else word,
                     word[:-2] if word.endswith("es") else word}
            table = next((t for t in counts if t in stems or t.rstrip("s") in stems), None)
            if table is None:
                table = next((t for t in counts if any(s and (s in t or t in s) for s in stems if len(s) > 3)), None)
            if table is None:
                continue
            if counts[table] < need:
                issues.append(f"the brief asks for at least {need} {word}; rows() returns {counts[table]} for `{table}`")
    return list(dict.fromkeys(issues))


def strip_seed_section(sql: str) -> str:
    i = sql.find(SEED_MARKER)
    return sql if i < 0 else sql[:i].rstrip() + "\n"


def write_seed_section(run_id: str, seed_sql: str) -> None:
    """Replace the platform's section of db/init.sql with these statements."""
    path = workspace_path(run_id) / "db" / "init.sql"
    base = strip_seed_section(path.read_text(encoding="utf-8", errors="replace")) if path.is_file() else ""
    path.write_text(base.rstrip() + "\n\n" + SEED_MARKER + "\n" + seed_sql, encoding="utf-8", newline="\n")


def tables_in(run_id: str) -> dict[str, dict[str, bool]]:
    path = workspace_path(run_id) / "db" / "init.sql"
    if not path.is_file():
        return {}
    return _table_columns(strip_seed_section(path.read_text(encoding="utf-8", errors="replace")))


_RUNNER = (
    "python - <<'PY'\n"
    "import json, sys\n"
    "sys.path.insert(0, 'db')\n"
    "import seed\n"
    "data = seed.rows()\n"
    "print('POIESIS_SEED_JSON')\n"
    "print(json.dumps(data, default=str))\n"
    "PY"
)


async def run_seed_script(run_id: str, timeout: int = 120) -> tuple[dict[str, list[dict[str, Any]]] | None, str]:
    """Run db/seed.py in the sandbox. Returns (rows by table, error text)."""
    result: ExecResult = await run_in_sandbox(run_id, _RUNNER, timeout=timeout, network=False)
    if result.timed_out:
        return None, f"{SEED_SCRIPT} did not finish within {timeout}s — it must run in seconds"
    marker = "POIESIS_SEED_JSON\n"
    if not result.ok or marker not in result.stdout:
        err = (result.stderr or result.stdout).strip()
        lines = [l for l in err.splitlines() if l.strip()][-12:]
        return None, f"{SEED_SCRIPT} failed:\n" + "\n".join(lines)
    payload = result.stdout.split(marker, 1)[1]
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"{SEED_SCRIPT} printed something rows() could not be read from: {exc}"
    if not isinstance(data, dict):
        return None, f"{SEED_SCRIPT}: rows() must return a dict of table -> list of rows"
    return data, ""


def summary(rows_by_table: dict[str, list[dict[str, Any]]]) -> str:
    parts = [f"{t} ({len(r)})" for t, r in rows_by_table.items() if isinstance(r, list) and r]
    return ", ".join(parts) or "no rows"


_TABLENAME = re.compile(r"__tablename__\s*=\s*['\"]([A-Za-z_]\w*)['\"]")


def model_tables(models_py: str) -> list[str]:
    return _TABLENAME.findall(models_py)
