"""Roles and permissions. Written by Poiesis, and read-only.

The application declares its policy in `domain/policy.py`:

    ROLES = {"agent": "Support agent", "lead": "Support lead", "admin": "Administrator"}
    PERSONAS = [{"username": "priya", "full_name": "Priya Shah", "title": "Support lead", "roles": ["lead"]}, …]
    PERMISSIONS = {
        "agent": ["ticket:read", "ticket:create", "ticket:update", "ticket:resolve"],
        "lead":  ["ticket:*", "cluster:*", "setting:read", "audit:read", "integrations:read"],
        "admin": ["*"],
    }
    SCREENS = {"accuracy_settings": ["lead", "admin"]}      # optional: who sees which screen

A permission is `<entity>:<action>`. The action is read, create, update or delete for
the generic data API, a transition's name for a workflow, or anything the domain
checks for itself (`ticket:merge`). `*` matches everything, `ticket:*` every action on
tickets, `*:read` reading anything. `admin` holds every permission.

Endpoints use it as a dependency, and the generic data API checks it on every call:

    @router.post("/tickets/{id}/merge", dependencies=[Depends(require("ticket:merge"))])
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Iterable

from fastapi import HTTPException

from .context import Actor, current

log = logging.getLogger(__name__)

DEFAULT_ROLES = {"admin": "Administrator"}
DEFAULT_PERSONAS = [{"username": "admin", "full_name": "Administrator", "title": "Administrator", "roles": ["admin"]}]
PLATFORM_PERMISSIONS = {
    "audit:read": "Read the audit trail",
    "rules:read": "Read the business rule catalogue",
    "integrations:read": "See connectors and their outbox",
    "integrations:manage": "Retry and test connectors",
    "users:read": "See people and their roles",
}


class Policy:
    def __init__(self) -> None:
        self.roles: dict[str, str] = dict(DEFAULT_ROLES)
        self.personas: list[dict[str, Any]] = list(DEFAULT_PERSONAS)
        self.permissions: dict[str, list[str]] = {"admin": ["*"]}
        self.screens: dict[str, list[str]] = {}
        self.error: str = ""
        self.loaded = False

    def load(self) -> "Policy":
        try:
            module = importlib.import_module(__package__.rsplit(".", 1)[0] + ".domain.policy")
        except ModuleNotFoundError:
            self.loaded = True
            return self
        except Exception as exc:  # noqa: BLE001 — a broken policy must be visible, not fatal
            self.error = f"{type(exc).__name__}: {exc}"
            log.error("domain/policy.py did not load: %s", self.error)
            self.loaded = True
            return self
        self.roles = {**DEFAULT_ROLES, **dict(getattr(module, "ROLES", {}) or {})}
        self.personas = list(getattr(module, "PERSONAS", []) or DEFAULT_PERSONAS)
        declared = {k: list(v) for k, v in (getattr(module, "PERMISSIONS", {}) or {}).items()}
        self.permissions = {**declared, "admin": ["*"]}
        self.screens = {k: list(v) for k, v in (getattr(module, "SCREENS", {}) or {}).items()}
        self.loaded = True
        return self

    def granted(self, roles: Iterable[str]) -> frozenset[str]:
        out: set[str] = set()
        for role in roles:
            out.update(self.permissions.get(role, []))
        return frozenset(out)

    def check_persona(self) -> str:
        """The persona the platform's browser check signs in as: an administrator when
        there is one (every screen is visible to them), else whoever holds most permissions."""
        def reach(p: dict[str, Any]) -> tuple[bool, int]:
            roles = p.get("roles", [])
            return "admin" in roles, len(self.granted(roles))
        best = max(self.personas, key=reach, default=DEFAULT_PERSONAS[0])
        return str(best.get("username", "admin"))


POLICY = Policy()


def policy() -> Policy:
    if not POLICY.loaded:
        POLICY.load()
    return POLICY


def matches(granted: Iterable[str], permission: str) -> bool:
    entity, _, action = permission.partition(":")
    for g in granted:
        if g == "*" or g == permission:
            return True
        g_entity, _, g_action = g.partition(":")
        if g_action == "*" and g_entity == entity:
            return True
        if g_entity == "*" and g_action == action:
            return True
    return False


def can(permission: str, actor: Actor | None = None) -> bool:
    actor = actor or current()
    if actor.kind in ("system", "service") or "admin" in actor.roles:
        return True
    return matches(actor.permissions, permission)


def ensure(permission: str, actor: Actor | None = None, what: str = "") -> None:
    """Raise 403 unless the actor holds the permission (401 when nobody is signed in)."""
    actor = actor or current()
    if actor.kind == "anonymous":
        raise HTTPException(status_code=401, detail="sign in first")
    if not can(permission, actor):
        roles = ", ".join(actor.roles) or "none"
        raise HTTPException(status_code=403, detail=(
            f"{actor.name} ({roles}) may not {what or permission}: it needs the '{permission}' permission"))


def require(permission: str):
    """FastAPI dependency: `dependencies=[Depends(require("ticket:merge"))]`."""
    def dependency() -> Actor:
        ensure(permission)
        return current()
    dependency.__name__ = f"require_{permission.replace(':', '_').replace('*', 'any')}"
    return dependency


def require_role(*roles: str):
    """FastAPI dependency for a role rather than a permission."""
    def dependency() -> Actor:
        actor = current()
        if actor.kind == "anonymous":
            raise HTTPException(status_code=401, detail="sign in first")
        if actor.kind not in ("system", "service") and not actor.has_role(*roles):
            raise HTTPException(status_code=403, detail=f"{actor.name} needs one of the roles: {', '.join(roles)}")
        return actor
    return dependency


def visible_screens(actor: Actor, screen_ids: Iterable[str]) -> list[str]:
    p = policy()
    out = []
    for sid in screen_ids:
        allowed = p.screens.get(sid)
        if not allowed or actor.kind in ("system", "service") or actor.has_role(*allowed):
            out.append(sid)
    return out
