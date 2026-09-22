"""The knowledge graph and the vector index over it, for the control room and operators."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from ..kg import vectors
from ..kg.client import kg
from ..reuse.retriever import portfolio_context

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

_reindex: asyncio.Task | None = None


@router.get("/capabilities")
async def capabilities():
    return await kg().capability_map()


@router.get("/stack")
async def stack():
    return await kg().house_stack()


@router.get("/search")
async def search(q: str):
    return await kg().find_reusable([t for t in q.split() if t])


@router.get("/recall")
async def recall(q: str, limit: int = 8):
    """Hybrid recall: the graph's word match and the vector index's meaning match, side by side."""
    words = [t for t in q.split() if t]
    graph_hits, comps, stories, lessons, decisions = await asyncio.gather(
        kg().find_reusable(words, limit=limit),
        vectors.search("components", q, limit=limit),
        vectors.search("stories", q, limit=limit),
        vectors.search("lessons", q, limit=limit),
        vectors.search("decisions", q, limit=limit),
    )
    return {"graph": graph_hits, "components": comps, "stories": stories,
            "lessons": lessons, "decisions": decisions}


@router.get("/lessons")
async def lessons(limit: int = 100):
    return await kg().lessons(limit=limit)


@router.get("/stats")
async def stats():
    return {"graph": await kg().stats(), "vectors": await vectors.counts(),
            "vectors_enabled": vectors.enabled()}


@router.get("/runs/{run_id}/graph")
async def run_graph(run_id: str):
    """What one run added to the graph: its project, stories, capabilities, decisions, reuse."""
    rows = await kg().run_lineage(run_id)
    if not rows:
        raise HTTPException(404, "this run has not been harvested into the graph")
    return rows


@router.post("/preview-reuse")
async def preview_reuse(payload: dict):
    """What would the architect find if this brief were submitted right now?"""
    return await portfolio_context(payload.get("brief", ""))


@router.post("/reindex")
async def reindex():
    """Embed every component the graph holds into the vector index. Runs in the background."""
    global _reindex
    if _reindex and not _reindex.done():
        return {"status": "already running"}

    async def work() -> None:
        rows = await kg().all_components()
        await vectors.reindex_components(rows)

    _reindex = asyncio.create_task(work())
    return {"status": "started"}


@router.get("/reindex")
async def reindex_status():
    if _reindex is None:
        return {"status": "never run", "vectors": await vectors.counts()}
    if not _reindex.done():
        return {"status": "running"}
    exc = _reindex.exception()
    return {"status": "failed" if exc else "done", "error": str(exc) if exc else "",
            "vectors": await vectors.counts()}


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
