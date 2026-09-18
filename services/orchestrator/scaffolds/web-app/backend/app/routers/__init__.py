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


def _discover() -> list:
    names = sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))
    real = [n for n in names if n != EXAMPLE]
    found = []
    for name in real or names:
        module = importlib.import_module(f"{__name__}.{name}")
        router = getattr(module, "router", None)
        if router is not None:
            found.append(router)
    return found


routers = _discover()
