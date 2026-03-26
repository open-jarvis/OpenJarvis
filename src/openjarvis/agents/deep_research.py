"""DeepResearchAgent -- multi-hop retrieval agent with cited reports.

Searches personal data across sources (email, Slack, documents) using
native function calling (OpenAI tool_calls format), cross-references
results, and produces narrative answers with inline source citations.
"""

from __future__ import annotations

from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import Message, Role, ToolCall, ToolResult
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool


def _tc_name(tc: dict) -> str:
    """Extract tool call name from OpenAI or flat format."""
    if "function" in tc:
        return tc["function"]["name"]
    return tc["name"]


def _tc_args(tc: dict) -> str:
    """Extract tool call arguments from OpenAI or flat format."""
    if "function" in tc:
        return tc["function"]["arguments"]
    return tc["arguments"]

DEEP_RESEARCH_SYSTEM_PROMPT = """\
You are a deep research agent. Your job is to search the user's personal \
knowledge base thoroughly and produce a well-cited narrative report.

## Instructions

1. Use the **knowledge_search** tool to search ingested personal data \
(emails, Slack messages, documents, notes). Make multiple searches with \
different queries to cross-reference information across sources.
2. Use the **think** tool to reason between searches -- plan your next \
query, evaluate what you have found so far, and identify gaps.
3. After gathering enough evidence, produce a final narrative answer \
with inline citations in the format: [source] title -- author
4. Include a **Sources** section at the end listing all referenced sources.

## Rules

- Always cite your sources. Never present information without attribution.
- Make at least two searches to cross-reference across different sources.
- If a search returns no results, try rephrasing the query.
- Prefer specificity: filter by source, author, or date when appropriate.
- Your final answer should be a coherent narrative, not a list of raw results."""


@AgentRegistry.register("deep_research")
class DeepResearchAgent(ToolUsingAgent):
    """Multi-hop research agent with native function calling and citations."""

    agent_id = "deep_research"
    _default_max_turns = 5
    _default_temperature = 0.3
    _default_max_tokens = 4096

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[BaseTool]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        interactive: bool = False,
        confirm_callback=None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            interactive=interactive,
            confirm_callback=confirm_callback,
        )

    @staticmethod
    def _extract_sources(tool_results: List[ToolResult]) -> List[str]:
        """Collect unique source references from tool results.

        Parses the formatted output of ``KnowledgeSearchTool`` to pull out
        ``[source] title -- author`` style references.
        """
        sources: list[str] = []
        seen: set[str] = set()
        for tr in tool_results:
            if tr.tool_name != "knowledge_search" or not tr.success:
                continue
            for line in tr.content.splitlines():
                if line.startswith("**Result "):
                    # Strip the **Result N:** prefix
                    ref = line.split(":", 1)[1].strip() if ":" in line else line
                    if ref and ref not in seen:
                        seen.add(ref)
                        sources.append(ref)
        return sources

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        # Build system prompt and initial messages
        messages = self._build_messages(
            input, context, system_prompt=DEEP_RESEARCH_SYSTEM_PROMPT
        )

        # Prepare OpenAI-format tool definitions for native function calling
        tools_openai = [t.to_openai_function() for t in self._tools]

        all_tool_results: list[ToolResult] = []
        turns = 0
        total_usage: dict[str, int] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

        for _turn in range(self._max_turns):
            turns += 1

            if self._loop_guard:
                messages = self._loop_guard.compress_context(messages)

            # Pass tools to engine for native function calling
            result = self._generate(messages, tools=tools_openai)

            # Accumulate token usage
            usage = result.get("usage", {})
            for k in total_usage:
                total_usage[k] += usage.get(k, 0)

            content = result.get("content", "")
            tool_calls_raw = result.get("tool_calls", [])

            # No tool calls -- this is the final answer
            if not tool_calls_raw:
                self._emit_turn_end(turns=turns)
                return AgentResult(
                    content=content,
                    tool_results=all_tool_results,
                    turns=turns,
                    metadata=total_usage,
                )

            # Append assistant message with tool_calls metadata
            assistant_tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=_tc_name(tc),
                    arguments=_tc_args(tc),
                )
                for tc in tool_calls_raw
            ]
            messages.append(
                Message(
                    role=Role.ASSISTANT,
                    content=content,
                    tool_calls=assistant_tool_calls,
                )
            )

            # Execute each tool call and append results
            for tc_raw in tool_calls_raw:
                tc = ToolCall(
                    id=tc_raw["id"],
                    name=_tc_name(tc_raw),
                    arguments=_tc_args(tc_raw),
                )

                # Loop guard check before execution
                if self._loop_guard:
                    verdict = self._loop_guard.check_call(tc.name, tc.arguments)
                    if verdict.blocked:
                        tool_result = ToolResult(
                            tool_name=tc.name,
                            content=f"Loop guard: {verdict.reason}",
                            success=False,
                        )
                        all_tool_results.append(tool_result)
                        messages.append(
                            Message(
                                role=Role.TOOL,
                                content=tool_result.content,
                                tool_call_id=tc.id,
                                name=tc.name,
                            )
                        )
                        continue

                tool_result = self._executor.execute(tc)
                all_tool_results.append(tool_result)

                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_result.content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )

        # Max turns exceeded
        return self._max_turns_result(all_tool_results, turns, metadata=total_usage)


__all__ = ["DeepResearchAgent", "DEEP_RESEARCH_SYSTEM_PROMPT"]
