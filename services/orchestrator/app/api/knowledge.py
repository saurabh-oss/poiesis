from __future__ import annotations

from fastapi import APIRouter

from ..kg.client import kg
from ..reuse.retriever import portfolio_context

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/capabilities")
async def capabilities():
    return await kg().capability_map()


@router.get("/stack")
async def stack():
    return await kg().house_stack()


@router.get("/search")
async def search(q: str):
    return await kg().find_reusable([t for t in q.split() if t])


@router.post("/preview-reuse")
async def preview_reuse(payload: dict):
    """What would the architect find if this brief were submitted right now?"""
    return await portfolio_context(payload.get("brief", ""))


@router.get("/graph")
async def graph(limit: int = 300):
    return await kg().run(
        """
        MATCH (a)-[r]->(b)
        WHERE a:Project OR a:Capability OR a:Component OR a:Technology
        RETURN labels(a)[0] AS from_type, coalesce(a.name, a.id) AS from_name,
               type(r) AS rel,
               labels(b)[0] AS to_type, coalesce(b.name, b.id) AS to_name
        LIMIT $limit
        """,
        limit=limit,
    )
