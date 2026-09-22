"""Test fixtures for {{project_name}}.

The test suite runs in a throwaway container with no Postgres, so anything that
touches the database would fail with "connection refused" — which reads like
broken feature code when it is only a missing service. Rather than start a
database for every test run, the session dependency is overridden with an
in-memory SQLite one, created fresh for each test.

That database starts with the same rows the deployed application opens with:
every INSERT in db/init.sql is loaded after the tables are created, so a test
sees the agents, tickets and incidents a first-time visitor sees. Anything a
test needs beyond that, it creates itself. Use the `client` fixture and it is
wired for you.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 — registers the tables on Base.metadata
from app.db import Base, get_session
from app.main import app

INIT_SQL = Path(__file__).resolve().parents[1] / "db" / "init.sql"


def _statements(sql: str) -> list[str]:
    """Split on semicolons outside quoted strings and comments."""
    out, start, i, quote = [], 0, 0, ""
    while i < len(sql):
        ch = sql[i]
        if quote:
            if ch == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    i += 1
                else:
                    quote = ""
        elif ch in "'\"":
            quote = ch
        elif sql.startswith("--", i):
            i = sql.find("\n", i)
            if i < 0:
                break
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            i = len(sql) if end < 0 else end + 1
        elif ch == ";":
            statement = sql[start:i + 1].strip()
            if statement:
                out.append(statement)
            start = i + 1
        i += 1
    tail = sql[start:].strip()
    if tail:
        out.append(tail)
    return out


def seed_from_init_sql(engine) -> int:
    """Load db/init.sql's INSERT rows into the test database. Returns rows attempted.

    The tables come from the models (create_all); only the data comes from
    init.sql. A statement that uses something SQLite cannot run (a Postgres-only
    expression, say) is skipped on its own, so one exotic row never empties the
    rest of the seed.
    """
    if not INIT_SQL.is_file():
        return 0
    loaded = 0
    with engine.begin() as conn:
        for stmt in _statements(INIT_SQL.read_text(encoding="utf-8", errors="replace")):
            if not stmt.lstrip().upper().startswith("INSERT"):
                continue
            try:
                with conn.begin_nested():
                    conn.exec_driver_sql(stmt)
                loaded += 1
            except Exception:  # noqa: BLE001 — that statement is simply absent under test
                continue
    return loaded


@pytest.fixture()
def db_session():
    """A real session against a private in-memory database, seeded like production."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        # One shared connection, or each checkout gets its own empty database.
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    seed_from_init_sql(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False, future=True)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    """A TestClient whose endpoints use the test database.

    Always take this fixture instead of constructing TestClient yourself — a bare
    client talks to the real DATABASE_URL, which does not exist under test.
    """
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
