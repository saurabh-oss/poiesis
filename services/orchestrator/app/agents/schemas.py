"""The shape of every agent's reply, as JSON Schema.

On the local profile these are handed to Ollama as the `format`, which
constrains decoding to the schema: a reply cannot be malformed, cannot omit a
required key, and cannot invent a status the graph does not understand. That
retires the most expensive failure mode of a local model — a ten-minute reply
that was one unescaped quote away from parsing.

The prompts still describe the shape in prose, because the hosted profiles do
not take a schema and because the description carries meaning ("2-4 sentences")
that a schema cannot. The two are kept in step by hand; the self-test checks
that every schema is valid and that the sample replies in it validate.

Keep the schemas permissive about *content* and strict about *structure*: a
required key with an empty string is recoverable, a missing key is not.
"""
from __future__ import annotations

from typing import Any


def _str(desc: str = "") -> dict[str, Any]:
    return {"type": "string", "description": desc} if desc else {"type": "string"}


def _strs(desc: str = "") -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, **({"description": desc} if desc else {})}


def _obj(props: dict[str, Any], required: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or list(props), **extra}


def _arr(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


_INT = {"type": "integer"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}


# ---- discovery -------------------------------------------------------------------

ANALYSIS = _obj({
    "understanding": _str(),
    "signals": _arr(_obj({"statement": _str(), "evidence_ids": _strs()})),
    "contradictions": _arr(_obj({"description": _str(), "evidence_ids": _strs()})),
    "questions": _arr(_obj({
        "id": _str(), "question": _str(), "why_it_matters": _str(),
        "cost_of_being_wrong": {"type": "string", "enum": ["high", "medium", "low"]},
        "proposed_default": _str(),
    })),
})

# ---- product ---------------------------------------------------------------------

VISION = _obj({
    "product_name": _str(),
    "problem_statement": _str(),
    "target_users": _arr(_obj({"persona": _str(), "current_pain": _str(), "evidence_ids": _strs()})),
    "value_proposition": _str(),
    "success_metrics": _arr(_obj({
        "metric": _str(), "baseline": _str(), "target": _str(), "how_measured": _str(),
        "assumed": _BOOL,
    }, ["metric", "target"])),
    "in_scope": _strs(),
    "explicitly_out_of_scope": _strs(),
    "key_risks": _arr(_obj({"risk": _str(), "mitigation": _str()})),
    "assumptions": _arr(_obj({"assumption": _str(), "if_wrong": _str()})),
}, ["product_name", "problem_statement", "target_users", "value_proposition",
    "success_metrics", "in_scope", "explicitly_out_of_scope"])

_STORY = _obj({
    "id": _str(), "epic_id": _str(), "title": _str(), "narrative": _str(),
    "acceptance_criteria": _strs(), "evidence_ids": _strs(),
    "covers": _strs("the ids of the brief's requirements this story delivers"),
    "value": _INT, "estimate": _INT,
    "risk": {"type": "string", "enum": ["high", "medium", "low"]},
    "depends_on": _strs(),
}, ["id", "epic_id", "title", "narrative", "acceptance_criteria", "covers", "value", "estimate", "risk"])
_NOT_COVERED = _arr(_obj({"id": _str(), "reason": _str()}))

BACKLOG = _obj({
    "epics": _arr(_obj({"id": _str(), "title": _str(), "outcome": _str(), "evidence_ids": _strs()},
                       ["id", "title", "outcome"])),
    "stories": _arr(_STORY),
    "not_covered": _NOT_COVERED,
}, ["epics", "stories", "not_covered"])

# Stories for requirements the backlog left without one; merged into it by the platform.
BACKLOG_ADDITIONS = _obj({"stories": _arr(_STORY), "not_covered": _NOT_COVERED})

# ---- requirements ----------------------------------------------------------------

REQUIREMENTS = _obj({"items": _arr(_obj({
    "id": _str("the brief's own id, or REQ-n for one it did not number"),
    "kind": {"type": "string", "enum": ["capability", "functional", "acceptance", "rule", "compliance", "role",
                                        "workflow", "integration", "notification", "nonfunctional", "data", "other"]},
    "title": _str(), "statement": _str(),
    "numbers": _strs("each number the brief fixes for it: thresholds, weights, limits, durations, counts"),
    "evidence_id": _str(),
}))})

# ---- design ----------------------------------------------------------------------

ARCHITECTURE = _obj({
    "context": _str(),
    "archetype": {"type": "string", "enum": ["web-app", "api-service", "cli-tool"]},
    "deployment": _obj({
        "entrypoint": _str(), "datastore": _str(), "env_vars": _strs(),
        "external_dependencies": _strs(),
    }, ["entrypoint", "datastore"]),
    "reuse_plan": _arr(_obj({
        "need": _str(),
        "verdict": {"type": "string", "enum": ["reuse", "extend", "build_new"]},
        "component_id": {"type": ["string", "null"]},
        "project": {"type": ["string", "null"]},
        "how": _str(), "rationale": _str(),
    }, ["need", "verdict", "how", "rationale"])),
    "components": _arr(_obj({
        "name": _str(), "responsibility": _str(), "technology": _str(),
        "interfaces": _strs(),
        "new_or_existing": {"type": "string", "enum": ["new", "existing"]},
    }, ["name", "responsibility", "technology"])),
    "data_model": _arr(_obj({"entity": _str(), "fields": _strs(), "owner_component": _str()},
                            ["entity", "fields"])),
    "decisions": _arr(_obj({
        "title": _str(), "context": _str(), "decision": _str(), "rationale": _str(),
        "consequences": _str(), "alternatives_rejected": _strs(),
    }, ["title", "decision", "rationale"])),
    "diagram_mermaid": _str(),
    "risks": _arr(_obj({"risk": _str(), "mitigation": _str()})),
}, ["context", "archetype", "deployment", "reuse_plan", "components", "data_model",
    "decisions", "diagram_mermaid"])

SPRINT = _obj({
    "sprint_goal": _str(),
    "capacity_used": _INT,
    "stories": _arr(_obj({"id": _str(), "rank": _INT, "why_now": _str()}, ["id", "rank"])),
    "deferred": _arr(_obj({"id": _str(), "why_not_now": _str()}, ["id"])),
    "definition_of_done": _strs(),
}, ["sprint_goal", "stories", "deferred"])

# ---- build -----------------------------------------------------------------------

_FILES = {"type": "object", "additionalProperties": {"type": "string"},
          "description": "relative path -> complete file content"}

IMPLEMENTATION = _obj({
    "files": _FILES,
    "commit_message": _str(),
    "manual_steps": _strs(),
    "blocked_reason": {"type": ["string", "null"]},
    "reasoning": _str(),
}, ["files", "commit_message"])

TESTS = _obj({
    "files": _FILES,
    "criteria_covered": _arr(_obj({"criterion": _str(), "test": _str()})),
    "criteria_not_covered": _arr(_obj({"criterion": _str(), "why": _str()})),
    "extra_dependencies": _strs(),
}, ["files", "criteria_covered", "criteria_not_covered"])

# The Acceptance Tester's verdict on checks that failed against the running app.
ACCEPTANCE_TRIAGE = _obj({
    "files": _FILES,
    "verdicts": _arr(_obj({
        "test": _str(),
        "verdict": {"type": "string", "enum": ["check_wrong", "app_wrong"]},
        "finding": _str("for app_wrong: what the app does and what the criterion requires"),
    }, ["test", "verdict", "finding"])),
}, ["files", "verdicts"])

# ---- ship ------------------------------------------------------------------------

_DIM = _obj({"score": _INT, "notes": _str()}, ["score"])

REVIEW = _obj({
    "dimensions": _obj({
        "acceptance_criteria_met": _DIM, "reuse_compliance": _DIM, "test_adequacy": _DIM,
        "maintainability": _DIM, "operational_safety": _DIM,
    }),
    "blocking_findings": _arr(_obj({
        "severity": {"type": "string", "enum": ["blocker", "major"]},
        "story_id": _str(), "file": _str(), "finding": _str(), "required_fix": _str(),
    }, ["severity", "finding", "required_fix"])),
    "advisory_findings": _arr(_obj({"story_id": _str(), "file": _str(), "finding": _str()},
                                   ["finding"])),
    "verdict": {"type": "string", "enum": ["ship", "ship_with_followups", "rework"]},
    "verdict_rationale": _str(),
})

RELEASE_NOTES = _obj({
    "version": _str(),
    "run_command": _str(),
    "release_notes_markdown": _str(),
    "smoke_checks": _arr(_obj({"description": _str(), "command": _str()}, ["description"])),
    "known_limitations": _strs(),
    "next_sprint_candidates": _strs(),
}, ["version", "release_notes_markdown", "known_limitations"])

# ---- helpers used outside the agents ------------------------------------------------

TERMS = _obj({"terms": _strs("4-10 short lowercase capability terms")})

LESSON = _obj({
    "lesson": _str("one sentence a developer can act on next time"),
    "applies_to": _str("the kind of story or file it applies to"),
}, ["lesson"])

ALL: dict[str, dict[str, Any]] = {
    "analysis": ANALYSIS, "vision": VISION, "backlog": BACKLOG, "backlog_additions": BACKLOG_ADDITIONS,
    "requirements": REQUIREMENTS, "architecture": ARCHITECTURE,
    "sprint": SPRINT, "implementation": IMPLEMENTATION, "tests": TESTS,
    "acceptance_triage": ACCEPTANCE_TRIAGE, "review": REVIEW,
    "release_notes": RELEASE_NOTES, "terms": TERMS, "lesson": LESSON,
}
