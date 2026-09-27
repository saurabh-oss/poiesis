"""Standard entities: the tables an overlay defines, written by the platform, not by a model.

A department's overlay knows what its records look like (scaffolds/_overlays/finance/…
/standard.py: supplier, purchase_order, invoice…). Asking a model to write sixteen tables
it has been shown, three times over (models.py, init.sql, schemas.py), spends its reply on
copying and gets a column wrong somewhere; the overlay's data, analytics, lifecycles and
dashboards then read a column that is not there. So:

- `wanted(text)` reads which standard entities the brief, the backlog and the architecture
  speak of (and the ones those cannot do without);
- the Foundation Developer is told they exist and writes only the brief's own entities,
  referring to a standard one as `<table>_id`;
- `merge(files, tables)` puts the standard definitions into the three files it returned.
  Where it wrote a standard entity itself, the platform's definition stands, with any
  column of its own it added kept at the end.

Nothing here calls a model.
"""
from __future__ import annotations

import re
from types import ModuleType
from typing import Any

from . import overlays

MODELS, SQL, SCHEMAS = "backend/app/models.py", "db/init.sql", "backend/app/schemas.py"
SECTION = "standard entities of the {name} library, written by the platform"

_CLASS = re.compile(r"^class (\w+)\(([^)]*)\):[^\n]*\n(?:(?:[ \t]+[^\n]*|[ \t]*)\n)*", re.M)
_TABLENAME = re.compile(r'__tablename__\s*=\s*["\'](\w+)["\']')
_CREATE = re.compile(r"(?:--[^\n]*\n)*CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\((.*?)\)\s*;[ \t]*\n?", re.S | re.I)
_ATTRIBUTE = re.compile(r"^\s{4}(\w+)\s*:\s*Mapped\[[^\n]*$", re.M)
_FIELD = re.compile(r"^\s{4}(\w+)\s*:\s*[^\n]*$", re.M)


def wanted(text: str, names: list[str] | None = None) -> dict[str, list[str]]:
    """Overlay -> the standard entities of it that the text speaks of."""
    out: dict[str, list[str]] = {}
    for name, mod in overlays.standards(names):
        if hasattr(mod, "needed"):
            tables = list(mod.needed(text))
            if tables:
                out[name] = tables
    return out


def describe(chosen: dict[str, list[str]]) -> str:
    """For the Foundation Developer: what the platform writes, so it writes the rest."""
    if not chosen:
        return ""
    parts = []
    for name, tables in chosen.items():
        mod = overlays.module(name, "standard")
        if mod is None:
            continue
        parts.append(mod.summary(tables))
    if not parts:
        return ""
    return (
        "\n\nSTANDARD ENTITIES — THE PLATFORM WRITES THESE TABLES ITSELF, in all three files, after your reply, with "
        "exactly these names and columns (`?` marks an optional column). Do NOT write them: they are not in your "
        "files. Write only the entities the brief needs beyond them. Refer to a standard entity from your own with "
        "an Integer column named `<table>_id` (`invoice_id`, `supplier_id`). When the brief needs a column a "
        "standard entity lacks, write that entity's class, table and schemas with ONLY `id` and the columns you "
        "add: the platform adds yours to its own.\n" + "\n".join(parts) + "\n"
        "The library's demonstration data, rules, lifecycles, analytics and dashboards read these columns; a "
        "table of your own that repeats one of them under another name (`vendor` for `supplier`, `bill` for "
        "`invoice`) would be empty of all that.\n")


