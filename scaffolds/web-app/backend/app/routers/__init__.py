"""Every story's endpoints, discovered rather than listed by hand. Read-only.

Endpoints used to live in one routes.py that each story rewrote in full; a story
shown a truncated copy dropped an earlier story's endpoints. Now each story owns
backend/app/routers/<resource>.py with its own `router`, and this module finds
them all. The worked example is mounted only until a real router exists.

A router module that fails to import is not skipped: the error propagates, so
the test suite fails loudly and names the module instead of the endpoint
silently disappearing.
"""
from __future__ import annotations

import importlib
import pkgutil

EXAMPLE = "examples"
# The platform's generic data API: mounted last, so a story router that declares
# the same path is the one FastAPI matches.
GENERIC = "resources"


def _discover() -> list:
    names = sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))
    real = [n for n in names if n not in (EXAMPLE, GENERIC)]
    ordered = (real or [EXAMPLE]) + ([GENERIC] if GENERIC in names else [])
    found = []
    for name in ordered:
        module = importlib.import_module(f"{__name__}.{name}")
        router = getattr(module, "router", None)
        if router is not None:
            found.append(router)
    return found


routers = _discover()
