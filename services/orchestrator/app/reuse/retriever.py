"""Reuse gate.

Every design step calls this before proposing anything new. The output is fed
to the architect as a constraint, not a suggestion: if a portfolio component
covers the need, the architect must either use it or record why it did not.

Retrieval is hybrid. The graph's full-text index matches identifiers and
docstrings by word; the vector index (kg/vectors.py) matches by meaning, and
also recalls what past runs built, decided, and learned the hard way. Both
degrade independently: an empty vector store leaves the graph's own search.
"""
from __future__ import annotations

import re
from typing import Any

from ..agents import schemas
from ..kg import vectors
from ..kg.client import kg
from ..llm import complete_json

_TERMS_SYSTEM = """You extract technical search terms from a product brief.
Return a JSON object {"terms": [...]} holding 4-10 short lowercase terms describing the
*capabilities* needed (e.g. "pdf parsing", "sprint planning", "anomaly detection", "sso"),
not the business domain and not generic words like "system" or "platform".

Use plain words separated by spaces. Never use snake_case, camelCase, hyphens or
underscores: write "session storage", not "session_storage". These are searched
against source code identifiers and docstrings, so an invented compound matches
nothing."""


_STOPWORDS = {
    "the", "and", "for", "with", "system", "platform", "service", "application",
    "app", "data", "management", "support", "user", "users", "new", "based",
}


def normalise_terms(terms: list[str]) -> list[str]:
    """Split model-invented compounds back into searchable words."""
    out: list[str] = []
    for raw in terms:
        cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(raw))
        cleaned = re.sub(r"[_\-/.]+", " ", cleaned).lower()
        cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def _lucene_query(terms: list[str]) -> str:
    """Match the whole phrase or any meaningful word within it."""
    clauses: list[str] = []
    words: set[str] = set()
    for term in terms:
        if " " in term:
            clauses.append(f'"{term}"')
        for word in term.split():
            if len(word) > 3 and word not in _STOPWORDS:
                words.add(word)
    clauses.extend(sorted(words))
    return " OR ".join(clauses)


def _merge(graph_hits: list[dict[str, Any]], vector_hits: list[dict[str, Any]],
           limit: int = 12) -> list[dict[str, Any]]:
    """Graph hits first (they are exact), then semantic ones the graph missed."""
    seen = {c.get("component_id") for c in graph_hits}
    out = list(graph_hits)
    for v in vector_hits:
        cid = v.get("component_id")
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append({
            "project": v.get("project"), "repo": "", "component_id": cid,
            "component": v.get("component"), "kind": v.get("kind"), "path": v.get("path"),
            "purpose": v.get("purpose"), "signature": v.get("signature"),
            "capabilities": [], "score": v.get("score"), "via": "semantic",
        })
    return out[:limit]


async def portfolio_context(brief: str) -> dict[str, Any]:
    terms = await complete_json(role="fast", system=_TERMS_SYSTEM, user=brief[:12000],
                                schema=schemas.TERMS)
    if isinstance(terms, dict):
        terms = terms.get("terms") or []
    if not isinstance(terms, list):
        terms = []
    terms = normalise_terms(terms)[:10]

    graph = kg()
    query = " ".join(terms) or brief[:1000]
    components = _merge(await graph.find_reusable(_lucene_query(terms)),
                        await vectors.search("components", query, limit=8))
    decisions = await graph.prior_decisions(terms)
    for d in await vectors.search("decisions", query, limit=4):
        if not any(x.get("title") == d.get("title") for x in decisions):
            decisions.append({"id": "", "title": d.get("title"), "decision": d.get("decision"),
                              "rationale": d.get("rationale"), "status": "accepted",
                              "project": d.get("project"), "via": "semantic"})
    stack = await graph.house_stack()
    capabilities = await graph.capability_map()
    past = await vectors.search("stories", query, limit=6)
    lessons = await vectors.search("lessons", query, limit=6)

    return {
        "search_terms": terms,
        "reuse_candidates": components,
        "prior_decisions": decisions,
        "house_stack": stack,
        "capability_map": capabilities,
        "past_stories": past,
        "lessons": lessons,
    }


async def lessons_for(text: str, limit: int = 5) -> list[dict[str, Any]]:
    """Lessons from past runs that apply to this story, by meaning."""
    return await vectors.search("lessons", text, limit=limit)


def render_for_prompt(ctx: dict[str, Any], limit: int = 8) -> str:
    """`limit` keeps this inside a small local context window; raise it on hosted models."""
    lines: list[str] = []
    if ctx.get("reuse_candidates"):
        lines.append("EXISTING PORTFOLIO COMPONENTS (prefer these over new code):")
        for c in ctx["reuse_candidates"][:limit]:
            caps = ", ".join(c.get("capabilities") or []) or "unclassified"
            lines.append(
                f"- [{c['component_id']}] {c['project']} :: {c['component']} ({c['kind']}) "
                f"at {c['path']} — {c.get('purpose') or 'no docstring'} [{caps}]"
            )
    else:
        lines.append("EXISTING PORTFOLIO COMPONENTS: none matched. Greenfield is justified.")

    if ctx.get("house_stack"):
        top = ", ".join(f"{t['technology']}({t['projects']})" for t in ctx["house_stack"][:15])
        lines.append(f"\nHOUSE STACK (adopt unless you justify otherwise): {top}")

    if ctx.get("prior_decisions"):
        lines.append("\nPRIOR ARCHITECTURE DECISIONS:")
        for d in ctx["prior_decisions"][:4]:
            lines.append(f"- {d['title']} → {d['decision']} ({d.get('project') or 'portfolio'})")

    if ctx.get("past_stories"):
        lines.append("\nWHAT PAST RUNS BUILT THAT RESEMBLES THIS:")
        for s in ctx["past_stories"][:min(limit, 5)]:
            lines.append(f"- {s.get('project')}: {s.get('title')} — {s.get('outcome')}")

    if ctx.get("lessons"):
        lines.append("\nLESSONS FROM PAST RUNS (each cost a failed story; do not repeat them):")
        for l in ctx["lessons"][:min(limit, 6)]:
            lines.append(f"- {l.get('lesson')}")

    return "\n".join(lines)


def render_lessons(lessons: list[dict[str, Any]]) -> str:
    if not lessons:
        return ""
    return ("\n\nLESSONS FROM PAST RUNS that apply to this story (each one cost a failed story "
            "before; do not repeat them):\n" + "\n".join(f"- {l.get('lesson')}" for l in lessons) + "\n")
