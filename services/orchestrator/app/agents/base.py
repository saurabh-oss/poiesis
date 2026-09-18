"""Agent contract.

An agent is a named role with a system prompt, a model role, and a typed output.
Keeping this thin means the value stream is defined by the graph, not buried in
agent internals — which is what makes the pipeline auditable.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..llm import complete, complete_json

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Agent:
    name: str
    role: str            # reasoning | coding | fast
    prompt_file: str
    temperature: float = 0.2

    @property
    def system(self) -> str:
        return (PROMPT_DIR / self.prompt_file).read_text(encoding="utf-8")

    async def json(self, user: str, *, max_tokens: int = 6000) -> Any:
        return await complete_json(
            role=self.role, system=self.system, user=user,
            temperature=self.temperature, max_tokens=max_tokens,
        )

    async def text(self, user: str, *, max_tokens: int = 4000) -> str:
        return await complete(
            role=self.role, system=self.system, user=user,
            temperature=self.temperature, max_tokens=max_tokens,
        )


ANALYST = Agent("Analyst", "reasoning", "analyst.md", 0.3)
PRODUCT_OWNER = Agent("Product Owner", "reasoning", "product_owner.md", 0.3)
ARCHITECT = Agent("Architect", "reasoning", "architect.md", 0.2)
PLANNER = Agent("Planner", "fast", "planner.md", 0.1)
DEVELOPER = Agent("Developer", "coding", "developer.md", 0.1)
TESTER = Agent("Tester", "coding", "tester.md", 0.1)
REVIEWER = Agent("Reviewer", "reasoning", "reviewer.md", 0.1)
RELEASE = Agent("Release Manager", "fast", "release.md", 0.1)
