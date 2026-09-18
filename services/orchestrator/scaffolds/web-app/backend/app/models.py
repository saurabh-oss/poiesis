"""ORM models for {{project_name}}.

>>> THIS IS THE SLOT for persistent entities. <<<

Every table needs two things to exist at runtime:
  1. A class here, inheriting Base.
  2. A matching CREATE TABLE in db/init.sql, which Postgres runs on first start.

Keep the two in step. There is no migration tool in this scaffold by design —
one file of SQL is easier to get right than an Alembic chain, and the database
is recreated on each deployment.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class Example(Base):
    """Worked example, paired with the /examples routes, schemas.py and init.sql.

    Remove all four together once real models exist.
    """

    __tablename__ = "example"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc)
    )
