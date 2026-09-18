"""Database access for {{project_name}}.

The engine is created lazily on purpose. Tests run in a throwaway sandbox with no
Postgres, so importing this module must never open a connection — otherwise the
whole suite fails at collection time and the failure looks like broken feature
code rather than a missing service.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app"
)


class Base(DeclarativeBase):
    pass


@lru_cache
def engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True, future=True)


@lru_cache
def _sessionmaker():
    return sessionmaker(bind=engine(), expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: `db: Session = Depends(get_session)`."""
    session = _sessionmaker()()
    try:
        yield session
    finally:
        session.close()
