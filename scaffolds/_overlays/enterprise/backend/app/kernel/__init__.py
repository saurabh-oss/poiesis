"""The enterprise kernel: sign-in and roles, audit, workflows and approvals, business
rules, notifications, the connectors' outbox and scheduled work. Written by Poiesis,
and read-only.

main.py and data_main.py call `install(app, service)` when this package exists, and
the api service calls `startup()` from its lifespan. Stories use it through a few names:

    from ..kernel import current, require, can, check, rule, violation, transition, notify, record

    @router.post("/tickets/{ticket_id}/merge", dependencies=[Depends(require("ticket:merge"))])
    def merge(ticket_id: int, db: Session = Depends(get_session)): …

The application's own policy, rules and workflows live in backend/app/domain/, which
this package imports at install time.
"""
from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import traceback
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import audit, models  # noqa: F401 — the kernel's tables join Base.metadata
from .audit import record
from .context import SYSTEM, Actor, acting_as, current
from .notify import notify
from .policy import can, ensure, policy, require, require_role
from .rules import RuleViolation, check, declare, rule, violation
from .workflow import Transition, Workflow, available, decide, register, transition

log = logging.getLogger(__name__)
APP = __package__.rsplit(".", 1)[0]
DOMAIN = APP + ".domain"
# A library is a package beside this one that a pack's overlay brings (finance, …). One that
# has an api.py with a `router` is served under /api; name -> "" once mounted, or why it was not.
LIBRARIES: dict[str, str] = {}
_NOT_A_LIBRARY = ("kernel", "connectors", "domain", "routers")


def _load_domain() -> str:
    """Import backend/app/domain (policy, rules, workflows). Returns the error, if any."""
    try:
        importlib.import_module(DOMAIN)
    except ModuleNotFoundError as exc:
        if exc.name == DOMAIN:
            return ""
        return _where(exc)
    except Exception as exc:  # noqa: BLE001 — shown on the profile and the sign-in screen, not fatal
        return _where(exc)
    return ""


def _where(exc: BaseException, part: str = "/domain/") -> str:
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if part in f.filename.replace("\\", "/")]
    at = f"{frames[-1].filename.replace(chr(92), '/').split('/app/', 1)[-1]}:{frames[-1].lineno}: " if frames else ""
    return f"{at}{type(exc).__name__}: {exc}"


def _mount_libraries(app: FastAPI) -> None:
    """Serve every library's API. One that fails to import is left out and named on the
    profile; the application and the other libraries still start."""
    for found in pkgutil.iter_modules(importlib.import_module(APP).__path__):
        if not found.ispkg or found.name in _NOT_A_LIBRARY or found.name.startswith("_"):
            continue
        try:
            if importlib.util.find_spec(f"{APP}.{found.name}.api") is None:
                continue
            router = getattr(importlib.import_module(f"{APP}.{found.name}.api"), "router", None)
        except Exception as exc:  # noqa: BLE001 — isolate it, as a broken story router is
            LIBRARIES[found.name] = _where(exc, f"/{found.name}/")
            log.error("library %s did not load and is left out: %s", found.name, LIBRARIES[found.name])
            continue
        if router is not None:
            app.include_router(router, prefix="/api")
            LIBRARIES[found.name] = ""


async def _rule_violation(_request: Any, exc: RuleViolation) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.as_dict())


def install(app: FastAPI, service: str = "api") -> None:
    """Mount the kernel on an application. Call it before the story routers are included."""
    from .. import connectors
    from .api import DOMAIN_ERROR, router as platform_router
    from .auth import AuthMiddleware, router as auth_router
    from .outbox import DbStore

    from .notify import install as deliver_after_commit
    audit.install()
    deliver_after_commit()
    connectors.set_store(DbStore())
    error = _load_domain()
    if error:
        DOMAIN_ERROR["domain"] = error
        log.error("backend/app/domain did not load: %s", error)
    policy().load()
    app.add_middleware(AuthMiddleware)
    app.add_exception_handler(RuleViolation, _rule_violation)
    app.include_router(auth_router, prefix="/api")
    app.include_router(platform_router, prefix="/api")
    if service == "api":
        _mount_libraries(app)
        for name, problem in LIBRARIES.items():
            if problem:
                DOMAIN_ERROR[f"library {name}"] = problem
    app.state.poiesis_service = service


def startup(service: str = "api") -> None:
    """The kernel's tables and the personas' accounts, then (api only) the scheduler."""
    from ..db import Base, engine
    from .auth import ensure_users
    try:
        Base.metadata.create_all(engine(), tables=[m.__table__ for m in models.PLATFORM_MODELS])
    except Exception as exc:  # noqa: BLE001 — the other service may be creating them at the same moment
        log.info("kernel tables: %s", str(exc).splitlines()[0])
    try:
        ensure_users()
    except Exception as exc:  # noqa: BLE001 — the database may be restoring; sign-in says so
        log.warning("could not create the personas' accounts: %s", exc)
    if service == "api":
        from . import jobs
        jobs.start()


def shutdown() -> None:
    from . import jobs
    jobs.stop()


def allow(table: str, action: str) -> None:
    """The generic data API's check: may the current actor <action> rows of <table>?"""
    ensure(f"{table}:{action}", what=f"{action} {table.replace('_', ' ')} records")


def is_platform_table(cls: type) -> bool:
    return bool(getattr(cls, "__poiesis_platform__", False))


__all__ = [
    "SYSTEM", "Actor", "RuleViolation", "Transition", "Workflow", "acting_as", "allow", "available", "can", "check",
    "current", "decide", "declare", "ensure", "install", "is_platform_table", "notify", "policy", "record", "register", "require",
    "require_role", "rule", "startup", "transition", "violation",
]
