"""Reuse gate.

Every design step calls this before proposing anything new. The output is fed
to the architect as a constraint, not a suggestion: if a portfolio component
covers the need, the architect must either use it or record why it did not.
"""
from __future__ import annotations

import re
from typing import Any

from ..kg.client import kg
from ..llm import complete_json

_TERMS_SYSTEM = """You extract technical search terms from a product brief.
Return a JSON array of 4-10 short lowercase terms describing the *capabilities*
needed (e.g. "pdf parsing", "sprint planning", "anomaly detection", "sso"),
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
    """Split model-invented compounds back into searchable words.

    The graph is searched with a Lucene full-text index over identifiers and
    docstrings. A phrase like "resume_resumption" is a token that appears in no
    real codebase, so an un-normalised term list silently returns nothing and the
    Architect concludes, wrongly, that the portfolio has nothing to reuse.
    """
    out: list[str] = []
    for raw in terms:
        # Split camelCase before lowering, or the word boundary is already gone.
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


async def portfolio_context(brief: str) -> dict[str, Any]:
    terms = await complete_json(role="fast", system=_TERMS_SYSTEM, user=brief[:6000])
    if not isinstance(terms, list):
        terms = []
    terms = normalise_terms(terms)[:10]

    graph = kg()
    components = await graph.find_reusable(_lucene_query(terms))
    decisions = await graph.prior_decisions(terms)
    stack = await graph.house_stack()
    capabilities = await graph.capability_map()

    return {
        "search_terms": terms,
        "reuse_candidates": components,
        "prior_decisions": decisions,
        "house_stack": stack,
        "capability_map": capabilities,
    }


def render_for_prompt(ctx: dict[str, Any], limit: int = 8) -> str:
    """`limit` keeps this inside a small local context window; raise it on hosted models."""
    lines: list[str] = []
    if ctx["reuse_candidates"]:
        lines.append("EXISTING PORTFOLIO COMPONENTS (prefer these over new code):")
        for c in ctx["reuse_candidates"][:limit]:
            caps = ", ".join(c.get("capabilities") or []) or "unclassified"
            lines.append(
                f"- [{c['component_id']}] {c['project']} :: {c['component']} ({c['kind']}) "
                f"at {c['path']} — {c.get('purpose') or 'no docstring'} [{caps}]"
            )
    else:
        lines.append("EXISTING PORTFOLIO COMPONENTS: none matched. Greenfield is justified.")

    if ctx["house_stack"]:
        top = ", ".join(f"{t['technology']}({t['projects']})" for t in ctx["house_stack"][:15])
        lines.append(f"\nHOUSE STACK (adopt unless you justify otherwise): {top}")

    if ctx["prior_decisions"]:
        lines.append("\nPRIOR ARCHITECTURE DECISIONS:")
        for d in ctx["prior_decisions"][:4]:
            lines.append(f"- {d['title']} → {d['decision']} ({d.get('project') or 'portfolio'})")

    return "\n".join(lines)
