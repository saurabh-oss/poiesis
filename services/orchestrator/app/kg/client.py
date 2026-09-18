"""Portfolio Knowledge Graph.

This is the part that makes Poiesis different from a code generator. Before an
architect agent designs anything, it asks: does this capability already exist
somewhere in the portfolio, and what did we decide last time?
"""
from __future__ import annotations

import asyncio
from typing import Any

from neo4j import GraphDatabase

from ..config import settings

SCHEMA = """
CREATE CONSTRAINT project_name IF NOT EXISTS
  FOR (p:Project) REQUIRE p.name IS UNIQUE;
CREATE CONSTRAINT component_id IF NOT EXISTS
  FOR (c:Component) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT capability_name IF NOT EXISTS
  FOR (c:Capability) REQUIRE c.name IS UNIQUE;
CREATE CONSTRAINT decision_id IF NOT EXISTS
  FOR (d:Decision) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT tech_name IF NOT EXISTS
  FOR (t:Technology) REQUIRE t.name IS UNIQUE;
CREATE CONSTRAINT story_id IF NOT EXISTS
  FOR (s:Story) REQUIRE s.id IS UNIQUE;
CREATE FULLTEXT INDEX componentSearch IF NOT EXISTS
  FOR (c:Component) ON EACH [c.name, c.purpose, c.signature];
CREATE FULLTEXT INDEX capabilitySearch IF NOT EXISTS
  FOR (c:Capability) ON EACH [c.name, c.description];
"""


class KnowledgeGraph:
    def __init__(self) -> None:
        s = settings()
        self._driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))

    def close(self) -> None:
        self._driver.close()

    # ---- plumbing ---------------------------------------------------------
    def _run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        with self._driver.session() as sess:
            return [r.data() for r in sess.run(cypher, **params)]

    async def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._run, cypher, **params)

    async def bootstrap(self) -> None:
        for stmt in [s.strip() for s in SCHEMA.split(";") if s.strip()]:
            await self.run(stmt)

    # ---- reads used by the agents ----------------------------------------
    async def find_reusable(self, terms: list[str], limit: int = 12) -> list[dict[str, Any]]:
        """Full-text search across indexed components, ranked, with owning project."""
        query = terms if isinstance(terms, str) else " OR ".join(
            f'"{t}"' if " " in t else t for t in terms if t.strip()
        )
        if not query.strip():
            return []
        return await self.run(
            """
            CALL db.index.fulltext.queryNodes('componentSearch', $q) YIELD node, score
            MATCH (p:Project)-[:CONTAINS]->(node)
            OPTIONAL MATCH (node)-[:IMPLEMENTS]->(cap:Capability)
            RETURN p.name AS project, p.repo_url AS repo, node.id AS component_id,
                   node.name AS component, node.kind AS kind, node.path AS path,
                   node.purpose AS purpose, node.signature AS signature,
                   collect(DISTINCT cap.name) AS capabilities, score
            ORDER BY score DESC LIMIT $limit
            """,
            q=query,
            limit=limit,
        )

    async def capability_map(self) -> list[dict[str, Any]]:
        return await self.run(
            """
            MATCH (p:Project)-[:PROVIDES]->(c:Capability)
            RETURN c.name AS capability, collect(p.name) AS projects
            ORDER BY capability
            """
        )

    async def prior_decisions(self, terms: list[str], limit: int = 8) -> list[dict[str, Any]]:
        return await self.run(
            """
            MATCH (d:Decision)
            WHERE any(t IN $terms WHERE toLower(d.title) CONTAINS toLower(t)
                                     OR toLower(d.context) CONTAINS toLower(t))
            OPTIONAL MATCH (d)-[:MADE_IN]->(p:Project)
            RETURN d.id AS id, d.title AS title, d.decision AS decision,
                   d.rationale AS rationale, d.status AS status, p.name AS project
            ORDER BY d.created_at DESC LIMIT $limit
            """,
            terms=terms,
            limit=limit,
        )

    async def house_stack(self) -> list[dict[str, Any]]:
        """What the portfolio already standardises on. Keeps new builds consistent."""
        return await self.run(
            """
            MATCH (p:Project)-[:USES]->(t:Technology)
            RETURN t.name AS technology, t.category AS category,
                   count(DISTINCT p) AS projects
            ORDER BY projects DESC, technology LIMIT 40
            """
        )

    # ---- writes: the loop that makes each run smarter than the last -------
    async def record_run(self, run_id: str, title: str, vision: dict[str, Any]) -> None:
        await self.run(
            """
            MERGE (p:Project {name: $name})
            SET p.repo_url = $repo, p.kind = 'poiesis-run', p.summary = $summary,
                p.run_id = $run_id
            """,
            name=title,
            repo=f"workspace://{run_id}",
            summary=vision.get("problem_statement", "")[:2000],
            run_id=run_id,
        )

    async def record_decision(self, run_id: str, project: str, decision: dict[str, Any]) -> None:
        await self.run(
            """
            MERGE (d:Decision {id: $id})
            SET d.title = $title, d.context = $context, d.decision = $decision,
                d.rationale = $rationale, d.status = 'accepted',
                d.created_at = timestamp(), d.run_id = $run_id
            WITH d
            MERGE (p:Project {name: $project})
            MERGE (d)-[:MADE_IN]->(p)
            """,
            id=f"{run_id}-{decision.get('title','adr')[:40]}",
            title=decision.get("title", ""),
            context=decision.get("context", ""),
            decision=decision.get("decision", ""),
            rationale=decision.get("rationale", ""),
            project=project,
            run_id=run_id,
        )

    async def record_reuse(self, project: str, component_ids: list[str]) -> None:
        await self.run(
            """
            MATCH (p:Project {name: $project})
            UNWIND $ids AS cid
            MATCH (c:Component {id: cid})
            MERGE (p)-[r:REUSES]->(c)
            SET r.at = timestamp()
            """,
            project=project,
            ids=component_ids,
        )


_kg: KnowledgeGraph | None = None


def kg() -> KnowledgeGraph:
    global _kg
    if _kg is None:
        _kg = KnowledgeGraph()
    return _kg
