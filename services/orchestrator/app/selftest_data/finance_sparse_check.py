"""Every GET the application serves, called bare with the platform's token, as its smoke check does:
none may answer 4xx or 5xx, whichever of the standard tables the application has.

    PYTHONPATH=backend python finance_sparse_check.py
"""
import os
import re

DB_FILE = os.environ.get("FIN_DB", "/tmp/sparse.db")
os.environ["DATABASE_URL"] = "sqlite:///" + DB_FILE
os.environ.setdefault("FINANCE_AS_OF", "2026-09-25")
os.environ.setdefault("JOB_SECONDS", "3600")
os.environ["POIESIS_SERVICE_TOKEN"] = "sparse-check"

if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

Base.metadata.create_all(engine())
bad, seen = [], 0
with TestClient(app, headers={"Authorization": "Bearer sparse-check"}) as client:
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods or not route.path.startswith("/api/"):
            continue
        parametrised = "{" in route.path
        r = client.get(re.sub(r"\{[^}]+\}", "1", route.path))
        seen += 1
        if r.status_code >= (500 if parametrised else 400):
            bad.append(f"{route.path} -> {r.status_code} {r.text[:200]}")
    tables = sorted(t for t in Base.metadata.tables if not t.startswith("sys_"))
print(f"{seen} GET routes over tables {tables}: {len(bad)} answered with an error")
for line in bad:
    print("  FAIL", line)
raise SystemExit(1 if bad else 0)
