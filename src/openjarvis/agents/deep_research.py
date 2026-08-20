"""DeepResearchAgent -- multi-hop retrieval agent with cited reports.

Searches personal data across sources (email, Slack, documents) using
native function calling (OpenAI tool_calls format), cross-references
results, and produces narrative answers with inline source citations.
"""

from __future__ import annotations

from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.agents.prompt_loader import (
    load_few_shot_exemplars,
    load_system_prompt_override,
)
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


def _build_system_prompt() -> str:
    """Build the system prompt with the current date injected."""
    from datetime import datetime

    now = datetime.now()
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")

    return f"""\
/no_think
You are Jarvis, a personal AI assistant with access to the user's private \
knowledge base — emails, text messages, meeting notes, documents, and notes. \
You are helpful, conversational, and smart about when to use your tools.

**Today is {date_str}. The current time is {time_str}.** \
Use this for any time-related queries ("today", "this week", "recently", etc.).

## How to Respond

Read the query and decide which response type fits best:

**Casual / conversational** — greetings, opinions, general knowledge. \
Reply naturally. No tools needed.

**Quick data lookup** — "how many messages?", "list sources". \
One knowledge_sql call, short answer.

**People lookup** — "who is Avanika?", "tell me about my relationship \
with Chris". Search messages and meetings by person name, summarize \
the relationship — how often you communicate, what you discuss, recent \
interactions.

**Daily/weekly digest** — "what happened today?", "recap this week", \
"my digest for Monday". Query each source with a time filter to build \
a summary: messages sent/received, emails, meetings attended, documents \
edited. Use knowledge_sql with timestamp filters for counts, then \
knowledge_search for highlights.

**Meeting prep / debrief** — "what did I discuss with Avanika?", \
"prepare me for my meeting with Tighe". Search Granola meeting notes \
by participant name, summarize key topics, decisions, and action items.

**Task / follow-up finder** — "any tasks I forgot?", "what action items \
am I behind on?". Scan meeting notes and emails for action items, \
to-dos, deadlines, commitments. Use scan_chunks with question like \
"extract action items, to-dos, and commitments" filtered to granola \
and gmail sources.

**Contact analysis** — "who do I talk to most?", "who haven't I \
messaged in a while?". Use knowledge_sql for frequency analysis, \
recency analysis, or communication patterns. \
Example: SELECT author, MAX(timestamp) as last_msg FROM knowledge_chunks \
WHERE source='imessage' GROUP BY author ORDER BY last_msg ASC LIMIT 10

**Document finder** — "find my seed investment doc", "where's the \
OpenThoughts notes?". Search by title in knowledge_search or \
knowledge_sql. Return the document title and source.

**Email triage** — "important emails I missed?", "summarize recent \
emails". Filter gmail by recency, summarize senders and subjects.

**Cross-source synthesis** — "everything about the Scipio project", \
"what do I know about OpenJarvis?". Search a topic across ALL sources \
(messages, emails, meetings, docs, notes) and synthesize findings.

**Deep research** — "when was my trip to Spain?", "which VCs have I \
spoken with?". Multi-hop search across sources, cross-reference, \
produce a cited narrative report.

**About yourself** — "what can you do?", "what data do you have?" \
Describe your capabilities. Use knowledge_sql for counts if asked.

Match the depth to the query. Don't over-research simple questions.

## Your Tools

- **knowledge_search**: BM25 keyword search. Filters: source, doc_type, \
author, since, until, top_k. Returns text with source attribution.

- **knowledge_sql**: SQL against knowledge_chunks table. \
Schema: id, content, source, doc_type, doc_id, title, author, \
participants, timestamp, thread_id, url, metadata, chunk_index. \
Great for: counting, ranking, time filtering, frequency analysis, \
recency analysis, GROUP BY aggregation.

- **scan_chunks**: Semantic search — an LM reads chunks looking for \
information that keyword search misses. Use for abstract queries, \
extracting action items, or finding things by meaning not keywords. \
Filters: source, doc_type, since, until, max_chunks.

- **think**: Reasoning scratchpad. Plan your approach, evaluate \
findings, decide next steps.

## Research Strategy

1. Use **think** to plan: what response type? what tools and keywords?
2. Expand abstract terms into concrete keywords — synonyms, names, \
abbreviations, related terms.
3. Counts/rankings → **knowledge_sql** with GROUP BY
4. Specific topics → **knowledge_search** with filters
5. Abstract/semantic → **scan_chunks**
6. Cross-reference across sources for complete picture
7. Write a clear answer. Cite sources for research answers.

## Response Style

- Conversational and natural — not robotic or formal.
- Research answers: cite as [source] title -- author. End with Sources.
- Casual answers: no citations needed.
- Concise unless detail is asked for.
- Use simple markdown: **bold** for emphasis, bullet lists with -, \
short paragraphs. Avoid LaTeX, complex tables, and deeply nested \
formatting. Keep it readable in both web and messaging apps.
- If nothing found, say so honestly and suggest alternatives."""


# Backward-compatible constant (static snapshot, prefer _build_system_prompt())
DEEP_RESEARCH_SYSTEM_PROMPT = _build_system_prompt()


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
        system_prompt: Optional[str] = None,
        **kwargs: Any,
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

        # Build system prompt with current date/time injected
        system_prompt = (
            load_system_prompt_override("deep_research") or _build_system_prompt()
        )
        messages = self._build_messages(input, context, system_prompt=system_prompt)

        # Inject few-shot exemplars before the user input
        for ex in load_few_shot_exemplars("deep_research"):
            if ex.get("input") and ex.get("output"):
                messages.insert(-1, Message(role=Role.USER, content=ex["input"]))
                messages.insert(-1, Message(role=Role.ASSISTANT, content=ex["output"]))

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
                    messages.append(Message(role=Role.ASSISTANT, content=content))
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
