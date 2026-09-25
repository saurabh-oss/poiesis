from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class RunState(TypedDict, total=False):
    run_id: str
    title: str
    brief: str                      # concatenated evidence, cited
    evidence: list[dict[str, Any]]  # {id, source_kind, source_ref, locator, content}

    clarifications: list[dict[str, Any]]
    answers: dict[str, str]

    vision: dict[str, Any]
    backlog: dict[str, Any]
    requirements: list[dict[str, Any]]  # what the brief requires, with ids and numbers (requirements.py)
    portfolio: dict[str, Any]
    architecture: dict[str, Any]
    sprint: dict[str, Any]
    scaffold: dict[str, Any]      # archetype, services, deployable contract
    # Declared, or LangGraph drops them from the state without a word: `foundation` was
    # returned for weeks and never reached the build stage's "the data layer exists" note.
    foundation: dict[str, Any]    # tables, seeded rows
    domain: dict[str, Any]        # roles, rules, workflows, rule test results (enterprise pack)

    build: dict[str, Any]
    test_report: dict[str, Any]
    review: dict[str, Any]
    deployment: dict[str, Any]    # where the increment is running, if it is
    release: dict[str, Any]

    repair_attempts: int
    human_rebuilds: int           # rounds the stakeholder sent back from the release gate
    log: Annotated[list[str], operator.add]
