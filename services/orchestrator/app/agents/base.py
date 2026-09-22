"""Agent contract.

An agent is a named role with a system prompt, a model role, a typed output and,
on the local profile, the JSON schema that output is constrained to. Keeping
this thin means the value stream is defined by the graph, not buried in agent
internals — which is what makes the pipeline auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import telemetry
from ..llm import complete, complete_json
from . import schemas

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Agent:
    name: str
    role: str            # reasoning | coding | fast
    prompt_file: str
    temperature: float = 0.2
    schema: dict[str, Any] | None = None   # the default reply shape; a call may override it
    key: str = ""        # how events and traces name this agent

    @property
    def system(self) -> str:
        return (PROMPT_DIR / self.prompt_file).read_text(encoding="utf-8")

    async def json(self, user: str, *, max_tokens: int = 6000,
                   schema: dict[str, Any] | None = None) -> Any:
        token = telemetry.current_agent.set(self.key or self.name.lower().replace(" ", "_"))
        try:
            return await complete_json(
                role=self.role, system=self.system, user=user,
                temperature=self.temperature, max_tokens=max_tokens,
                schema=schema or self.schema,
            )
        finally:
            telemetry.current_agent.reset(token)

    async def text(self, user: str, *, max_tokens: int = 4000) -> str:
        token = telemetry.current_agent.set(self.key or self.name.lower().replace(" ", "_"))
        try:
            return await complete(
                role=self.role, system=self.system, user=user,
                temperature=self.temperature, max_tokens=max_tokens,
            )
        finally:
            telemetry.current_agent.reset(token)


ANALYST = Agent("Analyst", "reasoning", "analyst.md", 0.3, schemas.ANALYSIS, "analyst")
# The Product Owner writes two artifacts; each call names its schema.
PRODUCT_OWNER = Agent("Product Owner", "reasoning", "product_owner.md", 0.3, None, "product_owner")
ARCHITECT = Agent("Architect", "reasoning", "architect.md", 0.2, schemas.ARCHITECTURE, "architect")
PLANNER = Agent("Planner", "fast", "planner.md", 0.1, schemas.SPRINT, "planner")
DEVELOPER = Agent("Developer", "coding", "developer.md", 0.1, schemas.IMPLEMENTATION, "developer")
TESTER = Agent("Tester", "coding", "tester.md", 0.1, schemas.TESTS, "tester")
REVIEWER = Agent("Reviewer", "reasoning", "reviewer.md", 0.1, schemas.REVIEW, "reviewer")
RELEASE = Agent("Release Manager", "fast", "release.md", 0.1, schemas.RELEASE_NOTES, "release")
