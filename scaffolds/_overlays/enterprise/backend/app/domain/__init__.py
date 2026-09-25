"""The application's business logic: who may do what, the rules, and the lifecycles.

    policy.py     roles, demonstration personas, permissions, who sees which screen
    rules.py      every business rule from the brief, once, with its id — pure functions
    workflows.py  each record's lifecycle: states, transitions, approvals, SLAs
    services.py   operations that combine rules, workflows and connectors over the database

Every screen and router uses these instead of re-implementing a rule: a number shown
on one screen is the number every other screen and job computes. The kernel imports
this package at start-up; importing it registers the rules and the workflows.
"""
from . import policy, rules, workflows  # noqa: F401 — importing registers them
