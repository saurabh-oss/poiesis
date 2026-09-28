"""The application's own guide: what it is for, who does what, how a record moves.
Written by Poiesis, and read-only.

It is assembled from what the application is, so it cannot describe something the application
does not do: the roles and the people (domain/policy.py), the lifecycles (domain/workflows.py),
the rules (the catalogue), what each department library says of its process
(`<library>/guide.py`), and what the platform recorded of the brief when it built the
application (`app/guide.json`: what it is for, its stories, its screens).

    GET /api/platform/guide        the guide, for the Guide screen
    GET /api/platform/guide.md     the same as a document, with its diagrams (Mermaid)

The platform keeps the document in the application's repository as docs/USER-GUIDE.md.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from . import rules as rule_registry
from . import workflow as wf
from .context import Actor
from .policy import policy

log = logging.getLogger(__name__)
RECORDED = Path(__file__).resolve().parents[1] / "guide.json"
APP = __package__.rsplit(".", 1)[0]


def recorded() -> dict[str, Any]:
    """What the platform wrote down when it built the application; {} when it wrote nothing."""
    try:
        return json.loads(RECORDED.read_text(encoding="utf-8")) if RECORDED.is_file() else {}
    except (OSError, ValueError):
        return {}


def _libraries() -> list[tuple[str, Any]]:
    from . import LIBRARIES
    out = []
    for name, problem in sorted(LIBRARIES.items()):
        if problem:
            continue
        try:
            out.append((name, importlib.import_module(f"{APP}.{name}.guide")))
        except ModuleNotFoundError:
            continue
        except Exception as exc:  # noqa: BLE001 — a guide is a help; the application works without it
            log.warning("%s/guide.py did not load: %s", name, exc)
    return out


def _tables() -> set[str]:
    from ..db import Base
    return {str(getattr(m.class_, "__tablename__", "")) for m in Base.registry.mappers}


def _words(text: str) -> str:
    return str(text or "").replace("_", " ").strip()


def _may(grants: list[str]) -> dict[str, Any]:
    """A role's permissions in words: what it reads, what it changes."""
    if "*" in grants:
        return {"reads": "everything", "changes": ["everything"], "oversight": ["everything"]}
    reads = "everything" if "*:read" in grants else sorted({_words(g.split(":")[0]) for g in grants if g.endswith(":read")})
    changes: dict[str, set[str]] = {}
    oversight = []
    for g in grants:
        entity, _, action = g.partition(":")
        if action == "read" or not action:
            continue
        if entity in ("audit", "rules", "integrations", "users"):
            continue
        changes.setdefault(_words(entity), set()).add("everything" if action == "*" else _words(action))
    for g, said in (("audit:read", "the audit trail"), ("rules:read", "the business rules"),
                    ("integrations:read", "the integrations"), ("integrations:manage", "retrying and testing connectors")):
        if g in grants:
            oversight.append(said)
    return {"reads": reads, "oversight": oversight,
            "changes": [f"{entity}: {', '.join(sorted(actions))}" if "everything" not in actions else f"{entity}: everything"
                        for entity, actions in sorted(changes.items())]}


