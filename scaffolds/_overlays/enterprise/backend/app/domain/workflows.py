"""Lifecycles. WORKED EXAMPLE over the scaffold's Example model: the domain stage
replaces this file with the application's own workflows.

A workflow owns one status column: nothing else may write it. States are the values
init.sql's comment names for that column; transitions say who may move a record, from
where to where, under which rule, and whether someone else must approve it first.
"""
from __future__ import annotations

from ..kernel.workflow import Transition, Workflow, register
from ..models import Example
from . import rules


def _finish_guard(item, ctx):
    """EX-01 decides whether finishing goes through a reviewer's approval: the engine
    asks for approval when the transition declares one, so small items take `finish`,
    large ones `finish_large`."""
    if rules.needs_approval(item):
        return "Items over 10,000 need a reviewer's approval: use “Request sign-off”"
    return None


def _large_only(item, ctx):
    if not rules.needs_approval(item):
        return "Only items over 10,000 need sign-off; finish it directly"
    return None


EXAMPLE = register(Workflow(
    "example", Example, field="status", title="Work item",
    states={"open": "Open", "in_progress": "In progress", "review": "In review", "done": "Done"},
    initial="open",
    transitions=[
        Transition("start", "open", "in_progress", label="Start", roles=("member", "reviewer")),
        Transition("submit", "in_progress", "review", label="Send to review", roles=("member",),
                   guard=rules.ready_for_review, rule="EX-02"),
        Transition("finish", "review", "done", label="Finish", roles=("reviewer",), guard=_finish_guard,
                   rule="EX-01", tone="ok"),
        Transition("finish_large", "review", "done", label="Request sign-off", roles=("reviewer",),
                   approval="admin", guard=_large_only, rule="EX-01", tone="ok"),
        Transition("send_back", "review", "in_progress", label="Send back", roles=("reviewer",),
                   requires_reason=True, tone="warn", notify=("member",)),
    ],
    sla={"review": 24},
    escalate={"review": "reviewer"},
))
