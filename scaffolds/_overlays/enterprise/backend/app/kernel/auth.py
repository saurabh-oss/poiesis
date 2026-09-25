"""Signing in, and knowing who is calling. Written by Poiesis, and read-only.

Every /api request passes through `AuthMiddleware`, which reads the bearer token, looks
the person up (cached for a minute, so a deactivated account stops working quickly) and
sets the actor for the request. Without a valid token only the sign-in endpoints, the
profile and the platform's status answer; everything else is 401.

Demonstration personas (domain/policy.py PERSONAS) sign in with one click while
AUTH_PERSONAS is on, which it is unless set to "off". With it off, people sign in with
a password: AUTH_ADMIN_PASSWORD sets the administrator's, and the administrator can
set others'. POIESIS_SERVICE_TOKEN is the platform's own token for its checks.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import _sessionmaker, get_session
from . import audit, security
from .context import ANONYMOUS, Actor, current, reset, set_current
from .models import AppUser, Notification, utcnow
from .policy import policy

PUBLIC_PREFIXES = ("/api/auth/", "/api/status", "/api/platform/profile", "/api/platform/modules", "/health")
_CACHE: dict[int, tuple[float, Actor | None]] = {}
_CACHE_SECONDS = 60

router = APIRouter()


def personas_enabled() -> bool:
    return os.getenv("AUTH_PERSONAS", "on").strip().lower() not in ("off", "0", "false", "no")


def auth_required() -> bool:
    return os.getenv("AUTH_REQUIRED", "on").strip().lower() not in ("off", "0", "false", "no")


def actor_for(user: AppUser) -> Actor:
    roles = tuple(user.role_list())
    return Actor(user.id, user.username, user.full_name, roles, user.email or "", user.title or "",
                 "user", policy().granted(roles))


SERVICE = Actor(None, "poiesis", "Poiesis checks", ("admin",), kind="service", permissions=frozenset({"*"}))


def _lookup(user_id: int) -> Actor | None:
    hit = _CACHE.get(user_id)
    if hit and hit[0] > time.time():
        return hit[1]
    with _sessionmaker()() as s:
        user = s.get(AppUser, user_id)
        actor = actor_for(user) if user is not None and user.active else None
    _CACHE[user_id] = (time.time() + _CACHE_SECONDS, actor)
    return actor


def resolve(authorization: str) -> Actor:
    if not authorization.lower().startswith("bearer "):
        return ANONYMOUS
    token = authorization[7:].strip()
    service = security.service_token()
    if service and token == service:
        return SERVICE
    claims = security.verify(token)
    if not claims or not isinstance(claims.get("uid"), int):
        return ANONYMOUS
    return _lookup(claims["uid"]) or ANONYMOUS


class AuthMiddleware:
    """Pure ASGI, so the actor set here is the one every endpoint and listener sees."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        actor = resolve(headers.get("authorization", ""))
        tokens = set_current(actor, headers.get("x-request-id"))
        try:
            path = scope.get("path", "")
            if path.startswith("/api/") and not path.startswith(PUBLIC_PREFIXES) \
                    and actor.kind == "anonymous" and auth_required():
                body = json.dumps({"detail": "sign in first"}).encode()
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
            await self.app(scope, receive, send)
        finally:
            reset(tokens)


def ensure_users() -> int:
    """Create or refresh a user for every persona the policy declares. Idempotent."""
    p = policy()
    made = 0
    with _sessionmaker()() as s:
        for persona in p.personas:
            username = str(persona.get("username", "")).strip().lower()
            if not username:
                continue
            user = s.query(AppUser).filter_by(username=username).first()
            if user is None:
                user = AppUser(username=username, full_name=persona.get("full_name") or username.title())
                s.add(user)
                made += 1
            user.full_name = persona.get("full_name") or user.full_name
            user.email = persona.get("email") or user.email or f"{username}@example.com"
            user.title = persona.get("title") or user.title or ""
            user.team = persona.get("team") or user.team or ""
            user.roles = ",".join(persona.get("roles") or [])
            user.persona = True
        admin_password = os.getenv("AUTH_ADMIN_PASSWORD", "").strip()
        if admin_password:
            for user in s.query(AppUser).all():
                if "admin" in user.role_list() and not user.password_hash:
                    user.password_hash = security.hash_password(admin_password)
        s.commit()
    return made


def _user_out(u: AppUser) -> dict[str, Any]:
    roles = policy().roles
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "title": u.title, "team": u.team,
            "email": u.email, "roles": [{"key": r, "label": roles.get(r, r.replace("_", " ").title())} for r in u.role_list()]}


@router.get("/auth/personas")
def personas(db: Session = Depends(get_session)) -> dict[str, Any]:
    """Who can sign in with one click (demonstration mode), for the sign-in screen."""
    users = db.query(AppUser).filter(AppUser.persona.is_(True), AppUser.active.is_(True)).order_by(AppUser.id).all() \
        if personas_enabled() else []
    return {"mode": "personas" if personas_enabled() else "password", "personas": [_user_out(u) for u in users],
            "policy_error": policy().error}


class SignIn(BaseModel):
    username: str
    password: str | None = None


@router.post("/auth/sign-in")
def sign_in(payload: SignIn, db: Session = Depends(get_session)) -> dict[str, Any]:
    user = db.query(AppUser).filter_by(username=payload.username.strip().lower()).first()
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="no such user")
    if payload.password:
        if not security.check_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="wrong password")
    elif not (user.persona and personas_enabled()):
        raise HTTPException(status_code=401, detail="a password is required")
    user.last_sign_in = utcnow()
    actor = actor_for(user)
    tokens = set_current(actor)
    try:
        audit.record(db, "sign_in", f"{user.full_name} signed in", entity="sys_user", entity_id=user.id)
        db.commit()
    finally:
        reset(tokens)
    _CACHE.pop(user.id, None)
    return {"token": security.issue({"uid": user.id, "u": user.username}), "user": _user_out(user)}


@router.get("/auth/me")
def me(db: Session = Depends(get_session)) -> dict[str, Any]:
    actor = current()
    if actor.kind == "anonymous":
        raise HTTPException(status_code=401, detail="sign in first")
    unread = 0
    if actor.id is not None:
        unread = db.query(Notification).filter(Notification.user_id == actor.id, Notification.read_at.is_(None)).count()
    roles = policy().roles
    return {**actor.as_dict(), "role_labels": [roles.get(r, r.replace("_", " ").title()) for r in actor.roles],
            "unread": unread, "screens": policy().screens}


class Password(BaseModel):
    username: str
    password: str


@router.post("/auth/password")
def set_password(payload: Password, db: Session = Depends(get_session)) -> dict[str, Any]:
    """An administrator sets someone's password; anyone sets their own."""
    actor = current()
    if actor.kind == "anonymous":
        raise HTTPException(status_code=401, detail="sign in first")
    user = db.query(AppUser).filter_by(username=payload.username.strip().lower()).first()
    if user is None:
        raise HTTPException(status_code=404, detail="no such user")
    if user.id != actor.id and "admin" not in actor.roles and actor.kind != "service":
        raise HTTPException(status_code=403, detail="only an administrator sets someone else's password")
    if len(payload.password) < 10:
        raise HTTPException(status_code=422, detail="use at least 10 characters")
    user.password_hash = security.hash_password(payload.password)
    audit.record(db, "update", f"Password set for {user.full_name}", entity="sys_user", entity_id=user.id)
    db.commit()
    return {"ok": True}
