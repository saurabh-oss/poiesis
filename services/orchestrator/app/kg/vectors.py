"""Vector recall over the knowledge graph.

Neo4j's full-text index finds a component when the Architect's search term is
*in* its name or docstring. It does not find `LeaveWindow.overlaps()` for the
term "double booking", or last quarter's lesson "seed the table the screen
reads" for a story about a dashboard. Embeddings do. This module keeps a
Qdrant collection per kind of thing worth recalling by meaning:

    components   portfolio code the Architect may reuse (from the indexer's graph)
    stories      what past runs built, with their outcome
    lessons      one-sentence, actionable things the platform learned from a failure
    decisions    architecture decisions and their rationale

The graph stays the source of truth; Qdrant is an index over it and is rebuilt
from it on demand (`reindex()`). When Qdrant or the embedding model is
unreachable, every call here degrades to an empty result and the graph's own
search carries on alone — recall is a quality boost, never a dependency.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from .. import telemetry
from ..config import settings
from ..llm import embed

log = logging.getLogger("poiesis.vectors")

COLLECTIONS = ("components", "stories", "lessons", "decisions")

_client: Any = None
_dimension: int | None = None
_disabled = False


def _qdrant():
    """One client. ':memory:' as the URL gives an in-process store for tests."""
    global _client
    if _client is None:
        from qdrant_client import QdrantClient
        url = settings().qdrant_url
        _client = QdrantClient(":memory:") if url == ":memory:" else QdrantClient(url=url, timeout=20)
    return _client


def use_client(client: Any) -> None:
    global _client, _disabled, _dimension
    _client, _disabled, _dimension = client, False, None


def enabled() -> bool:
    return settings().poiesis_vectors and not _disabled


def _point_id(kind: str, key: str) -> int:
    return int(hashlib.blake2b(f"{kind}:{key}".encode(), digest_size=8).hexdigest(), 16) >> 1


async def _ensure(kind: str, dimension: int) -> None:
    from qdrant_client.models import Distance, VectorParams
    c = _qdrant()
    if not c.collection_exists(kind):
        c.create_collection(kind, vectors_config=VectorParams(size=dimension, distance=Distance.COSINE))


async def upsert(kind: str, items: list[dict[str, Any]]) -> int:
    """Embed and store `items`, each {key, text, ...payload}. Returns how many landed."""
    global _disabled, _dimension
    if not enabled() or not items:
        return 0
    try:
        from qdrant_client.models import PointStruct
        async with telemetry.span("kg", f"embed {kind}", count=len(items)):
            vectors = await embed([i["text"][:4000] for i in items])
            if not vectors:
                return 0
            _dimension = len(vectors[0])
            await _ensure(kind, _dimension)
            points = [PointStruct(id=_point_id(kind, i["key"]), vector=v,
                                  payload={k: val for k, val in i.items() if k != "text"} | {"text": i["text"][:1200]})
                      for i, v in zip(items, vectors)]
            _qdrant().upsert(kind, points)
            return len(points)
    except Exception as exc:  # noqa: BLE001 — recall is optional
        log.warning("vector upsert to %s skipped: %s", kind, exc)
        _disabled = "Connection" in type(exc).__name__ or "connect" in str(exc).lower()
        return 0


async def search(kind: str, query: str, limit: int = 8,
                 must: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Nearest items to `query`, each payload plus a `score`."""
    if not enabled() or not query.strip():
        return []
    try:
        c = _qdrant()
        if not c.collection_exists(kind):
            return []
        vector = (await embed([query[:4000]]))[0]
        flt = None
        if must:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            flt = Filter(must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in must.items()])
        hits = c.query_points(kind, query=vector, limit=limit, query_filter=flt).points
        return [{**(h.payload or {}), "score": round(float(h.score), 3)} for h in hits]
    except Exception as exc:  # noqa: BLE001
        log.warning("vector search in %s skipped: %s", kind, exc)
        return []


async def counts() -> dict[str, int]:
    out: dict[str, int] = {}
    if not enabled():
        return out
    try:
        c = _qdrant()
        for kind in COLLECTIONS:
            out[kind] = c.count(kind).count if c.collection_exists(kind) else 0
    except Exception:  # noqa: BLE001
        pass
    return out


# ---- what gets indexed --------------------------------------------------------------

def component_item(row: dict[str, Any]) -> dict[str, Any]:
    text = f"{row.get('component') or row.get('name')} ({row.get('kind')}) in {row.get('project')}: " \
           f"{row.get('purpose') or ''} {row.get('signature') or ''}"
    return {"key": row["component_id"] if "component_id" in row else row["id"],
            "text": text, "component_id": row.get("component_id") or row.get("id"),
            "project": row.get("project"), "component": row.get("component") or row.get("name"),
            "kind": row.get("kind"), "path": row.get("path"), "purpose": row.get("purpose") or "",
            "signature": row.get("signature") or ""}


def story_item(run_id: str, project: str, story: dict[str, Any], outcome: str) -> dict[str, Any]:
    text = f"{story.get('title')}: {story.get('narrative')} " \
           + " ".join(story.get("acceptance_criteria") or [])
    return {"key": f"{run_id}:{story.get('id')}", "text": text, "run_id": run_id,
            "project": project, "story_id": story.get("id"), "title": story.get("title"),
            "outcome": outcome}


def lesson_item(run_id: str, story_id: str, lesson: str, applies_to: str) -> dict[str, Any]:
    return {"key": f"{run_id}:{story_id}:{hashlib.md5(lesson.encode()).hexdigest()[:8]}",
            "text": f"{applies_to}: {lesson}", "run_id": run_id, "story_id": story_id,
            "lesson": lesson, "applies_to": applies_to}


def decision_item(run_id: str, project: str, decision: dict[str, Any]) -> dict[str, Any]:
    text = f"{decision.get('title')}: {decision.get('decision')} — {decision.get('rationale')}"
    return {"key": f"{run_id}:{decision.get('title', '')[:40]}", "text": text, "run_id": run_id,
            "project": project, "title": decision.get("title"), "decision": decision.get("decision"),
            "rationale": decision.get("rationale")}


async def reindex_components(rows: list[dict[str, Any]], batch: int = 64) -> int:
    """Embed every component the graph knows. Called after the indexer runs."""
    total = 0
    for i in range(0, len(rows), batch):
        total += await upsert("components", [component_item(r) for r in rows[i:i + batch]])
    return total
