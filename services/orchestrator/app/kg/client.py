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
CREATE CONSTRAINT lesson_id IF NOT EXISTS
  FOR (l:Lesson) REQUIRE l.id IS UNIQUE;
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


    # ---- what the platform learns, and how a run is remembered --------------

    async def all_components(self) -> list[dict[str, Any]]:
        """Every indexed component, for the vector index to embed."""
        return await self.run(
            """
            MATCH (p:Project)-[:CONTAINS]->(c:Component)
            RETURN p.name AS project, c.id AS component_id, c.name AS component,
                   c.kind AS kind, c.path AS path, c.purpose AS purpose, c.signature AS signature
            """
        )

    async def record_outcome(self, run_id: str, project: str, outcome: dict[str, Any]) -> None:
        """Score, verdict and what shipped, on the run's Project node."""
        await self.run(
            """
            MERGE (p:Project {name: $project})
            SET p.run_id = $run_id, p.score = $score, p.verdict = $verdict,
                p.released = $released, p.stories_green = $green, p.stories_total = $total,
                p.finished_at = timestamp()
            """,
            project=project, run_id=run_id, score=outcome.get("score"),
            verdict=outcome.get("verdict", ""), released=bool(outcome.get("released")),
            green=int(outcome.get("green") or 0), total=int(outcome.get("total") or 0),
        )

    async def record_story_outcome(self, run_id: str, story_id: str, status: str,
                                   repairs: int) -> None:
        await self.run(
            """
            MERGE (s:Story {id: $sid}) SET s.status = $status, s.repairs = $repairs
            """,
            sid=f"{run_id}:{story_id}", status=status, repairs=int(repairs or 0),
        )

    async def record_lesson(self, run_id: str, story_id: str, lesson: str,
                            applies_to: str, project: str) -> str:
        lid = f"{run_id}:{story_id}:{abs(hash(lesson)) % 10**8}"
        await self.run(
            """
            MERGE (l:Lesson {id: $id})
            SET l.text = $text, l.applies_to = $applies_to, l.run_id = $run_id,
                l.story_id = $story_id, l.created_at = timestamp()
            WITH l
            MERGE (s:Story {id: $sid}) MERGE (l)-[:LEARNED_FROM]->(s)
            WITH l
            MERGE (p:Project {name: $project}) MERGE (l)-[:LEARNED_IN]->(p)
            """,
            id=lid, text=lesson, applies_to=applies_to, run_id=run_id, story_id=story_id,
            sid=f"{run_id}:{story_id}", project=project,
        )
        return lid

    async def lessons(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.run(
            """
            MATCH (l:Lesson)
            OPTIONAL MATCH (l)-[:LEARNED_IN]->(p:Project)
            RETURN l.id AS id, l.text AS lesson, l.applies_to AS applies_to,
                   l.run_id AS run_id, l.story_id AS story_id, p.name AS project,
                   l.created_at AS created_at
            ORDER BY l.created_at DESC LIMIT $limit
            """,
            limit=limit,
        )

    async def run_lineage(self, run_id: str) -> list[dict[str, Any]]:
        """Everything a run put in the graph, as edges the control room can draw."""
        return await self.run(
            """
            MATCH (p:Project {run_id: $run_id})
            OPTIONAL MATCH (p)-[r]->(x)
            WITH p, collect({rel: type(r), to_type: labels(x)[0],
                             to_name: coalesce(x.name, x.title, x.id)}) AS out
            OPTIONAL MATCH (l:Lesson)-[:LEARNED_IN]->(p)
            RETURN p.name AS project, p.score AS score, p.verdict AS verdict,
                   p.released AS released, out AS edges,
                   collect(DISTINCT l.text) AS lessons
            """,
            run_id=run_id,
        )

    async def stats(self) -> dict[str, int]:
        rows = await self.run(
            """
            CALL { MATCH (p:Project) RETURN count(p) AS projects }
            CALL { MATCH (c:Component) RETURN count(c) AS components }
            CALL { MATCH (c:Capability) RETURN count(c) AS capabilities }
            CALL { MATCH (t:Technology) RETURN count(t) AS technologies }
            CALL { MATCH (d:Decision) RETURN count(d) AS decisions }
            CALL { MATCH (s:Story) RETURN count(s) AS stories }
            CALL { MATCH (l:Lesson) RETURN count(l) AS lessons }
            CALL { MATCH ()-[r:REUSES]->() RETURN count(r) AS reuse_edges }
            RETURN projects, components, capabilities, technologies, decisions, stories,
                   lessons, reuse_edges
            """
        )
        return {k: int(v or 0) for k, v in (rows[0] if rows else {}).items()}


_kg: KnowledgeGraph | None = None


def kg() -> KnowledgeGraph:
    global _kg
    if _kg is None:
        _kg = KnowledgeGraph()
    return _kg
