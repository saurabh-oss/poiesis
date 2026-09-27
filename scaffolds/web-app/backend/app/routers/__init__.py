"""Every story's endpoints, discovered rather than listed by hand. Read-only.

Endpoints used to live in one routes.py that each story rewrote in full; a story
shown a truncated copy dropped an earlier story's endpoints. Now each story owns
backend/app/routers/<resource>.py with its own `router`, and this module finds
them all. The worked example is mounted only until a real router exists.

A router module that fails to import is isolated, not fatal. One story's
`NameError` used to stop the whole API from starting, so every screen of every
story went dark and the deployment failed outright. Now the broken module is
left out, the rest of the API starts, and the failure is recorded in `broken`
(module -> the error), served at /api/platform/modules and checked by the
platform before deploy, so it is repaired rather than hidden.
"""
from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import traceback

EXAMPLE = "examples"
# The platform's generic data API: mounted last, so a story router that declares
# the same path is the one FastAPI matches.
GENERIC = "resources"

log = logging.getLogger(__name__)


def _tolerate_return_annotations() -> None:
    """A route written `def approve(...) -> PurchaseOrder:` means "it returns an order", not "validate
    the reply against this class": FastAPI reads the annotation as a response model, cannot make one
    of an ORM class, and refuses the whole router ("Invalid args for response field"), taking every
    endpoint of the story with it. Such a route is registered without a response model instead."""
    from fastapi import routing
    from fastapi.exceptions import FastAPIError
    if getattr(routing.APIRouter.add_api_route, "_poiesis_tolerant", False):
        return
    original = routing.APIRouter.add_api_route

    def add_api_route(self, path, endpoint, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return original(self, path, endpoint, **kwargs)
        except FastAPIError as exc:
            if "response field" not in str(exc):
                raise
            log.warning("%s %s: its return annotation is not a response model; registered without one", endpoint.__name__, path)
            return original(self, path, endpoint, **{**kwargs, "response_model": None})

    add_api_route._poiesis_tolerant = True  # type: ignore[attr-defined]
    routing.APIRouter.add_api_route = add_api_route  # type: ignore[method-assign]


_tolerate_return_annotations()

# module name -> "file:line: ErrorType: message" for every router that did not load.
broken: dict[str, str] = {}


def _where(exc: BaseException) -> str:
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if "/routers/" in f.filename.replace("\\", "/")]
    at = f"{frames[-1].filename.replace(chr(92), '/').split('/app/', 1)[-1]}:{frames[-1].lineno}: " if frames else ""
    return f"{at}{type(exc).__name__}: {exc}"


def _discover() -> list:
    names = sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith("_"))
    real = [n for n in names if n not in (EXAMPLE, GENERIC)]
    ordered = (real or [EXAMPLE]) + ([GENERIC] if GENERIC in names else [])
    found = []
    for name in ordered:
        try:
            module = importlib.import_module(f"{__name__}.{name}")
        except Exception as exc:  # noqa: BLE001 — isolate it; the rest of the API still starts
            broken[name] = _where(exc)
            log.error("router %s did not load and is left out: %s", name, broken[name])
            continue
        router = getattr(module, "router", None)
        if router is not None:
            found.append(router)
    return found


# The data service imports this package only to reach routers/resources.py; it
# must not load story code, or a broken story module would reach it too.
routers = [] if os.getenv("POIESIS_SERVICE") == "data" else _discover()
