"""native_react must not finalize without web_search on news queries."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents.native_react import NativeReActAgent
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


class _WebStub(BaseTool):
    tool_id = "web_search"
    calls = 0

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description="search",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )

    def execute(self, **params) -> ToolResult:
        _WebStub.calls += 1
        return ToolResult(
            tool_name="web_search",
            content="**Headline** — snippet text",
            success=True,
        )


def test_plain_answer_rejected_until_web_search() -> None:
    _WebStub.calls = 0
    engine = MagicMock()
    engine.generate.side_effect = [
        {
            "content": "Here are world news: BBC said something.",
            "usage": {},
        },
        {
            "content": (
                "Thought: search\n"
                'Action: web_search\n'
                'Action Input: {"query": "world news"}'
            ),
            "usage": {},
        },
        {
            "content": "Thought: done\nFinal Answer: From search: Headline snippet.",
            "usage": {},
        },
    ]
    agent = NativeReActAgent(engine, "m", tools=[_WebStub()], max_turns=5)
    result = agent.run("znajdź wiadomości ze świata")
    assert _WebStub.calls >= 1
    assert "Headline" in result.content or "snippet" in result.content.lower()
