"""Rule tests. WORKED EXAMPLE: the domain stage replaces this file.

One or more tests per rule, each named after the rule it proves — `test_ex_01_…` proves
EX-01 — so the catalogue can show which rules are tested and whether they passed. The
rules are pure, so a test builds plain objects: no database, no client, no network.
"""
from types import SimpleNamespace as Item

import pytest

from app.domain import rules
from app.kernel.rules import RuleViolation


def test_ex_01_over_threshold_needs_approval():
    assert rules.needs_approval(Item(amount=10_001)) is True


def test_ex_01_at_threshold_does_not():
    assert rules.needs_approval(Item(amount=10_000)) is False


def test_ex_02_owner_required():
    with pytest.raises(RuleViolation) as err:
        rules.ready_for_review(Item(owner="  "))
    assert err.value.rule_id == "EX-02"


def test_ex_02_with_owner_passes():
    assert rules.ready_for_review(Item(owner="Sam")) is None


def test_ex_03_weights_and_caps():
    assert rules.priority(50_000, 30) == 100.0
    assert rules.priority(100_000, 90) == 100.0
    assert rules.priority(25_000, 0) == 30.0
    assert rules.priority(0, 15) == 20.0
