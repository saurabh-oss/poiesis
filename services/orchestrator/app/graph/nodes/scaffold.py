"""Stage: materialise a working application skeleton before any feature code.

This node makes no model calls. That is the point of it.

Before this stage existed, the Developer was asked to invent a topology and
implement a story in the same breath, under a prompt that forbids speculative
work — so it produced a single module, no server, and no way to run anything. A
14B model is also at its worst on boilerplate it has to recall verbatim.

Rendering a template instead means the application boots on day one, costs no
tokens, and reduces the Developer's job to filling named slots: a router in
backend/app/routers/, a table in models.py and init.sql, a screen in
frontend/screens/.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from ...config import archetype, scaffold_root
from ...events import emit
from ...workspace import repo
from ...workspace.checks import regenerate_registry
from ..state import RunState
from ..store import save_artifact, set_stage

# Files copied byte-for-byte. Everything else is read as UTF-8 and substituted.
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".pdf"}

# Files the Developer may not touch. The prompt says so too, but a 14B model will
# cheerfully rewrite main.py to "fix" a failing test, and taking the health
# endpoint or the compose topology with it turns a code defect into an
# undeployable increment. The prompt is guidance; this is the guarantee.
#
# The frontend shell joined this list after a released app threw "api is not
# defined" on load: a story rewrote the single shared app.js and deleted the
# helper it then called. Stories now add their own files (a router, a screen)
# and the shared plumbing that loads them cannot be edited at all.
PROTECTED = (
    "docker-compose.yml",
    "conftest.py",
    "backend/Dockerfile",
    "backend/app/main.py",
    "backend/app/db.py",
    "backend/app/routes.py",
    "backend/app/routers/__init__.py",
    "backend/app/routers/examples.py",
    "db/Dockerfile",
    "frontend/Dockerfile",
    "frontend/nginx.conf",
    "frontend/index.html",
    "frontend/app.js",
    "frontend/styles.css",
    "frontend/screens/index.js",
    "frontend/screens/example.js",
    "tests/conftest.py",
    "tests/test_scaffold_smoke.py",
    "tests/test_platform_endpoints.py",
)

# Platform-owned files every workspace must have. One bootstrapped before a file
# existed gets it at the start of its next build round, the way deploy upgrades
# an old compose file, so an in-flight run benefits from a new check.
PLATFORM_FILES = ("tests/test_platform_endpoints.py",)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "poiesis-app"


def render(text: str, values: dict[str, str]) -> str:
    """Deliberately not a template engine.

    The scaffold contains JavaScript, CSS and SQL, all full of braces that a real
    templating language would try to interpret. Plain replacement of an explicit
    token set cannot misfire on generated code.
    """
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def materialise(template_dir: Path, target: Path, values: dict[str, str]) -> list[str]:
    written: list[str] = []
    for source in sorted(template_dir.rglob("*")):
        if not source.is_file():
            continue
        rel = source.relative_to(template_dir)
        # A bytecode cache left in the template by a local import is not part of
        # the skeleton, and reading it as UTF-8 would fail the whole bootstrap.
        if "__pycache__" in rel.parts or source.suffix in (".pyc", ".pyo"):
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix.lower() in BINARY_SUFFIXES:
            shutil.copyfile(source, dest)
        else:
            body = source.read_text(encoding="utf-8")
            dest.write_text(render(body, values), encoding="utf-8", newline="\n")
        written.append(rel.as_posix())
    return written


def refresh_platform_files(run_id: str, state: RunState) -> list[str]:
    """Copy in any platform-owned file the workspace is missing. Returns what was added."""
    template_dir = scaffold_root() / (chosen_archetype(state).get("scaffold") or "web-app")
    root = repo.workspace_path(run_id)
    added: list[str] = []
    for rel in PLATFORM_FILES:
        source, dest = template_dir / rel, root / rel
        if source.is_file() and not dest.exists() and dest.parent.is_dir():
            shutil.copyfile(source, dest)
            added.append(rel)
    return added


def chosen_archetype(state: RunState) -> dict[str, Any]:
    """Whatever the Architect declared, validated against the pack.

    config.archetype() falls back to the pack default for an unknown name, so an
    agent that invents one degrades to a working application instead of halting
    the run.
    """
    declared = (state.get("architecture") or {}).get("archetype")
    return archetype(declared if isinstance(declared, str) else None)


async def bootstrap(state: RunState) -> RunState:
    """Node name is a verb: LangGraph reserves state keys, and `scaffold` is one."""
    run_id = state["run_id"]
    await set_stage(run_id, "scaffold")

    arch = chosen_archetype(state)
    project = (state.get("vision") or {}).get("product_name") or state.get("title") or run_id
    values = {
        "project_name": project,
        "project_slug": slugify(project),
        "description": (state.get("vision") or {}).get("value_proposition", "")
        or "Generated by Poiesis.",
    }

    template_dir = scaffold_root() / (arch.get("scaffold") or "web-app")
    if not template_dir.is_dir():
        fallback = scaffold_root() / "web-app"
        await emit(
            run_id,
            f"No scaffold template '{arch.get('scaffold')}'; falling back to web-app",
            agent="scaffold", stage="scaffold", level="warn",
        )
        template_dir = fallback

    repo.init_workspace(run_id)
    written = materialise(template_dir, repo.workspace_path(run_id), values)
    regenerate_registry(run_id)
    sha = repo.commit(run_id, f"chore(scaffold): {arch['name']} skeleton for {project}")

    services = [s.get("name") for s in arch.get("services", []) if s.get("name")]
    await emit(
        run_id,
        f"Scaffolded a {arch['name']} in {len(written)} files "
        f"({', '.join(services) or 'no services'}) — the app boots before any feature code",
        agent="scaffold", stage="scaffold",
        data={"archetype": arch["name"], "files": written, "commit": sha,
              "services": arch.get("services", []),
              "definition_of_deployable": arch.get("definition_of_deployable", [])},
    )

    record = {
        "archetype": arch["name"],
        "description": arch.get("description", ""),
        "entrypoint": arch.get("entrypoint", ""),
        "services": arch.get("services", []),
        "definition_of_deployable": arch.get("definition_of_deployable", []),
        "files": written,
        "protected": [p for p in PROTECTED if p in written],
        "commit": sha,
    }
    await save_artifact(run_id, "scaffold", "scaffold", record)
    return {"scaffold": record}
