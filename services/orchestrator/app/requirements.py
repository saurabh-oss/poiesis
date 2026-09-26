"""What the brief asks for, as a list the platform can check the work against.

The enterprise DupeGuard run built nine screens from a brief that named ten. Its backlog
had an epic called "Audit & Accuracy Monitoring" and no story for the accuracy screen, and
nothing noticed: the stories were checked for testable criteria, never against the brief.
Its domain stage then registered eleven rules, passed thirty tests, and left out the one
the whole product turns on, the confidence score of section 6.2, which had no id in the
brief to be missed by.

So the platform keeps an inventory of the brief's requirements. The ids the brief defines
itself are found deterministically (a line or table row that starts with `M1`, `BR-04`,
`FR-12`, `AC-3`), so none can be dropped; a model pass classifies them and adds what has no
id: a scoring formula, a weight, a default, an approval, an integration. Each item carries
the numbers the brief fixes for it. The backlog must cover every screen, capability,
functional requirement and acceptance criterion with a story; the domain stage must
implement every rule under its id, with tests that pin the brief's numbers.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

# A requirement id: a short capital prefix and a number — M1, BR-04, FR-12, AC-3, COMP-01.
ID = r"[A-Z]{1,5}-?\d{1,3}[a-z]?"
# A definition starts a line or a table cell and is followed by a separator, a bracket or
# a capitalised word: "M1 | Command Center", "BR-01 Auto-close | …", "BR-10: A cluster",
# "AC-1 (M1) Given …". An id mentioned mid-sentence ("apply BR-01 to BR-06") is a reference.
_DEFINITION = re.compile(
    rf"^\s*\|?\s*({ID})\b(?=\s*[|:.)–—(-]|\s+[A-Z'\"(])[\s|:.)–—-]*(.*)$")
_NUMBER = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w.]*\d)")
_SECTION = re.compile(r"(?:§\s*|section\s+|sect\.\s*|see\s+)\d+(?:\.\d+)*", re.IGNORECASE)

KINDS = ["capability", "functional", "acceptance", "rule", "compliance", "role", "workflow",
         "integration", "notification", "nonfunctional", "data", "other"]
# Delivered by a story: something a person sees or does, and how it is judged done.
STORY_KINDS = {"capability", "functional", "acceptance"}
# Decided once, in the domain layer, when the pack has one; by a story otherwise.
RULE_KINDS = {"rule", "compliance"}
# A screen the brief names is never left out quietly, with or without a reason.
NEVER_EXCUSED = {"capability"}


def norm(rid: str) -> str:
    return re.sub(r"\s+", "", str(rid or "")).upper()


def family(rid: str) -> str:
    m = re.match(r"[A-Z]+", norm(rid))
    return m.group(0) if m else ""


def defined_ids(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every id the brief defines, in order, with the text that defines it and its fragment."""
    found: dict[str, dict[str, Any]] = {}
    for e in evidence:
        for line in str(e.get("content") or "").splitlines():
            m = _DEFINITION.match(line)
            if not m:
                continue
            rid, text = norm(m.group(1)), m.group(2).strip(" |")
            if not text or len(text) < 3:
                continue
            prior = found.get(rid)
            if prior is None or len(text) > len(prior["text"]):
                found[rid] = {"id": rid, "text": text[:600], "evidence_id": e.get("id", "")}
    return list(found.values())


def numbers_in(text: str) -> list[str]:
    """The numbers a statement fixes, without section references or the digits of ids."""
    clean = _SECTION.sub(" ", re.sub(rf"\b{ID}\b", " ", str(text or "")))
    out: list[str] = []
    for n in _NUMBER.findall(clean):
        n = n.replace(",", "")
        if n not in out:
            out.append(n)
    return out


def number_forms(n: str) -> list[str]:
    """How a test may write a number the brief states: 55 as 55, 55.0 or 0.55."""
    forms = [n]
    try:
        value = float(n)
    except ValueError:
        return forms
    if value.is_integer():
        forms.append(f"{int(value)}.0")
        if 0 < value <= 100:
            forms.append(f"{value / 100:g}")
    return forms


# How a family of ids is usually meant, when the model's reply is unavailable.
FAMILY_KINDS = {"M": "capability", "SCR": "capability", "UC": "capability", "BR": "rule",
                "FR": "functional", "F": "functional", "AC": "acceptance", "COMP": "compliance",
                "NFR": "nonfunctional"}


