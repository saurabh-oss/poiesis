"""What the platform writes down for an application's own guide, and the guide as a document.

An application built by Poiesis explains itself to the people who use it. An enterprise
application writes its guide from what it is (its roles, its people, its lifecycles, its rules;
the kernel's guide.py) and shows it on its Guide screen. What it cannot know by itself is what
the platform knew when it built it: what the brief was for, which stories are in the increment
and which screen delivers each. That is recorded here, in `backend/app/guide.json`, every time
the application is deployed.

Once the application runs, its guide is fetched as a document and kept in its repository as
`docs/USER-GUIDE.md`. An application without the kernel gets a plainer document, written here
from the same record.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..db import Artifact, session
from . import overlays
from .checks import stories_in, story_screens
from .repo import workspace_path

RECORD = "backend/app/guide.json"
DOCUMENT = "docs/USER-GUIDE.md"

_TITLE = re.compile(r"""\btitle\s*:\s*(["'`])(.+?)\1""")
_SUBTITLE = re.compile(r"""\bsubtitle\s*:\s*(["'`])(.+?)\1""")


def _latest(run_id: str, kind: str) -> dict[str, Any]:
    with session() as s:
        row = (s.query(Artifact).filter(Artifact.run_id == run_id, Artifact.kind == kind)
               .order_by(Artifact.version.desc()).first())
        return dict(row.body) if row is not None and isinstance(row.body, dict) else {}


def _used(source: str) -> str:
    """Which of a department library's screens a screen file is, as the library names it."""
    for name in overlays.active():
        module = overlays.module(name, "screens")
        if module is not None and hasattr(module, "used"):
            try:
                found = module.used(source)
            except Exception:  # noqa: BLE001 — a name for the guide, nothing depends on it
                found = ""
            if found:
                return str(found)
    return ""


def screens(run_id: str) -> list[dict[str, Any]]:
    """The application's screens as they stand in the workspace."""
    out = []
    for path in story_screens(run_id):
        source = path.read_text(encoding="utf-8", errors="replace")
        title, subtitle = _TITLE.search(source), _SUBTITLE.search(source)
        ids = stories_in(source)
        out.append({"id": path.stem, "title": title.group(2) if title else path.stem.replace("_", " ").capitalize(),
                    "subtitle": subtitle.group(2) if subtitle else "", "story": ids[0] if ids else "",
                    "stories": ids, "uses": _used(source)})
    return out


def record(run_id: str, title: str = "") -> dict[str, Any]:
    """What the platform knows of the application that the application does not."""
    vision, backlog, sprint = _latest(run_id, "vision"), _latest(run_id, "backlog"), _latest(run_id, "sprint")
    report = _latest(run_id, "test_report")
    found = screens(run_id)
    delivered = {s for screen in found for s in screen["stories"]}
    wanted = [e.get("id") for e in sprint.get("stories", [])]
    dropped = {r.get("story_id") for r in report.get("stories", []) if r.get("status") == "dropped"}
    every = {s.get("id"): s for s in backlog.get("stories", [])}
    chosen = [sid for sid in wanted if sid in every and sid not in dropped] or sorted(delivered & set(every))
    stories = [{"id": sid, "title": every[sid].get("title", ""), "narrative": every[sid].get("narrative", ""),
                "criteria": list(every[sid].get("acceptance_criteria") or [])[:6], "delivered": sid in delivered}
               for sid in chosen]
    later = [s.get("title", "") for sid, s in every.items() if sid not in chosen]
    increment = ""
    if stories and later:
        increment = (f"This is an increment: {len(stories)} of the {len(every)} stories asked for. "
                     "Still to come: " + "; ".join(t for t in later[:8] if t) + ("; and more." if len(later) > 8 else "."))
    return {
        "app": str(vision.get("product_name") or title or ""),
        "purpose": str(vision.get("problem_statement") or "").strip(),
        "for": [str(u.get("persona")) for u in vision.get("target_users", []) if isinstance(u, dict) and u.get("persona")],
        "goal": str(sprint.get("sprint_goal") or "").strip(),
        "increment": increment,
        "stories": stories,
        "screens": found,
    }


def write(run_id: str) -> bool:
    """Keep backend/app/guide.json as the record stands. Returns whether it changed."""
    root = workspace_path(run_id)
    if not (root / "backend" / "app").is_dir():
        return False
    body = json.dumps(record(run_id), indent=2, ensure_ascii=False) + "\n"
    path = root / RECORD
    if path.is_file() and path.read_text(encoding="utf-8", errors="replace") == body:
        return False
    path.write_text(body, encoding="utf-8", newline="\n")
    return True


def plain(note: dict[str, Any]) -> str:
    """The guide of an application without the kernel: what it is for, its screens, its stories."""
    out = [f"# {note.get('app') or 'This application'}: user guide", ""]
    if note.get("purpose"):
        out += ["## What it is for", "", note["purpose"], ""]
    if note.get("increment"):
        out += [note["increment"], ""]
    if note.get("for"):
        out += ["## Who it is for", "", *[f"- {who}" for who in note["for"]], ""]
    stories = {s["id"]: s for s in note.get("stories", [])}
    if note.get("screens"):
        out += ["## The screens", "", "Every screen is in the navigation on the left.", "", "| Screen | What it is for |", "|---|---|"]
        for s in note["screens"]:
            what = (stories.get(s.get("story") or "") or {}).get("narrative") or s.get("subtitle") or ""
            out.append(f"| {s['title']} | {str(what).replace('|', '/')} |")
        out.append("")
    if stories:
        out += ["## What it does", ""]
        for s in stories.values():
            out += [f"### {s['title']}", "", s.get("narrative", ""), ""]
            out += [f"- {c}" for c in s.get("criteria", [])]
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def keep(run_id: str, text: str) -> bool:
    """Keep the guide as a document in the application's repository. Returns whether it changed."""
    text = (text or "").replace("\r\n", "\n").strip() + "\n"
    if not text.startswith("# "):
        return False
    path = workspace_path(run_id) / DOCUMENT
    if path.is_file() and path.read_text(encoding="utf-8", errors="replace") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return True
