"""Test fixtures for {{project_name}}.

The test suite runs in a throwaway container with no Postgres, so anything that
touches the database would fail with "connection refused" — which reads like
broken feature code when it is only a missing service. Rather than start a
database for every test run, the session dependency is overridden with an
in-memory SQLite one, created fresh for each test.

That gives every test a real database with real tables and no shared state, and
it costs nothing to start. Use the `client` fixture and it is wired for you.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401 — registers the tables on Base.metadata
from app.db import Base, get_session
from app.main import app


@pytest.fixture()
def db_session():
    """A real session against a private in-memory database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        # One shared connection, or each checkout gets its own empty database.
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
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