def build(actor: Actor | None = None) -> dict[str, Any]:
    p = policy()
    flows = [w.describe() for w in wf.iter_workflows()]
    by_entity = {f["entity"]: f for f in flows}
    labels = dict(p.roles)
    note = recorded()

    roles: dict[str, dict[str, Any]] = {}
    for key, label in p.roles.items():
        roles[key] = {"key": key, "label": label, "people": [], "does": [], "approves": [],
                      "may": _may(list(p.permissions.get(key, []))), "screens": []}
    for person in p.personas:
        for key in person.get("roles", []):
            if key in roles:
                roles[key]["people"].append({k: person.get(k, "") for k in ("full_name", "username", "title", "team")})
    for f in flows:
        states = {s["key"]: s["label"] for s in f["states"]}
        for t in f["transitions"]:
            move = {"workflow": f["title"], "entity": f["entity"], "name": t["name"], "move": t["label"],
                    "from": [states.get(s, _words(s)) for s in t["from"] if s != "*"], "to": states.get(t["to"], _words(t["to"])),
                    "approval": t.get("approval"), "approvers": [labels.get(a, _words(a)) for a in t.get("approvers", [])],
                    "rule": t.get("rule"), "needs_reason": bool(t.get("requires_reason"))}
            for key in t["roles"]:
                if key in roles:
                    roles[key]["does"].append(move)
            for key in t.get("approvers", []):
                if key in roles:
                    roles[key]["approves"].append(move)
    for screen_id, allowed in p.screens.items():
        for key in allowed:
            if key in roles:
                roles[key]["screens"].append(screen_id)

    processes: list[dict[str, Any]] = []
    numbers: list[dict[str, Any]] = []
    uses: list[dict[str, str]] = []
    library_screens: dict[str, str] = {}
    tables = _tables()
    for name, module in _libraries():
        try:
            if hasattr(module, "process"):
                processes += list(module.process(by_entity, tables))
            if hasattr(module, "numbers"):
                numbers += [{**n, "library": name} for n in module.numbers(labels)]
            uses += [{**u, "library": name} for u in getattr(module, "USES", [])]
            if hasattr(module, "screens"):
                library_screens.update(module.screens())
        except Exception as exc:  # noqa: BLE001
            log.warning("the %s library's guide could not be read: %s", name, exc)
    for proc in processes:
        for step in [*proc.get("steps", []), *proc.get("alongside", [])]:
            step["role_labels"] = [labels.get(r, _words(r).capitalize()) for r in step.get("roles", [])]
            step["approver_labels"] = [labels.get(r, _words(r).capitalize()) for r in step.get("approvers", [])]

    catalogue = rule_registry.catalogue()
    me = None
    if actor is not None and actor.kind == "user":
        me = {"name": actor.name, "username": actor.username, "title": actor.title,
              "roles": [{"key": r, "label": labels.get(r, _words(r).capitalize())} for r in actor.roles]}
    return {
        "app": os.getenv("APP_NAME", "") or note.get("app", ""),
        "about": {k: note.get(k) for k in ("purpose", "for", "goal", "built", "increment") if note.get(k)},
        "me": me,
        "roles": [r for r in roles.values() if r["people"] or r["does"] or r["approves"] or r["key"] != "admin"],
        "processes": processes,
        "lifecycles": flows,
        "numbers": numbers,
        "uses": uses,
        "library_screens": library_screens,
        "stories": note.get("stories", []),
        "screens": note.get("screens", []),
        "rules": [{"id": r["id"], "title": r.get("title", ""), "statement": r.get("statement", ""), "kind": r.get("kind", ""),
                   "source": r.get("source", ""), "tested": (r.get("tests") or {}).get("total", 0)} for r in catalogue],
        "platform": [
            {"id": "approvals", "title": "Approvals", "what": "Every decision waiting for you, and the ones you asked for."},
            {"id": "audit_trail", "title": "Audit trail", "what": "Every change, who made it, and what it was before."},
            {"id": "business_rules", "title": "Business rules", "what": "Every rule the application enforces, with its tests."},
            {"id": "integrations", "title": "Integrations", "what": "The systems the application talks to, and what it sent."},
        ],
    }


# --------------------------------------------------------------------------- the document

def _id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", str(text))


def _quote(text: str) -> str:
    return str(text).replace('"', "'").replace("\n", " ")


def _screens_for(step: dict[str, Any], screens: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in screens if s.get("uses") in step.get("uses", [])]


