"""Who is acting, for the length of one request or one job. Written by Poiesis, and read-only.

The audit listener, the workflow engine, the rules and the connectors all need to know
the actor without every function taking it as a parameter; a context variable carries
it from the authentication middleware to wherever a row is written.
"""
from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator


@dataclass(frozen=True)
class Actor:
    id: int | None
    username: str
    name: str
    roles: tuple[str, ...] = ()
    email: str = ""
    title: str = ""
    kind: str = "user"          # user | system | service
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has_role(self, *roles: str) -> bool:
        return bool(set(roles) & set(self.roles)) or "admin" in self.roles

    def as_dict(self) -> dict:
        return {"id": self.id, "username": self.username, "name": self.name, "roles": list(self.roles),
                "email": self.email, "title": self.title, "kind": self.kind,
                "permissions": sorted(self.permissions)}


SYSTEM = Actor(None, "system", "System", ("system",), kind="system", permissions=frozenset({"*"}))
ANONYMOUS = Actor(None, "anonymous", "Anonymous", (), kind="anonymous")

_actor: contextvars.ContextVar[Actor] = contextvars.ContextVar("poiesis_actor", default=ANONYMOUS)
_request: contextvars.ContextVar[str] = contextvars.ContextVar("poiesis_request", default="")


def current() -> Actor:
    """The actor of this request or job; `ANONYMOUS` outside one."""
    return _actor.get()


def request_id() -> str:
    return _request.get()


def set_current(actor: Actor, request: str | None = None) -> tuple[contextvars.Token, contextvars.Token]:
    return _actor.set(actor), _request.set(request or uuid.uuid4().hex[:12])


def reset(tokens: tuple[contextvars.Token, contextvars.Token]) -> None:
    _actor.reset(tokens[0])
    _request.reset(tokens[1])


@contextmanager
def acting_as(actor: Actor) -> Iterator[Actor]:
    """Run a block as someone else: the scheduler acts as SYSTEM, a test as a persona."""
    tokens = set_current(actor)
    try:
        yield actor
    finally:
        reset(tokens)
