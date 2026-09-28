"""Which of the library's screens a story is nearest to. Written by Poiesis, and read-only.

The kit (frontend/finance.js) has a screen for most of what a finance or procurement story
asks for: eight dashboards people read figures on (`fin.blueprints`) and eight work screens
people work from (`fin.worklists`). At the build stage the platform asks, story by story,

    suggest(story, tables) -> {"kind", "name", "title", "icon", "file", "why", "score", "content"} | None

and shows the Developer the answer as the screen to start from: a whole file that works as it
stands, to change where the story needs something of its own. If the Developer's own screen
still fails its checks when its repairs are spent, the platform puts this one in its place, so
the story ships a screen that works. Nothing here reads an application: it is words and a
template, and it imports nothing but the standard library.

    story    {"id": "S9", "title": "Confirm receipt of goods", "narrative": "…", "acceptance_criteria": ["…"]}
    tables   the tables the application has; a screen whose records it lacks is not suggested
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

# A story says what it is in its title first: a word there counts three times.
TITLE, ELSEWHERE = 3, 1
# Below this, the story is not clearly any of the library's screens, and none is suggested:
# one strong word in the title is enough, one weak word is not.
ENOUGH = 7

# name -> (title, icon, the records it needs (any of them), its words and how much each says)
WORKLISTS: dict[str, tuple[str, str, tuple[str, ...], dict[str, int]]] = {
    "requisitions": ("Requisitions", "inbox", ("requisition",), {
        "requisition": 3, "purchase request": 3, "my requests": 3, "raise": 2, "request": 1, "submit": 1, "draft": 1}),
    "approvals": ("Approval queue", "shield", ("requisition", "purchase_order", "invoice", "payment_run", "budget_change"), {
        "approv": 3, "reject": 3, "queue": 2, "decision": 2, "sign off": 2, "sign-off": 2, "authoris": 2, "authoriz": 2,
        "awaiting": 1, "pending": 1, "delegation": 1}),
    "ordering": ("Ordering", "cart", ("purchase_order",), {
        "purchase order": 3, "from approved requisition": 3, "raise order": 3, "create order": 3, "send to supplier": 3,
        "to the supplier": 2, "buyer": 2, "order": 1, "po ": 1}),
    "receiving": ("Goods in", "truck", ("purchase_order",), {
        "receipt": 3, "receive": 3, "goods": 3, "grn": 3, "deliver": 2, "received": 2, "warehouse": 1}),
    "invoices": ("Invoice desk", "layers", ("invoice",), {
        "invoice": 3, "three-way": 3, "three way": 3, "3-way": 3, "match": 2, "exception": 2, "accounts payable": 2,
        "hold": 1, "held": 1}),
    "paymentRuns": ("Payment runs", "dollar", ("payment_run",), {
        "payment run": 4, "pay run": 4, "remittance": 2, "release payment": 3, "payment": 2, "bacs": 2, "treasury": 1}),
    "suppliers": ("Supplier list", "building", ("supplier",), {
        "onboard": 3, "supplier": 2, "vendor": 2, "approved supplier": 2, "suspend": 2, "due diligence": 2}),
    "contracts": ("Contracts", "file", ("contract",), {
        "contract": 3, "renew": 3, "expir": 2, "notice period": 2, "terminat": 1}),
}

DASHBOARDS: dict[str, tuple[str, str, tuple[str, ...], dict[str, int]]] = {
    "executive": ("Executive summary", "dollar", ("invoice", "purchase_order"), {
        "executive": 3, "cfo": 2, "finance director": 2, "summary": 2, "overview": 2, "at a glance": 2, "headline": 2}),
    "spend": ("Spend analysis", "pie", ("invoice",), {
        "spend": 3, "by category": 2, "by supplier": 2, "by cost cent": 2, "where the money": 2, "analysis": 1}),
    "budget": ("Budget control", "chart", ("budget_line",), {
        "budget": 3, "variance": 2, "forecast": 2, "overspen": 2, "against actual": 2, "vs actual": 2, "actual": 1}),
    "payables": ("Accounts payable", "inbox", ("invoice",), {
        "payable": 3, "ageing": 3, "aging": 3, "dpo": 3, "overdue": 2, "creditor": 2, "on time payment": 2}),
    "procureToPay": ("Purchase to pay", "cart", ("purchase_order", "requisition"), {
        "cycle time": 3, "funnel": 3, "purchase to pay": 3, "purchase-to-pay": 3, "procure to pay": 3, "procure-to-pay": 3,
        "p2p": 3, "bottleneck": 2, "how long": 1}),
    "suppliers": ("Suppliers", "building", ("supplier",), {
        "scorecard": 3, "supplier performance": 3, "concentration": 3, "supplier risk": 3, "otif": 3, "on time in full": 3}),
    "controls": ("Controls", "shield", ("invoice", "purchase_order"), {
        "control": 2, "audit": 2, "compliance": 2, "duplicate": 2, "maverick": 2, "segregation": 2, "split": 1}),
    "savings": ("Savings", "sparkles", ("savings_initiative",), {"saving": 3, "cost avoidance": 3, "baseline": 1}),
}

# What says a screen is read, and what says it is worked on.
READ = {"dashboard": 4, "kpi": 3, "report": 2, "chart": 2, "trend": 2, "analys": 2, "monitor": 2, "overview": 2,
        "summary": 2, "insight": 2, "visib": 1, "track": 1, "figures": 2, "drill": 2}
WORK = {"approve": 3, "reject": 3, "queue": 3, "raise": 2, "create": 2, "submit": 2, "confirm": 2, "receive": 2,
        "match": 2, "send": 2, "propose": 2, "onboard": 2, "record": 1, "process": 1, "enter": 1, "resolve": 2}


def _text(story: dict[str, Any]) -> tuple[str, str]:
    title = str(story.get("title") or "").lower()
    rest = " ".join([str(story.get("narrative") or ""), *[str(c) for c in story.get("acceptance_criteria") or []]]).lower()
    return f" {title} ", f" {rest} "


def _has(word: str, text: str) -> bool:
    """The word, or a word that starts with it ("approv" finds "approved"); never the inside of
    another ("otif" is not in "notification"). A word written with a space after it is whole."""
    end = r"(?![a-z0-9])" if word.endswith(" ") else ""
    return re.search(r"(?<![a-z0-9])" + re.escape(word.strip()) + end, text) is not None


def _score(words: dict[str, int], title: str, rest: str) -> tuple[int, list[str]]:
    total, found = 0, []
    for word, weight in words.items():
        if _has(word, title):
            total += weight * TITLE
            found.append(word.strip())
        elif _has(word, rest):
            total += weight * ELSEWHERE
            found.append(word.strip())
    return total, found


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "screen"


def ranked(story: dict[str, Any], tables: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Every screen of the library the story has a word of, the nearest first."""
    have = {str(t) for t in tables or ()}
    title, rest = _text(story)
    read, _ = _score(READ, title, rest)
    work, _ = _score(WORK, title, rest)
    out = []
    for kind, catalogue, lean in (("worklist", WORKLISTS, work), ("dashboard", DASHBOARDS, read)):
        for name, (label, icon, needs, words) in catalogue.items():
            if have and not any(n in have for n in needs):
                continue
            score, found = _score(words, title, rest)
            if score:
                out.append({"kind": kind, "name": name, "title": label, "icon": icon, "own": score, "score": score + lean,
                            "words": found})
    # A tie goes to the screen people work on: it is the one a model writes worst by hand.
    return sorted(out, key=lambda s: (-s["score"], s["kind"] != "worklist", s["name"]))