def process_diagram(proc: dict[str, Any]) -> str:
    """The process as a Mermaid flowchart, a lane for each role."""
    lanes: dict[str, list[dict[str, Any]]] = {}
    for step in proc["steps"]:
        lane = (step.get("role_labels") or ["Anyone"])[0]
        lanes.setdefault(lane, []).append(step)
    lines = ["```mermaid", "flowchart LR"]
    for lane, steps in lanes.items():
        lines.append(f'  subgraph {_id(lane)}["{_quote(lane)}"]')
        for s in steps:
            shape = ('{{"' + _quote(s["title"]) + '"}}') if s.get("decides") else ('["' + _quote(s["title"]) + '"]')
            lines.append(f"    {_id(s['key'])}{shape}")
        lines.append("  end")
    keys = [s["key"] for s in proc["steps"]]
    for a, b in zip(keys, keys[1:]):
        lines.append(f"  {_id(a)} --> {_id(b)}")
    lines.append("```")
    return "\n".join(lines)


def lifecycle_diagram(flow: dict[str, Any]) -> str:
    """A record's lifecycle as a Mermaid state diagram."""
    labels = {s["key"]: s["label"] for s in flow["states"]}
    lines = ["```mermaid", "stateDiagram-v2", "  direction LR"]
    for key, label in labels.items():
        lines.append(f'  state "{_quote(label)}" as {_id(key)}')
    lines.append(f"  [*] --> {_id(flow['initial'])}")
    for t in flow["transitions"]:
        target = t["to"]
        for source in t["from"]:
            if source == "*":
                continue
            if t.get("pending") and t["pending"] != source:
                lines.append(f"  {_id(source)} --> {_id(t['pending'])}: {_quote(t['label'])}")
                lines.append(f"  {_id(t['pending'])} --> {_id(target)}: approved")
            else:
                lines.append(f"  {_id(source)} --> {_id(target)}: {_quote(t['label'])}")
    for key in flow.get("final", []):
        lines.append(f"  {_id(key)} --> [*]")
    lines.append("```")
    return "\n".join(lines)


