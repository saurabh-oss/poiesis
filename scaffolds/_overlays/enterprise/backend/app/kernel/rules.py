"""The business rule registry. Written by Poiesis, and read-only.

Every rule the brief states has one id, one statement and one implementation, in
`domain/rules.py`:

    @rule("BR-04", "A P1 ticket is never closed automatically",
          source="BRD §6.2", kind="decision")
    def may_auto_close(ticket) -> bool:
        return ticket.priority != "P1"

and a rule that forbids something says so with its id:

    check(amount <= limit, "BR-07", f"£{amount:,.0f} is above your approval limit of £{limit:,.0f}")

A violation becomes HTTP 409 with the rule's id and message, so a screen can show the
person exactly which rule stopped them. The catalogue at /api/platform/rules lists every
rule with where it is implemented, how often it fired and what its tests proved.
"""
from __future__ import annotations

import functools
import inspect
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

KINDS = ("validation", "decision", "calculation", "authorisation", "workflow", "notification", "integration")


@dataclass
class Rule:
    id: str
    title: str
    statement: str = ""
    source: str = ""
    kind: str = "decision"
    module: str = ""
    function: str = ""
    line: int = 0
    calls: int = 0
    violations: int = 0
    last_message: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "statement": self.statement or self.title, "source": self.source,
                "kind": self.kind, "where": f"{self.module}.{self.function}" if self.function else self.module,
                "line": self.line, "calls": self.calls, "violations": self.violations, "last_message": self.last_message}


RULES: dict[str, Rule] = {}
_lock = threading.Lock()


class RuleViolation(Exception):
    """Something a business rule forbids. Answered as 409 with the rule's id."""

    def __init__(self, rule_id: str, message: str, *, status: int = 409, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.rule_id = rule_id
        self.message = message
        self.status = status
        self.details = details or {}
        self.counted = False

    def __str__(self) -> str:
        # The id travels with the text, so a log line or a test reading str(err) sees
        # which rule refused ("BR-04: P1 tickets are closed by a person").
        return f"{self.rule_id}: {self.message}"

    def as_dict(self) -> dict[str, Any]:
        r = RULES.get(self.rule_id)
        return {"detail": self.message, "rule": self.rule_id, "rule_title": r.title if r else "", **self.details}


def rule(rule_id: str, title: str, *, statement: str = "", source: str = "", kind: str = "decision"):
    """Register the decorated function as the one implementation of a rule."""
    def decorate(fn: Callable) -> Callable:
        try:
            line = inspect.getsourcelines(fn)[1]
        except (OSError, TypeError):
            line = 0
        entry = RULES.get(rule_id) or Rule(rule_id, title)
        entry.title, entry.statement, entry.source = title, statement or entry.statement, source or entry.source
        entry.kind = kind if kind in KINDS else "decision"
        entry.module, entry.function, entry.line = fn.__module__, fn.__qualname__, line
        RULES[rule_id] = entry

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _lock:
                entry.calls += 1
            try:
                return fn(*args, **kwargs)
            except RuleViolation as exc:
                if not exc.counted:
                    _count(RULES.get(exc.rule_id) or entry, exc)
                raise

        wrapper.rule_id = rule_id  # type: ignore[attr-defined]
        return wrapper
    return decorate


def declare(rule_id: str, title: str, *, statement: str = "", source: str = "", kind: str = "decision") -> Rule:
    """A rule enforced somewhere other than a decorated function (a workflow guard, the
    policy, a database constraint): catalogued all the same.

    It only fills in what is missing: a rule the domain already defined with @rule keeps
    its own title, kind and source when a workflow transition names it."""
    if rule_id in RULES:
        entry = RULES[rule_id]
        entry.statement = entry.statement or statement
        entry.source = entry.source or source
        return entry
    entry = Rule(rule_id, title)
    entry.statement, entry.source, entry.kind = statement or title, source, kind
    caller = inspect.stack()[1]
    module = inspect.getmodule(caller.frame)
    if not entry.module and module is not None:
        entry.module = module.__name__
    entry.line = entry.line or caller.lineno
    RULES[rule_id] = entry
    return entry


def _count(entry: Rule | None, exc: RuleViolation) -> None:
    exc.counted = True
    if entry is not None:
        with _lock:
            entry.violations += 1
            entry.last_message = exc.message


def violation(rule_id: str, message: str, **details: Any) -> RuleViolation:
    exc = RuleViolation(rule_id, message, details=details)
    _count(RULES.get(rule_id), exc)
    return exc


def check(condition: Any, rule_id: str, message: str, **details: Any) -> None:
    """Raise the rule's violation unless `condition` holds."""
    if not condition:
        raise violation(rule_id, message, **details)


def results() -> dict[str, Any]:
    """What the rule tests proved at build time (written by the platform, baked into the image)."""
    path = Path(__file__).resolve().parent.parent / "domain" / "rule_results.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def catalogue() -> list[dict[str, Any]]:
    proven = results().get("rules", {})
    out = []
    for r in sorted(RULES.values(), key=lambda x: _order(x.id)):
        row = r.as_dict()
        t = proven.get(r.id) or {}
        row["tests"] = {"total": t.get("total", 0), "passed": t.get("passed", 0), "names": t.get("names", [])[:12]}
        out.append(row)
    return out


def _order(rule_id: str) -> tuple:
    import re
    parts = re.split(r"(\d+)", rule_id)
    return tuple(int(p) if p.isdigit() else p for p in parts)
