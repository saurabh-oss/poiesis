"""The generic data API for {{project_name}}. Written by Poiesis, and read-only.

Every table in models.py is served under /api without anyone writing a router
for it, so a screen can list, search, filter, sort, read, create, update and
delete rows the moment the model exists:

    GET    /api/<resources>                 list, newest id first by default
           ?q=text                          search every text column
           ?<column>=value                  exact filter, repeatable, any column
           ?sort=column | ?sort=-column     order by a column, `-` for descending
           ?limit=200&offset=0              paging (limit defaults to 500)
    GET    /api/<resources>/{id}            one row, 404 when absent
    POST   /api/<resources>                 body: {column: value}; 201 with the row
    PATCH  /api/<resources>/{id}            body: the columns to change; the row
    DELETE /api/<resources>/{id}            204
    GET    /api/resources                   every table, its path and its columns

<resources> is the table name in kebab-case plural: `ticket` -> /api/tickets,
`incident_audit_entry` -> /api/incident-audit-entries. Rows are plain JSON
objects with one key per column. A story router that declares the same path
wins: story routers are mounted before this one, and FastAPI keeps the first
match, so a story replaces exactly the endpoints it needs and inherits the rest.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import String, Text, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models  # noqa: F401 — registers every table on Base.metadata
from ..db import Base, get_session

router = APIRouter()

_RESERVED = {"q", "sort", "limit", "offset"}


def plural(table: str) -> str:
    """`incident_audit_entry` -> `incident-audit-entries`."""
    word = table.replace("_", "-").lower()
    if word.endswith("s") and not word.endswith("ss"):
        return word
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def _serialize(row: Any, columns: list[Any]) -> dict[str, Any]:
    return {c.key: getattr(row, c.key) for c in columns}


def _coerce(column: Any, value: Any) -> Any:
    """Turn a query-string or JSON value into what the column stores."""
    if value is None or value == "":
        return None
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return value
    try:
        if python_type is bool and isinstance(value, str):
            return value.lower() in ("1", "true", "yes", "on")
        if python_type in (int, float) and isinstance(value, str):
            return python_type(value)
        if python_type is dt.datetime and isinstance(value, str):
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if python_type is dt.date and isinstance(value, str):
            return dt.date.fromisoformat(value[:10])
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{column.key}: {value!r} is not a valid {python_type.__name__}")
    return value


def _register(cls: type) -> None:
    table = cls.__tablename__
    path = f"/{plural(table)}"
    mapper = cls.__mapper__
    columns = list(mapper.columns)
    by_key = {c.key: c for c in columns}
    pk = mapper.primary_key[0]
    text_columns = [c for c in columns if isinstance(c.type, (String, Text))]
    name = re.sub(r"[^a-z0-9]+", "_", plural(table))

    def get_or_404(db: Session, item_id: int) -> Any:
        row = db.get(cls, item_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"{table} {item_id} not found")
        return row

    def list_rows(request: Request, db: Session = Depends(get_session)) -> list[dict[str, Any]]:
        query = db.query(cls)
        params = request.query_params
        q = (params.get("q") or "").strip()
        if q and text_columns:
            query = query.filter(or_(*[c.ilike(f"%{q}%") for c in text_columns]))
        for key in params.keys():
            if key in _RESERVED or key not in by_key:
                continue
            values = [_coerce(by_key[key], v) for v in params.getlist(key)]
            query = query.filter(by_key[key].in_(values)) if len(values) > 1 else query.filter(by_key[key] == values[0])
        sort = params.get("sort") or f"-{pk.key}"
        column = by_key.get(sort.lstrip("-"))
        if column is not None:
            query = query.order_by(column.desc() if sort.startswith("-") else column.asc())
        limit = min(int(params.get("limit") or 500), 5000)
        offset = int(params.get("offset") or 0)
        return [_serialize(r, columns) for r in query.offset(offset).limit(limit).all()]

    def read_row(item_id: int, db: Session = Depends(get_session)) -> dict[str, Any]:
        return _serialize(get_or_404(db, item_id), columns)

    def create_row(payload: dict[str, Any], db: Session = Depends(get_session)) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="the body must be a JSON object")
        values = {k: _coerce(by_key[k], v) for k, v in payload.items() if k in by_key and k != pk.key}
        row = cls(**values)
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc.orig).splitlines()[0]) from exc
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc).splitlines()[0]) from exc
        db.refresh(row)
        return _serialize(row, columns)

    def update_row(item_id: int, payload: dict[str, Any], db: Session = Depends(get_session)) -> dict[str, Any]:
        row = get_or_404(db, item_id)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="the body must be a JSON object")
        for k, v in payload.items():
            if k in by_key and k != pk.key:
                setattr(row, k, _coerce(by_key[k], v))
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc.orig).splitlines()[0]) from exc
        db.refresh(row)
        return _serialize(row, columns)

    def delete_row(item_id: int, db: Session = Depends(get_session)):
        db.delete(get_or_404(db, item_id))
        db.commit()
        return Response(status_code=204)

    router.add_api_route(path, list_rows, methods=["GET"], name=f"list_{name}", summary=f"List {plural(table)}")
    router.add_api_route(path + "/{item_id}", read_row, methods=["GET"], name=f"read_{name}")
    router.add_api_route(path, create_row, methods=["POST"], status_code=201, name=f"create_{name}")
    router.add_api_route(path + "/{item_id}", update_row, methods=["PATCH", "PUT"], name=f"update_{name}")
    router.add_api_route(path + "/{item_id}", delete_row, methods=["DELETE"], status_code=204,
                         response_class=Response, name=f"delete_{name}")


def catalogue() -> list[dict[str, Any]]:
    out = []
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        out.append({
            "table": cls.__tablename__,
            "path": f"/api/{plural(cls.__tablename__)}",
            "columns": [{"name": c.key, "type": str(c.type), "nullable": bool(c.nullable)} for c in mapper.columns],
        })
    return sorted(out, key=lambda t: t["table"])


@router.get("/resources")
def list_resources() -> list[dict[str, Any]]:
    """Every table this API serves, with its path and columns."""
    return catalogue()


for _mapper in sorted(Base.registry.mappers, key=lambda m: m.class_.__tablename__):
    _register(_mapper.class_)
