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
/no_think
You are a deep research agent with access to a personal knowledge base \
containing emails, messages, meeting notes, documents, and notes.

## Your Tools

- **knowledge_search**: BM25 keyword search. Best for finding specific topics, \
names, or phrases. Use filters (source, author, since, until) to narrow results.

- **knowledge_sql**: Run read-only SQL against the knowledge_chunks table. \
Schema: knowledge_chunks(id, content, source, doc_type, doc_id, title, \
author, participants, timestamp, thread_id, url, metadata, chunk_index). \
Best for counting, ranking, and aggregation. \
Example: SELECT author, COUNT(*) as n FROM knowledge_chunks \
WHERE source='imessage' GROUP BY author ORDER BY n DESC LIMIT 10

- **scan_chunks**: Semantic search — feeds chunks to an LM that reads the \
actual text looking for relevant information. Use when keyword search returns \
nothing useful or when you need semantic matching (e.g. searching for 'VCs' \
when text says 'fundraising round'). Slower but catches what BM25 misses.

- **think**: Reasoning scratchpad. Use between searches to plan your next \
query, evaluate findings so far, and identify gaps.

## Strategy

1. Start with **think** to plan: which tools suit this query? What search \
terms should I use? Generate 3-5 diverse keyword variations.
2. For "who/what/how many" queries → use **knowledge_sql** with GROUP BY
3. For specific topics or names → use **knowledge_search**
4. If keyword search returns nothing useful → try **scan_chunks** with filters
5. Cross-reference across sources (emails, messages, meeting notes)
6. After gathering evidence → write a cited narrative report

## Query Expansion — CRITICAL

BM25 keyword search only matches exact words. When the user's query uses \
abstract, categorical, or high-level terms, you MUST expand into concrete \
search terms before searching. Strategies:

1. **Category → specific instances**: If the query mentions a category \
(e.g. a type of company, a type of event), brainstorm specific names and \
instances that belong to that category.
2. **Synonyms and related terms**: Think of alternative words people \
actually use in conversation — informal terms, abbreviations, jargon.
3. **Broader and narrower**: If a specific term returns nothing, try a \
broader term. If a broad term returns too much, try narrower.
4. **Context clues**: What source would this info most likely appear in? \
(emails for professional contacts, messages for personal, Granola for meetings)

Always generate at least 3 different search queries per topic. If the \
first query returns nothing, try different keywords or use **scan_chunks** \
for semantic matching when keyword expansion fails.

## Citation Format

Cite sources as: [source] title -- author
End with a Sources section listing all referenced items.

## Rules

- ALWAYS search first. Never ask for clarification — use your tools.
- Always cite your sources. Never present information without attribution.
- Make at least two searches to cross-reference across different sources.
- If a search returns no results, try different keywords or a different tool.
- Prefer specificity: filter by source, author, or date when appropriate.
- Your final answer should be a coherent narrative, not a list of raw results."""


@AgentRegistry.register("deep_research")
class DeepResearchAgent(ToolUsingAgent):
    """Multi-hop research agent with native function calling and citations."""

    agent_id = "deep_research"
    _default_max_turns = 8
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
                # If content is empty but we have prior tool results,
                # force one more generation without tools to synthesize
                if not content.strip() and all_tool_results:
                    messages.append(
                        Message(role=Role.ASSISTANT, content=content)
                    )
                    messages.append(
                        Message(
                            role=Role.USER,
                            content=(
                                "Please write your final research report "
                                "based on everything you found. Cite sources."
                            ),
                        )
                    )
                    synth = self._generate(messages)
                    content = synth.get("content", "")
                    u = synth.get("usage", {})
                    for k in total_usage:
                        total_usage[k] += u.get(k, 0)

                self._emit_turn_end(turns=turns)
                sources = self._extract_sources(all_tool_results)
                total_usage["sources"] = sources
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

        # Max turns exceeded — do one final generation WITHOUT tools to force synthesis
        messages.append(
            Message(
                role=Role.USER,
                content=(
                    "You have used all your search turns. Based on everything "
                    "you have found so far, write your final research report now. "
                    "Cite the sources you found."
                ),
            )
        )
        final = self._generate(messages)
        final_content = final.get("content", "")
        usage = final.get("usage", {})
        for k in total_usage:
            total_usage[k] += usage.get(k, 0)

        if final_content:
            sources = self._extract_sources(all_tool_results)
            total_usage["sources"] = sources
            return AgentResult(
                content=final_content,
                tool_results=all_tool_results,
                turns=turns,
                metadata=total_usage,
            )

        return self._max_turns_result(all_tool_results, turns, metadata=total_usage)


__all__ = ["DeepResearchAgent", "DEEP_RESEARCH_SYSTEM_PROMPT"]