def merge(defined: list[dict[str, Any]], modelled: list[dict[str, Any]], brief: str) -> list[dict[str, Any]]:
    """The model's classified list, made to contain every defined id exactly once.

    A defined id the model left out is added back, classified like the rest of its family;
    a number the model reports that the brief never states is dropped."""
    items: dict[str, dict[str, Any]] = {}
    for raw in modelled:
        rid = norm(raw.get("id", ""))
        if not rid or rid in items:
            continue
        kind = raw.get("kind") if raw.get("kind") in KINDS else "other"
        statement = str(raw.get("statement") or "").strip()
        nums = [str(n).strip() for n in raw.get("numbers") or [] if str(n).strip()]
        nums = [n for n in dict.fromkeys(nums) if re.fullmatch(r"\d+(?:\.\d+)?", n)
                and re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", brief)]
        items[rid] = {"id": rid, "kind": kind, "title": str(raw.get("title") or "").strip()[:160],
                      "statement": statement[:600], "numbers": nums,
                      "evidence_id": str(raw.get("evidence_id") or ""), "source": "brief" if rid else "",
                      "superseded_by": str(raw.get("superseded_by") or "").strip()[:300]}
    by_family: dict[str, Counter] = {}
    for it in items.values():
        by_family.setdefault(family(it["id"]), Counter())[it["kind"]] += 1
    for d in defined:
        it = items.get(d["id"])
        if it is None:
            kinds = by_family.get(family(d["id"]))
            guess = kinds.most_common(1)[0][0] if kinds else FAMILY_KINDS.get(family(d["id"]), "other")
            items[d["id"]] = {"id": d["id"], "kind": guess,
                              "title": d["text"].split("|")[0].strip()[:160], "statement": d["text"],
                              "numbers": numbers_in(d["text"]), "evidence_id": d["evidence_id"], "source": "brief"}
        else:
            it["defined"] = True
            if not it["statement"]:
                it["statement"] = d["text"]
            it["evidence_id"] = it["evidence_id"] or d["evidence_id"]
    defined_set = {d["id"] for d in defined}
    for it in items.values():
        it["defined"] = it["id"] in defined_set
    order = {d["id"]: i for i, d in enumerate(defined)}
    return sorted(items.values(), key=lambda it: (0 if it["id"] in order else 1, order.get(it["id"], 0)))


def needs_story(item: dict[str, Any], domain_layer: bool) -> bool:
    if item.get("superseded_by"):
        return False  # a later instruction replaced it: building it would contradict the brief
    return item["kind"] in STORY_KINDS or (item["kind"] in RULE_KINDS and not domain_layer)


def story_mentions(story: dict[str, Any]) -> set[str]:
    """The requirement ids a story says it delivers: its `covers` list, and any id it names."""
    ids = {norm(x) for x in story.get("covers") or [] if str(x).strip()}
    text = " ".join([str(story.get("title") or ""), str(story.get("narrative") or ""),
                     *[str(c) for c in story.get("acceptance_criteria") or []]])
    ids |= {norm(x) for x in re.findall(rf"\b{ID}\b", text)}
    return ids


def backlog_coverage(inventory: list[dict[str, Any]], backlog: dict[str, Any],
                     domain_layer: bool) -> dict[str, Any]:
    """Which requirements a story delivers, which are excused with a reason, which are missing."""
    stories = backlog.get("stories") or []
    by_req: dict[str, list[str]] = {}
    for s in stories:
        for rid in story_mentions(s):
            by_req.setdefault(rid, []).append(str(s.get("id")))
    excused = {norm(x.get("id")): str(x.get("reason") or "").strip()
               for x in backlog.get("not_covered") or [] if str(x.get("reason") or "").strip()}
    rows, missing = [], []
    for it in inventory:
        if not needs_story(it, domain_layer):
            continue
        covered = by_req.get(it["id"], [])
        if covered:
            status = "covered"
        elif it["id"] in excused and it["kind"] not in NEVER_EXCUSED:
            status = "excused"
        else:
            status = "missing"
            missing.append(it)
        rows.append({"id": it["id"], "kind": it["kind"], "title": it["title"], "stories": covered,
                     "status": status, "reason": excused.get(it["id"], "")})
    return {"rows": rows, "missing": [m["id"] for m in missing], "missing_items": missing,
            "covered": sum(1 for r in rows if r["status"] == "covered"),
            "excused": sum(1 for r in rows if r["status"] == "excused"), "total": len(rows)}


def describe(items: list[dict[str, Any]], limit: int = 60) -> str:
    """Requirements as lines a prompt can carry."""
    lines = []
    for it in items[:limit]:
        nums = f" [numbers: {', '.join(it['numbers'])}]" if it.get("numbers") else ""
        lines.append(f"- {it['id']} ({it['kind']}): {it['title']} — {it['statement'][:300]}{nums}")
    return "\n".join(lines)


# ---- the domain layer against the brief ------------------------------------------------

_PLACEHOLDER = re.compile(
    r"(?i)\b(simplified|placeholder|for (?:the )?mvp|todo|fixme|hard-?coded|dummy|not implemented|"
    r"stub(?:bed)?|to be implemented|in a real (?:system|app))\b")


def placeholders(files: dict[str, str]) -> list[str]:
    """Lines where the model says it cut a corner, in the files that hold the rules."""
    out = []
    for rel, body in files.items():
        for i, line in enumerate(str(body or "").splitlines(), 1):
            if _PLACEHOLDER.search(line):
                out.append(f"{rel}:{i}: {line.strip()[:140]}")
    return out


def tests_by_rule(test_source: str, rule_ids: list[str]) -> dict[str, str]:
    """The source of every test named after each rule (test_br_04_…), joined per rule."""
    slug = lambda i: re.sub(r"[^a-z0-9]+", "_", i.lower()).strip("_")  # noqa: E731
    chunks = re.split(r"(?m)^(?=\s*def test_)", test_source or "")
    out: dict[str, str] = {}
    ids = sorted(rule_ids, key=lambda i: -len(slug(i)))
    for chunk in chunks:
        m = re.match(r"\s*def (test_\w+)", chunk)
        if not m:
            continue
        name = m.group(1).lower()
        rid = next((i for i in ids if name.startswith(f"test_{slug(i)}_") or name == f"test_{slug(i)}"), None)
        if rid:
            out[rid] = out.get(rid, "") + "\n" + chunk
    return out


def domain_gaps(inventory: list[dict[str, Any]], registered: list[str], test_source: str,
                files: dict[str, str]) -> list[str]:
    """What the domain layer leaves out of the brief's rules. Each line is a repair instruction."""
    rules = [it for it in inventory if it["kind"] in RULE_KINDS and not it.get("superseded_by")]
    have = {norm(r) for r in registered}
    problems: list[str] = []
    missing = [it for it in rules if it["id"] not in have]
    if missing:
        problems.append(
            "rules the brief states that rules.py does not register under their id (add a @rule with exactly "
            "this id, or declare() it where a workflow or service implements it): "
            + "; ".join(f"{it['id']} {it['title']}" for it in missing[:12]))
    tests = tests_by_rule(test_source, [it["id"] for it in rules])
    for it in rules:
        if it["id"] in have and it.get("numbers"):
            body = tests.get(it["id"], "")
            absent = [n for n in it["numbers"]
                      if not any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", body) for f in number_forms(n))]
            if absent:
                problems.append(
                    f"{it['id']}'s tests never state the brief's number(s) {', '.join(absent)}: write them as "
                    f"literals in test_{re.sub(r'[^a-z0-9]+', '_', it['id'].lower()).strip('_')}_… (both sides of "
                    "each threshold), so a wrong constant fails a test")
    cut = placeholders(files)
    if cut:
        problems.append("the rules must do what the brief says, not a simplified stand-in; these lines admit a "
                        "shortcut: " + " | ".join(cut[:6]))
    return problems


def delivery(inventory: list[dict[str, Any]], backlog: dict[str, Any], built: dict[str, str],
             domain_layer: bool) -> dict[str, Any]:
    """Which requirements the increment delivers: covered by a story that ended green.

    `built` maps story id to its build status (green, red, dropped); a story missing from
    it was never built this round."""
    by_req: dict[str, list[str]] = {}
    for s in backlog.get("stories") or []:
        for rid in story_mentions(s):
            by_req.setdefault(rid, []).append(str(s.get("id")))
    delivered, not_delivered = [], []
    for it in inventory:
        if not needs_story(it, domain_layer):
            continue
        stories = by_req.get(it["id"], [])
        if any(built.get(sid) == "green" for sid in stories):
            delivered.append(it["id"])
        else:
            why = ("no story" if not stories else
                   ", ".join(f"{sid} {built.get(sid) or 'not built'}" for sid in stories))
            not_delivered.append({"id": it["id"], "kind": it["kind"], "title": it["title"], "why": why})
    return {"delivered": delivered, "not_delivered": not_delivered,
            "total": len(delivered) + len(not_delivered)}
