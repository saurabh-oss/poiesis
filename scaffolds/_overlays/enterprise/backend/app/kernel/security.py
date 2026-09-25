"""Tokens and passwords, from the standard library. Written by Poiesis, and read-only.

A session token is `<payload>.<signature>`: the payload is base64url JSON (user id,
username, expiry) and the signature an HMAC-SHA256 over it with the application's
secret. APP_SECRET sets the secret; without it one is derived from the database URL,
so it is stable across restarts of the same deployment and differs between apps.
Passwords are PBKDF2-SHA256 with a per-user salt.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

TOKEN_HOURS = int(os.getenv("AUTH_TOKEN_HOURS", "12") or 12)
_ITERATIONS = 200_000


def _secret() -> bytes:
    explicit = os.getenv("APP_SECRET", "").strip()
    if explicit:
        return explicit.encode()
    seed = os.getenv("DATABASE_URL", "") + "|" + os.getenv("APP_NAME", "") + "|poiesis-app-secret"
    return hashlib.sha256(seed.encode()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(claims: dict[str, Any], hours: int = TOKEN_HOURS) -> str:
    payload = _b64(json.dumps({**claims, "exp": int(time.time()) + hours * 3600}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify(token: str) -> dict[str, Any] | None:
    """The claims of a valid, unexpired token; None for anything else."""
    try:
        payload, signature = token.split(".", 1)
    except (ValueError, AttributeError):
        return None
    expected = _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        claims = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(claims.get("exp", 0)) < time.time():
        return None
    return claims


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def check_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        _, iterations, salt, digest = stored.split("$")
        again = hashlib.pbkdf2_hmac("sha256", password.encode(), _unb64(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(_b64(again), digest)


def service_token() -> str:
    """The platform's own token (its API and browser checks), set per deployment."""
    return os.getenv("POIESIS_SERVICE_TOKEN", "").strip()
