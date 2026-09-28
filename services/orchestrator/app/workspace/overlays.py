"""Overlays: what a pack lays over the scaffold, and what each one tells the platform about itself.

An overlay is a directory, `scaffolds/_overlays/<name>/`, copied over the rendered
scaffold when the pack's `build.overlays` names it. The enterprise overlay brings the
kernel and the connectors; a department's overlay (finance, …) brings that department's
library: its rules, workflows, standard entities, demonstration data, connectors and
dashboard kit. Its `overlay.yaml` says what the platform needs to know, so adding a
department is adding a directory, not editing the orchestrator:

    name: finance
    title: Finance and procurement library
    requires: [enterprise]
    owned:                       # platform-owned: stories may not edit them, and a run in
      dirs: [backend/app/finance/]           # flight gets their fixes on its next round
      files: [frontend/finance.js, …]
    prompts:                     # added to an agent's prompt, by who reads it
      architect: prompts/architect.md
      foundation: prompts/foundation.md
      domain: prompts/domain.md
      data: prompts/data.md
      developer: prompts/developer.md
    standard: backend/app/finance/standard.py    # ENTITIES, summary(), gaps(): the entities it expects
    demo: backend/app/finance/demo.py            # rows(tables, today=): data for those entities
    screens: backend/app/finance/screens.py      # suggest(story, tables): its screen nearest a story
    library_tests: [tests/test_finance_library.py]
    reference: [[frontend/screens/example_finance.js, 3400]]     # worked examples shown to the Developer
    settings: [ERP_, FISCAL_, FINANCE_, BASE_CURRENCY]           # APPS_<these> reach the app's environment
    components: |                # what the Architect is told every app of the pack already has
      - finance library: …

`overlay.yaml` and `prompts/` are about the overlay; they are not copied into applications.
A prompt file may use {{standard_entities}}, which is replaced by the overlay's entities.
"""
from __future__ import annotations

import importlib.util
import sys
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from ..config import pack, scaffold_root

ROOT = "_overlays"
MANIFEST = "overlay.yaml"
META = (MANIFEST, "prompts/", "README.md")

# What the enterprise overlay owned before overlays described themselves; still the
# answer for an overlay without a manifest.
DEFAULT_OWNED = {"dirs": ["backend/app/kernel/", "backend/app/connectors/"],
                 "files": ["frontend/platform.js", "frontend/platform.css"]}
EXAMPLE_PREFIX = "example"


def root(name: str) -> Path:
    return scaffold_root() / ROOT / name


def active() -> list[str]:
    """The overlays of the current pack that exist, in the order they are laid."""
    names = pack().get("build", {}).get("overlays") or []
    return [n for n in names if isinstance(n, str) and root(n).is_dir()]


@lru_cache(maxsize=32)
def _read(path: str, stamp: float) -> dict[str, Any]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def manifest(name: str) -> dict[str, Any]:
    path = root(name) / MANIFEST
    if not path.is_file():
        return {"name": name, "owned": DEFAULT_OWNED} if name == "enterprise" else {"name": name}
    return {"name": name, **_read(str(path), path.stat().st_mtime)}


def is_meta(rel: str) -> bool:
    """A file that describes the overlay rather than belonging to the application."""
    rel = rel.replace("\\", "/").lstrip("./")
    return any(rel == m or (m.endswith("/") and rel.startswith(m)) for m in META)


def _clean(rel: str) -> str:
    rel = rel.replace("\\", "/")
    return rel[2:] if rel.startswith("./") else rel


def owned_by(name: str, rel: str) -> bool:
    rel = _clean(rel)
    own = manifest(name).get("owned") or {}
    return rel in (own.get("files") or []) or any(rel.startswith(d) for d in own.get("dirs") or [])


def owned(rel: str, names: list[str] | None = None) -> bool:
    """Platform-owned through an overlay: stories may not write it."""
    return any(owned_by(n, rel) for n in (names if names is not None else active()))


def text(name: str, rel: str) -> str:
    path = root(name) / rel
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def module(name: str, key: str) -> ModuleType | None:
    """An overlay's module named in its manifest (`standard`, `demo`), loaded from the template.

    From the template, not a workspace: it is platform code, the same for every run, and a
    workspace is where models write. Its directory joins the import path while it loads, so
    `demo.py` finds the `standard.py` beside it. Reloaded when the file changes.
    """
    rel = manifest(name).get(key)
    path = root(name) / str(rel) if rel else None
    if path is None or not path.is_file():
        return None
    return _load(str(path), path.stat().st_mtime, f"poiesis_overlay_{name}_{key}")


@lru_cache(maxsize=32)
def _load(path: str, stamp: float, alias: str) -> ModuleType | None:
    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    folder = str(Path(path).parent)
    # A sibling imported by its bare name (`import standard`) must be this overlay's, not
    # another's left in sys.modules: take it out for the duration, and put it back.
    siblings = {p.stem for p in Path(folder).glob("*.py")}
    parked = {n: sys.modules.pop(n) for n in list(sys.modules) if n in siblings}
    sys.path.insert(0, folder)
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(folder)
        for n in siblings:
            sys.modules.pop(n, None)
        sys.modules.update(parked)
    return mod


