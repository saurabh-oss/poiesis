"""The enterprise overlay as the control room sees it: the reusable connectors every
enterprise app carries, and each app's business logic (roles, rules, workflows, tests).

    GET /api/enterprise/connectors          the catalogue, with how apps would run each one
    GET /api/enterprise/runs/{id}/domain    one run's domain: rules and their tests, workflows, roles
"""
from __future__ import annotations

import importlib.util
import os
import sys
from functools import lru_cache
from types import ModuleType
from typing import Any

from fastapi import APIRouter, HTTPException

from ..config import scaffold_root
from ..db import Artifact, Deployment, Run, session

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])

KERNEL_FEATURES = [
    {"key": "auth", "title": "Sign-in, roles and permissions",
     "detail": "Demonstration personas or passwords; <table>:<action> permissions checked on every API call, the generic data API included."},
    {"key": "workflow", "title": "Workflows, approvals and SLAs",
     "detail": "Each record's lifecycle declared once and enforced by the server: role checks, rule guards, four-eyes approvals, SLA clocks and escalation."},
    {"key": "audit", "title": "Audit trail",
     "detail": "Every insert, update and delete through the ORM, with who, when and each field before and after; transitions, approvals and rule decisions too."},
    {"key": "rules", "title": "Business rule catalogue",
     "detail": "Every rule with its id, source in the brief, where it lives, how often it fired or refused, and what its tests proved."},
    {"key": "notify", "title": "Notifications",
     "detail": "An in-app inbox per person, fanned out to e-mail, Slack or Teams by policy, sent only after the transaction commits."},
    {"key": "outbox", "title": "Connector outbox and scheduler",
     "detail": "Every outside call recorded; retryable failures replayed by the scheduler, which also escalates SLA breaches."},
]


@lru_cache
def _connectors() -> ModuleType:
    """The overlay's connectors package, loaded from the scaffold so the catalogue is
    always what the applications actually ship."""
    root = scaffold_root() / "_overlays" / "enterprise" / "backend" / "app" / "connectors"
    name = "poiesis_overlay_connectors"
    spec = importlib.util.spec_from_file_location(name, root / "__init__.py", submodule_search_locations=[str(root)])
    if spec is None or spec.loader is None:
        raise RuntimeError("the enterprise overlay has no connectors package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _app_env() -> dict[str, str]:
    """What an enterprise app's app.env would carry: APPS_JIRA_BASE_URL → JIRA_BASE_URL."""
    return {k[5:]: v for k, v in os.environ.items() if k.startswith("APPS_") and v.strip()}


@router.get("/connectors")
def connectors() -> dict[str, Any]:
    try:
        mod = _connectors()
    except Exception as exc:  # noqa: BLE001 — a broken overlay is shown, not hidden
        raise HTTPException(status_code=500, detail=f"the connectors did not load: {exc}") from exc
    env = _app_env()
    out = []
    for name, cls in mod.CONNECTORS.items():
        status = cls(env=env).status()
        file = sys.modules[cls.__module__].__file__ or ""
        try:
            lines = sum(1 for _ in open(file, encoding="utf-8"))
        except OSError:
            lines = 0
        status["source"] = f"scaffolds/_overlays/enterprise/backend/app/connectors/{os.path.basename(file)}"
        status["lines"] = lines
        out.append(status)
    with session() as s:
        ids = {rid for (rid,) in s.query(Artifact.run_id).filter(Artifact.kind == "domain").distinct()}
        runs = s.query(Run).filter(Run.id.in_(ids)).order_by(Run.created_at.desc()).all() if ids else []
        deployed = {d.run_id: d for d in s.query(Deployment).filter(Deployment.run_id.in_(ids)).all()} if ids else {}
        apps = []
        for r in runs:
            art = s.query(Artifact).filter_by(run_id=r.id, kind="domain").order_by(Artifact.version.desc()).first()
            body = art.body if art else {}
            d = deployed.get(r.id)
            apps.append({"run_id": r.id, "title": r.title, "status": r.status,
                         "rules": len(body.get("rules") or []), "workflows": len(body.get("workflows") or []),
                         "roles": len(body.get("roles") or {}), "tests": body.get("tests") or {},
                         "url": d.url if d and d.status == "running" else None})
    return {"connectors": out, "kernel": KERNEL_FEATURES, "apps": apps,
            "live_settings": sorted(env)}


@router.get("/runs/{run_id}/domain")
def run_domain(run_id: str) -> dict[str, Any]:
    with session() as s:
        art = s.query(Artifact).filter_by(run_id=run_id, kind="domain").order_by(Artifact.version.desc()).first()
        if art is None:
            raise HTTPException(status_code=404, detail="this run has no domain layer (not built with the enterprise pack)")
        d = s.get(Deployment, run_id)
        return {**art.body, "url": d.url if d and d.status == "running" else None}
