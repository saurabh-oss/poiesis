"""The people of a finance and procurement function. Written by Poiesis, and read-only.

Roles, one demonstration persona for each, and what each may do, following the usual
segregation of duties: requesting, approving, ordering, receiving, matching, and paying
are different people. `domain/policy.py` starts from these and changes what its brief says:

    from ..finance import personas

    ROLES = personas.roles("requester", "budget_holder", "buyer", "ap_clerk", "finance_controller", "cfo")
    PERSONAS = personas.people(ROLES)
    PERMISSIONS = personas.permissions(ROLES)
    SCREENS = {"budget_control": ["budget_holder", "finance_controller", "cfo"]}
    CHANNELS = personas.CHANNELS
"""
from __future__ import annotations

from typing import Iterable

ROLES: dict[str, str] = {
    "requester": "Requester",
    "budget_holder": "Budget holder",
    "head_of_department": "Head of department",
    "buyer": "Buyer",
    "procurement_manager": "Procurement manager",
    "ap_clerk": "Accounts payable",
    "treasury": "Treasury",
    "finance_controller": "Financial controller",
    "finance_director": "Finance director",
    "cfo": "Chief financial officer",
    "auditor": "Internal audit",
    "admin": "Administrator",
}

PEOPLE: dict[str, dict[str, str]] = {
    "requester": {"username": "nadia", "full_name": "Nadia Rahman", "title": "Operations analyst", "team": "Operations"},
    "budget_holder": {"username": "tom", "full_name": "Tom Ashworth", "title": "Operations manager", "team": "Operations"},
    "head_of_department": {"username": "helen", "full_name": "Helen Okoro", "title": "Head of Operations", "team": "Operations"},
    "buyer": {"username": "daniel", "full_name": "Daniel Moreau", "title": "Senior buyer", "team": "Procurement"},
    "procurement_manager": {"username": "ingrid", "full_name": "Ingrid Solberg", "title": "Head of Procurement", "team": "Procurement"},
    "ap_clerk": {"username": "kofi", "full_name": "Kofi Mensah", "title": "Accounts payable specialist", "team": "Finance"},
    "treasury": {"username": "mei", "full_name": "Mei Tanaka", "title": "Treasury analyst", "team": "Finance"},
    "finance_controller": {"username": "rachel", "full_name": "Rachel Whitmore", "title": "Financial controller", "team": "Finance"},
    "finance_director": {"username": "arjun", "full_name": "Arjun Mehta", "title": "Finance director", "team": "Finance"},
    "cfo": {"username": "sofia", "full_name": "Sofia Lindgren", "title": "Chief financial officer", "team": "Executive"},
    "auditor": {"username": "peter", "full_name": "Peter Novak", "title": "Internal auditor", "team": "Internal audit"},
    "admin": {"username": "alex", "full_name": "Alex Moreau", "title": "Platform owner", "team": "IT"},
}

_OVERSIGHT = ["audit:read", "rules:read", "integrations:read", "users:read"]

GRANTS: dict[str, list[str]] = {
    "requester": ["*:read", "requisition:create", "requisition:update", "requisition:submit", "requisition:revise",
                  "requisition:cancel", "goods_receipt:create", "purchase_order:receive", "purchase_order:receive_part"],
    "budget_holder": ["*:read", "requisition:create", "requisition:update", "requisition:submit", "requisition:revise",
                      "requisition:cancel", "requisition:approve", "budget_change:create", "budget_change:approve",
                      "goods_receipt:create", "purchase_order:receive", "purchase_order:receive_part"],
    "head_of_department": ["*:read", "budget_change:create", "budget_change:approve", "audit:read", "rules:read"],
    "buyer": ["*:read", "requisition:order", "requisition:cancel", "purchase_order:*", "purchase_order_line:*",
              "supplier:create", "supplier:update", "supplier:submit", "supplier:activate", "supplier:suspend",
              "supplier:reinstate", "contract:*", "savings_initiative:*", "goods_receipt:create", "integrations:read",
              "rules:read"],
    "procurement_manager": ["*:read", "requisition:order", "requisition:cancel", "purchase_order:*",
                            "purchase_order_line:*", "supplier:*", "contract:*", "savings_initiative:*",
                            "spend_category:*", *_OVERSIGHT],
    "ap_clerk": ["*:read", "invoice:*", "payment:create", "payment:update", "payment_run:create", "payment_run:update",
                 "payment_run:approve", "integrations:read", "rules:read"],
    "treasury": ["*:read", "payment_run:release", "payment_run:complete", "payment:*", "invoice:schedule", "invoice:pay",
                 "exchange_rate:*", "integrations:read"],
    "finance_controller": ["*:read", "budget_line:*", "budget_change:*", "gl_account:*", "cost_center:*",
                           "exchange_rate:*", "setting:*", "integrations:manage", *_OVERSIGHT],
    "finance_director": ["*:read", *_OVERSIGHT],
    "cfo": ["*:read", *_OVERSIGHT],
    "auditor": ["*:read", *_OVERSIGHT],
    "admin": ["*"],
}

CHANNELS = {
    "approval_requested": ["email", "teams"],
    "approval_decided": ["email"],
    "sla_breached": ["email", "teams"],
}


def roles(*names: str) -> dict[str, str]:
    """The named roles (and admin), in the library's order. With no names, all of them."""
    wanted = set(names) | {"admin"} if names else set(ROLES)
    unknown = wanted - set(ROLES)
    if unknown:
        raise KeyError(f"the library has no role {', '.join(sorted(unknown))}; it has: {', '.join(ROLES)}")
    return {k: v for k, v in ROLES.items() if k in wanted}


def people(role_names: Iterable[str] | None = None, domain: str = "example.com") -> list[dict]:
    """One demonstration persona per role."""
    out = []
    for role in (role_names if role_names is not None else ROLES):
        p = PEOPLE.get(role)
        if p:
            first, last = p["full_name"].lower().split(" ", 1)
            out.append({**p, "email": f"{first}.{last.replace(' ', '')}@{domain}", "roles": [role]})
    return out


def permissions(role_names: Iterable[str] | None = None, extra: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """What each role may do. `extra` adds an application's own permissions to a role."""
    out = {}
    for role in (role_names if role_names is not None else ROLES):
        out[role] = list(dict.fromkeys(GRANTS.get(role, ["*:read"]) + list((extra or {}).get(role, []))))
    out.setdefault("admin", ["*"])
    return out