def markdown(guide: dict[str, Any]) -> str:
    app = guide.get("app") or "This application"
    about = guide.get("about") or {}
    screens = guide.get("screens") or []
    titles = {s["id"]: s.get("title", s["id"]) for s in screens}
    out: list[str] = [f"# {app}: user guide", ""]
    out.append("_This guide is written by the application from its own roles, lifecycles, rules and screens. "
               "The same guide is on the **Guide** screen inside the application._")
    out.append("")
    if about.get("purpose"):
        out += ["## What it is for", "", str(about["purpose"]), ""]
    if about.get("increment"):
        out += [str(about["increment"]), ""]

    people = [(r["label"], p) for r in guide["roles"] for p in r["people"]]
    if people:
        out += ["## Signing in", "",
                "Choose a person on the sign-in page. Each holds one role, and sees and may do what that role allows.", "",
                "| Person | Role | |", "|---|---|---|"]
        out += [f"| {p.get('full_name', '')} | {label} | {', '.join(x for x in (p.get('title'), p.get('team')) if x)} |"
                for label, p in people]
        out.append("")

    for proc in guide.get("processes", []):
        out += [f"## The process: {proc['title']}", "", proc.get("about", ""), "", process_diagram(proc), ""]
        for n, step in enumerate(proc["steps"], 1):
            who = ", ".join(step.get("role_labels") or ["Anyone"])
            out.append(f"### {n}. {step['title']}")
            out.append("")
            out.append(f"**Who:** {who}" + (f". **Approved by:** {', '.join(step['approver_labels'])}"
                                           + (", by the amount" if len(step["approver_labels"]) > 1 else "")
                                           if step.get("approver_labels") else ""))
            found = _screens_for(step, screens)
            out.append("")
            out.append("**Where:** " + (", ".join(f"the **{s.get('title', s['id'])}** screen" for s in found) if found
                                         else "_this application has no screen for this step yet_"))
            out += ["", step["what"], ""]
            out += [f"{i}. {line}" for i, line in enumerate(step.get("how", []), 1)]
            if step.get("rules"):
                out += ["", "Rules that decide it: " + ", ".join(f"`{r}`" for r in step["rules"])]
            if step.get("leaves"):
                out += ["", f"_It leaves:_ {step['leaves']}."]
            out.append("")
        if proc.get("alongside"):
            out += ["### Alongside", ""]
            for item in proc["alongside"]:
                found = _screens_for(item, screens)
                out.append(f"- **{item['title']}.** {item['what']}"
                           + (" On: " + ", ".join(s.get("title", s["id"]) for s in found) + "." if found else ""))
            out.append("")

    out += ["## Who does what", ""]
    for r in guide["roles"]:
        if not (r["people"] or r["does"] or r["approves"]):
            continue
        names = ", ".join(p.get("full_name", "") for p in r["people"])
        out.append(f"### {r['label']}" + (f" ({names})" if names else ""))
        out.append("")
        mine = [titles.get(s, s) for s in r.get("screens", [])]
        if mine:
            out.append("Screens: " + ", ".join(mine) + ".")
            out.append("")
        if r["does"]:
            out += ["| Does | To | Moves it | Needs |", "|---|---|---|---|"]
            out += [f"| {m['move']} | {m['workflow']} | {' / '.join(m['from']) or 'any state'} → {m['to']} | "
                    + ("the approval of " + " or ".join(m["approvers"]) if m["approvers"] else
                       "a reason" if m["needs_reason"] else "") + " |" for m in r["does"]]
            out.append("")
        if r["approves"]:
            out.append("Approves: " + "; ".join(sorted({f"{m['move']} ({m['workflow']})" for m in r["approves"]})) + ".")
            out.append("")
        may = r["may"]
        reads = may["reads"] if isinstance(may["reads"], str) else ", ".join(may["reads"]) or "nothing"
        out.append(f"May read {reads}." + (" May change " + "; ".join(may["changes"]) + "." if may["changes"] else "")
                   + (" Sees " + ", ".join(may["oversight"]) + "." if may.get("oversight") else ""))
        out.append("")

    if screens:
        out += ["## The screens", "", "| Screen | What it is for |", "|---|---|"]
        known = guide.get("library_screens", {})
        stories = {s["id"]: s for s in guide.get("stories", [])}
        for s in screens:
            story = stories.get(s.get("story") or "", {})
            what = known.get(s.get("uses") or "", "") or story.get("narrative", "") or s.get("subtitle", "")
            out.append(f"| {s.get('title', s['id'])} | {_quote(what)} |")
        out += [f"| {p['title']} | {p['what']} |" for p in guide.get("platform", [])]
        out.append("")

    if guide.get("lifecycles"):
        out += ["## How a record moves", "",
                "A record's status changes only through the moves below, by the people whose role allows them. "
                "Every move is in the audit trail.", ""]
        roles = {r["key"]: r["label"] for r in guide["roles"]}
        for flow in guide["lifecycles"]:
            out += [f"### {flow['title']}", "", lifecycle_diagram(flow), "",
                    "| Move | From | To | Who | Approved by |", "|---|---|---|---|---|"]
            labels = {s["key"]: s["label"] for s in flow["states"]}
            for t in flow["transitions"]:
                out.append(f"| {t['label']} | {', '.join(labels.get(s, s) for s in t['from'])} | {labels.get(t['to'], t['to'])} | "
                           f"{', '.join(roles.get(r, _words(r)) for r in t['roles'])} | "
                           f"{' or '.join(roles.get(r, _words(r)) for r in t.get('approvers', []))} |")
            out.append("")

    if guide.get("numbers"):
        out += ["## The numbers this organisation works to", "", "| | | Rule |", "|---|---|---|"]
        out += [f"| {n['label']} | {n['value']} | {('`' + n['rule'] + '`') if n.get('rule') else ''} |" for n in guide["numbers"]]
        out.append("")

    if guide.get("rules"):
        out += ["## The rules", "", "| Rule | | Tests |", "|---|---|---|"]
        out += [f"| `{r['id']}` | {_quote(r['title'])} | {r['tested'] or ''} |" for r in guide["rules"]]
        out.append("")
    return "\n".join(out).rstrip() + "\n"