def _split_top(text: str) -> list[str]:
    """The parts of a CREATE TABLE body, split at the commas that are not inside brackets."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return [re.sub(r"--[^\n]*", "", p).strip() for p in out if re.sub(r"--[^\n]*", "", p).strip()]


def _classes(source: str) -> list[tuple[str, str, str, tuple[int, int]]]:
    """(class name, bases, body text, span) for every top-level class."""
    return [(m.group(1), m.group(2), m.group(0), m.span()) for m in _CLASS.finditer(source)]


def _cut(source: str, spans: list[tuple[int, int]]) -> str:
    for start, end in sorted(spans, reverse=True):
        source = source[:start] + source[end:]
    return re.sub(r"\n{4,}", "\n\n\n", source)


def _own_lines(block: str, pattern: re.Pattern[str], known: set[str]) -> list[str]:
    """The lines of a block that declare something the standard does not have."""
    out = []
    for m in pattern.finditer(block):
        name = m.group(1)
        if name not in known and name not in ("id", "model_config") and not name.startswith("__"):
            out.append(m.group(0).strip())
    return out


def merge(files: dict[str, str], tables: list[str], mod: ModuleType, name: str = "library",
          ) -> tuple[dict[str, str], list[str]]:
    """The three files with the standard entities `tables` in them. Returns the files and what was done."""
    out = dict(files)
    notes: list[str] = []
    if not tables:
        return out, notes
    wanted_tables = [t for t in getattr(mod, "ORDER", list(mod.ENTITIES)) if t in tables]
    known = {t: set(mod.column_names(t)) for t in wanted_tables}
    classes = {mod.class_name(t): t for t in wanted_tables}
    extras: dict[str, dict[str, list[str]]] = {t: {"model": [], "sql": [], "schema": []} for t in wanted_tables}
    banner = SECTION.format(name=name)

    # models.py
    models = out.get(MODELS, "")
    if models:
        spans = []
        for cls, _, block, span in _classes(models):
            table = (_TABLENAME.search(block) or [None, None])[1] if _TABLENAME.search(block) else None
            table = table if table in known else classes.get(cls)
            if table in known:
                extras[table]["model"] = _own_lines(block, _ATTRIBUTE, known[table])
                spans.append(span)
        models = _cut(models, spans).rstrip("\n")
        if banner in models:
            models = models[: models.index(f"# ---- {banner}")].rstrip("\n")
        head = ("import datetime as dt  # noqa: F811\n\nfrom sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, Text  "
                "# noqa: F811\nfrom sqlalchemy.orm import Mapped, mapped_column  # noqa: F811\n\n\n"
                "def _now() -> dt.datetime:\n    return dt.datetime.now(dt.timezone.utc)\n")
        body = "\n\n\n".join(mod.model_class(t, extras[t]["model"]) for t in wanted_tables)
        out[MODELS] = f"{models}\n\n\n# ---- {banner} ----\n{head}\n\n{body}\n"

    # db/init.sql
    sql = out.get(SQL, "")
    if sql:
        spans = []
        for m in _CREATE.finditer(sql):
            table = m.group(1).lower()
            if table in known:
                for part in _split_top(m.group(2)):
                    column = part.split()[0].strip('"').lower() if part.split() else ""
                    if column and column not in known[table] and column.upper() not in (
                            "PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK"):
                        extras[table]["sql"].append(part)
                spans.append(m.span())
        sql = _cut(sql, spans).rstrip("\n")
        if banner in sql:
            sql = sql[: sql.index(f"-- ---- {banner}")].rstrip("\n")
        body = "\n\n".join(mod.create_table(t, extras[t]["sql"]) for t in wanted_tables)
        out[SQL] = f"{sql}\n\n-- ---- {banner} ----\n{body}\n"

    # schemas.py
    schemas = out.get(SCHEMAS, "")
    if schemas:
        spans = []
        names = {f"{cls}{suffix}": table for cls, table in classes.items() for suffix in ("Create", "Out", "Update", "Base")}
        for cls, _, block, span in _classes(schemas):
            table = names.get(cls)
            if table in known:
                for line in _own_lines(block, _FIELD, known[table]):
                    if line.split(":")[0] not in {e.split(":")[0] for e in extras[table]["schema"]}:
                        field = line if "=" in line else line + " | None = None" if "None" not in line else line + " = None"
                        extras[table]["schema"].append(field)
                spans.append(span)
        schemas = _cut(schemas, spans).rstrip("\n")
        if banner in schemas:
            schemas = schemas[: schemas.index(f"# ---- {banner}")].rstrip("\n")
        head = "import datetime as dt  # noqa: F811\n\nfrom pydantic import BaseModel, ConfigDict  # noqa: F811\n"
        body = "\n\n\n".join(mod.schema_classes(t, extras[t]["schema"]) for t in wanted_tables)
        out[SCHEMAS] = f"{schemas}\n\n\n# ---- {banner} ----\n{head}\n\n{body}\n"

    added = {t: e["model"] for t, e in extras.items() if e["model"]}
    notes.append(f"{len(wanted_tables)} standard {name} entities written by the platform: " + ", ".join(wanted_tables))
    for table, lines in added.items():
        notes.append(f"{table}: kept the application's own column(s) " + ", ".join(line.split(":")[0] for line in lines))
    return out, notes


def apply(files: dict[str, Any], chosen: dict[str, list[str]]) -> tuple[dict[str, Any], list[str]]:
    """merge() for every overlay that has standard entities to write."""
    notes: list[str] = []
    out = {k: v for k, v in files.items()}
    for name, tables in chosen.items():
        mod = overlays.module(name, "standard")
        if mod is None or not all(isinstance(out.get(f), str) and out.get(f) for f in (MODELS, SQL, SCHEMAS)):
            continue
        out, said = merge(out, tables, mod, name)
        notes += said
    return out, notes


def class_names(models_source: str) -> dict[str, str]:
    """Table -> the class that maps it, read from models.py."""
    out = {}
    for cls, _, block, _ in _classes(models_source):
        m = _TABLENAME.search(block)
        if m:
            out[m.group(1)] = cls
    return out


def gaps(tables: dict[str, Any], names: list[str] | None = None) -> list[str]:
    """What the data model lacks of the standard entities it has, overlay by overlay."""
    out: list[str] = []
    for _, mod in overlays.standards(names):
        if hasattr(mod, "gaps"):
            out += list(mod.gaps(tables))
    return out