def _js(value: Any) -> str:
    """A value as JavaScript writes it: { id: "s9-receiving", mine: true }."""
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', str(k)) else json.dumps(str(k))}: {_js(v)}"
                                for k, v in value.items()) + " }"
    return json.dumps(value)


def content(kind: str, name: str, story: dict[str, Any], *, title: str = "", icon: str = "", options: dict[str, Any] | None = None) -> str:
    """The screen file: an import, a title and one call."""
    sid = str(story.get("id") or "")
    heading = title or str(story.get("title") or name)
    spec = _js({"id": _slug(f"{sid} {name}").replace("_", "-"), **(options or {})})
    call = (f"fin.workbench(root, ctx, fin.worklists.{name}({spec}))" if kind == "worklist"
            else f"fin.dashboard(root, ctx, fin.blueprints.{name}({spec}))")
    what = ("add: [views], remove: [\"key\"], actions, columns, mine" if kind == "worklist"
            else "kpis, targets, filters, fixed, add: [widgets], remove: [\"type\"]")
    return (
        'import fin from "../finance.js";\n\n'
        f"// The finance library's screen for this story. Say what the story needs different\n"
        f"// ({what}); everything else comes with it.\n"
        "export default {\n"
        f"  title: {json.dumps(heading)},\n"
        f"  icon: {json.dumps(icon or 'dollar')},\n"
        f"  story: {json.dumps(sid)},\n"
        "  async render(root, ctx) {\n"
        f"    await {call};\n"
        "  },\n"
        "};\n"
    )


def suggest(story: dict[str, Any], tables: Iterable[str] = ()) -> dict[str, Any] | None:
    """The library's screen nearest the story, or None when the story is not clearly any of them."""
    found = ranked(story, tables)
    if not found or found[0]["own"] < ENOUGH:
        return None
    best = found[0]
    title, rest = _text(story)
    options: dict[str, Any] = {}
    if best["name"] == "approvals":
        # A queue of one kind of record when the story speaks of only one.
        named = [e for e, words in (("requisition", ("requisition", "purchase request")), ("purchase_order", ("purchase order",)),
                                     ("invoice", ("invoice",)), ("payment_run", ("payment run",)))
                 if any(_has(w, title + rest) for w in words)]
        have = {str(t) for t in tables or ()}
        if len(named) == 1 and (not have or named[0] in have):
            options["of"] = named[0]
    if best["name"] == "requisitions" and any(_has(w, title + rest) for w in ("my ", "own ", "requester")):
        options["mine"] = True
    heading = str(story.get("title") or best["title"]).strip()
    heading = best["title"] if len(heading) > 34 else heading
    why = (f"the library has a {'work screen' if best['kind'] == 'worklist' else 'dashboard'} for this, \"{best['title']}\" "
           f"(fin.{'worklists' if best['kind'] == 'worklist' else 'blueprints'}.{best['name']})")
    return {**best, "heading": heading, "file": f"{_slug(heading)}.js", "why": why, "options": options,
            "content": content(best["kind"], best["name"], story, title=heading, icon=best["icon"], options=options)}