def standards(names: list[str] | None = None) -> list[tuple[str, ModuleType]]:
    """(overlay, its standard-entities module) for every overlay that has one."""
    out = []
    for n in (names if names is not None else active()):
        mod = module(n, "standard")
        if mod is not None and hasattr(mod, "ENTITIES"):
            out.append((n, mod))
    return out


def standard_tables(names: list[str] | None = None) -> dict[str, str]:
    """Every standard entity of the active overlays: table -> the overlay it belongs to."""
    return {table: n for n, mod in standards(names) for table in mod.ENTITIES}


def prompt(slot: str, names: list[str] | None = None) -> str:
    """What the active overlays add to an agent's prompt: architect, product, foundation,
    domain, data or developer. "" when none of them has anything to say."""
    parts = []
    for n in (names if names is not None else active()):
        rel = (manifest(n).get("prompts") or {}).get(slot)
        body = text(n, str(rel)).strip() if rel else ""
        if not body:
            continue
        if "{{standard_entities}}" in body:
            mod = module(n, "standard")
            body = body.replace("{{standard_entities}}", mod.summary() if mod is not None and hasattr(mod, "summary") else "")
        parts.append(body)
    return ("\n\n" + "\n\n".join(parts) + "\n") if parts else ""


def components(names: list[str] | None = None) -> str:
    """For the Architect: what every application of the pack already has, beyond the kernel."""
    lines = [str(manifest(n).get("components") or "").strip() for n in (names if names is not None else active())]
    return "\n".join(line for line in lines if line)


def library_tests(names: list[str] | None = None) -> list[str]:
    """Test files an overlay ships that prove its own rules; they run with the domain's."""
    out: list[str] = []
    for n in (names if names is not None else active()):
        out += [str(t) for t in manifest(n).get("library_tests") or [] if (root(n) / str(t)).is_file()]
    return out


def references(names: list[str] | None = None) -> list[tuple[str, int]]:
    """Worked examples an overlay ships for the Developer: (workspace path, characters to show)."""
    out: list[tuple[str, int]] = []
    for n in (names if names is not None else active()):
        for item in manifest(n).get("reference") or []:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                out.append((str(item[0]), int(item[1])))
            elif isinstance(item, str):
                out.append((item, 2000))
    return out


def screen_for(story: dict[str, Any], tables: Any = (), names: list[str] | None = None) -> dict[str, Any] | None:
    """The screen an overlay's library has for a story, the nearest of them all: a whole file
    that works as it stands ({"kind", "name", "title", "file", "why", "score", "content", "overlay"}).
    None when no library has one, or the story is not clearly any of theirs."""
    best: dict[str, Any] | None = None
    for n in (names if names is not None else active()):
        mod = module(n, "screens")
        if mod is None or not hasattr(mod, "suggest"):
            continue
        try:
            found = mod.suggest(story, list(tables or ()))
        except Exception:  # noqa: BLE001 — a suggestion is a help; without one the story is built as any other
            found = None
        if found and found.get("content") and (best is None or found.get("score", 0) > best.get("score", 0)):
            best = {**found, "overlay": n}
    return best


def settings_prefixes(names: list[str] | None = None) -> tuple[str, ...]:
    """Environment settings (APPS_<prefix>…) the overlays' code reads in a deployed application."""
    out: list[str] = []
    for n in (names if names is not None else active()):
        out += [str(s) for s in manifest(n).get("settings") or []]
    return tuple(dict.fromkeys(out))


def is_example_screen(filename: str) -> bool:
    """example.js, and an overlay's example_<name>.js: references, not part of a delivered application."""
    stem = filename[:-3] if filename.endswith(".js") else filename
    return stem == EXAMPLE_PREFIX or stem.startswith(EXAMPLE_PREFIX + "_")


def demo_rows(tables: dict[str, Any], today: Any = None, names: list[str] | None = None,
              ) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Demonstration data the overlays bring for their standard entities among `tables`.

    `tables` maps a table to its columns (any iterable, or {column: required}). Returns the
    rows by table, in an order every reference resolves in, and what went wrong: an overlay
    whose generator fails is reported and left out, and the Data Designer writes those tables.
    """
    rows: dict[str, list[dict[str, Any]]] = {}
    notes: list[str] = []
    shape = {str(t): [str(c) for c in cols] for t, cols in tables.items()}
    for n in (names if names is not None else active()):
        mod = module(n, "demo")
        if mod is None or not hasattr(mod, "rows"):
            continue
        try:
            made = mod.rows(shape, today=today)
        except Exception as exc:  # noqa: BLE001 — a generator that fails must not fail the run
            notes.append(f"the {n} overlay's demonstration data could not be generated ({type(exc).__name__}: {exc})")
            continue
        for table, data in made.items():
            if table in shape and table not in rows and data:
                rows[table] = data
    return rows, notes
