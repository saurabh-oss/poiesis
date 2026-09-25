"""Business rules. WORKED EXAMPLE over the scaffold's Example model: the domain stage
replaces this file with every rule the brief states.

The shape every rule keeps:
  - one function per rule, decorated with its id, a one-line title, and where the brief
    says it (`source`), so the catalogue can trace code back to the requirement;
  - pure: it takes records or plain values and returns a value, or raises the rule's
    violation with `check(...)`. No database, no HTTP, no clock read inside — pass
    `now` in — so it is testable in isolation and every screen gets the same answer;
  - numbers the brief fixes (thresholds, weights, limits) are named constants here.
"""
from __future__ import annotations

from typing import Any

from ..kernel.rules import check, rule

REVIEW_AMOUNT = 10_000          # EX-01: above this, finishing needs a reviewer's approval
WEIGHTS = {"amount": 0.6, "age": 0.4}


@rule("EX-01", "Items over 10,000 need a reviewer's approval to finish",
      source="Worked example §2", kind="decision")
def needs_approval(item: Any) -> bool:
    return float(getattr(item, "amount", 0) or 0) > REVIEW_AMOUNT


@rule("EX-02", "An item cannot go to review without an owner",
      source="Worked example §3", kind="validation")
def ready_for_review(item: Any, ctx: Any = None) -> None:
    check(bool((getattr(item, "owner", "") or "").strip()), "EX-02", "Assign an owner before sending it to review")


@rule("EX-03", "Priority = 60% amount (capped at 50,000) + 40% age (capped at 30 days)",
      source="Worked example §4", kind="calculation")
def priority(amount: float, age_days: float) -> float:
    a = min(max(amount, 0), 50_000) / 50_000
    b = min(max(age_days, 0), 30) / 30
    return round(100 * (WEIGHTS["amount"] * a + WEIGHTS["age"] * b), 1)
