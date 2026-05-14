"""Agentic research loop over the hybrid-search tool.

A small, self-contained planner-executor loop:

* the planner is a local Ollama chat model (default ``gemma4:31b``),
* the only tool it can call is :meth:`HybridSearch.search`,
* it gets up to ``max_iterations`` tool calls,
* tool results are trimmed before re-entering the context window, and
* the final reply must cite specific hits.

The loop is deliberately decoupled from the rest of the agent scaffolding
(`ToolUsingAgent`, `EventBus`, `AgentContext`, etc.) so the surface stays
small. Anything that wants tracing or registry integration can wrap it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from openjarvis.connectors.hybrid_search import HybridSearch, SearchHit
from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.engine._base import InferenceEngine

logger = logging.getLogger(__name__)


DEFAULT_PLANNER_MODEL = "gemma4:31b"


SEARCH_TOOL_SPEC: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search",
        "description": (
            "Hybrid search over the user's personal knowledge corpus (emails, "
            "notes, calendar events, attachments). Combines BM25 lexical match "
            "with dense embedding similarity, ranked by reciprocal rank fusion. "
            "Use structured filters (person, time_range, sources) whenever the "
            "user names a specific person or time window. Each call returns up "
            "to 'limit' results with content snippets and thread context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Natural-language query. Use the topic the user is asking "
                        "about. Can be empty when filtering purely by person or "
                        "time (e.g. 'list all mail from Kelly in May')."
                    ),
                },
                "person": {
                    "type": "string",
                    "description": (
                        "Filter to messages involving this person. Matches a "
                        "substring of the name or email address — 'Kelly' or "
                        "'@tldrnewsletter.com' both work."
                    ),
                },
                "time_range": {
                    "type": "object",
                    "description": "ISO 8601 datetime range. Either bound may be omitted.",
                    "properties": {
                        "start": {"type": "string", "description": "ISO 8601 start"},
                        "end": {"type": "string", "description": "ISO 8601 end"},
                    },
                },
                "sources": {
                    "type": "array",
                    "description": "Restrict to these connectors (e.g. ['gmail']).",
                    "items": {"type": "string"},
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20, cap 20).",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    },
}


SYSTEM_PROMPT = """You are a research assistant with access to the user's personal knowledge corpus (their email, notes, calendar). You answer questions by calling a single tool:

    search(query, person=None, time_range=None, sources=None, limit=20)

Strategy:
  1. If the user names a person, ALWAYS pass `person=` rather than relying on lexical match. Hybrid search will fuzzy-match name or address fragments.
  2. When the user mentions ANY time window — "this past week", "recently", "last month", "past few days", "yesterday" — you MUST translate it to a `time_range` parameter. Today is {today}.
  3. The `time_range` argument is a JSON object: `{{"start": "<ISO 8601>", "end": "<ISO 8601>"}}`. Either bound may be omitted, but pass at least one whenever the user gave you a temporal cue.
  4. If the first structured search returns nothing useful, broaden with a semantic query and drop filters one at a time.
  5. Call search up to 5 times. Once you have enough, write a synthesis.

Synthesis rules:
  - Cite specific results by their numeric id (e.g. "[hit-3]").
  - Quote sender / date / subject when relevant — the user wants attribution.
  - If the search returned nothing relevant, say so plainly. Do not invent results.
  - Only state facts that appear in the retrieved search results. Never supplement with your own knowledge or training data. If you are unsure whether a fact came from the search results, do not include it.

Today's date is {today}.
"""


# ---------------------------------------------------------------------------
# Tool-result shaping
# ---------------------------------------------------------------------------


def _trim_thread_context(ctx: List[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
    """Keep the first ``cap`` entries; mark elision when trimming."""
    if len(ctx) <= cap:
        return ctx
    trimmed = list(ctx[:cap])
    trimmed.append({"snippet": f"… {len(ctx) - cap} more chunks in thread …"})
    return trimmed


def shape_results_for_model(
    hits: List[SearchHit],
    *,
    detailed_top: int = 5,
    thread_ctx_per_hit: int = 3,
    total_cap: int = 20,
) -> Dict[str, Any]:
    """Compact a hit list into a JSON payload the planner can chew through.

    The first ``detailed_top`` rows keep their content snippet and trimmed
    thread context; the remainder are summarised to title + sender + date so
    the planner still sees the breadth of what's available without blowing the
    context window. Each hit gets a stable ``id`` so the synthesis can cite it.
    """
    out_hits: List[Dict[str, Any]] = []
    visible = hits[:total_cap]
    for i, h in enumerate(visible):
        sender = h.participants[0] if h.participants else ""
        base = {
            "id": f"hit-{i + 1}",
            "title": h.title,
            "sender": sender,
            "timestamp": h.timestamp,
            "source": h.source,
            "score": round(h.score, 4),
        }
        if i < detailed_top:
            base["snippet"] = h.content_snippet
            if h.thread_context:
                base["thread"] = _trim_thread_context(h.thread_context, thread_ctx_per_hit)
        out_hits.append(base)
    return {
        "num_results": len(hits),
        "shown": len(visible),
        "truncated": len(hits) > total_cap,
        "hits": out_hits,
    }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class ToolInvocation:
    """One call to ``search`` together with what the planner asked for and got."""

    arguments: Dict[str, Any]
    num_results: int
    top_titles: List[str]
    raw_hits: List[SearchHit] = field(default_factory=list)


@dataclass
class ResearchResult:
    answer: str
    iterations: int
    tool_calls: List[ToolInvocation]
    usage: Dict[str, int] = field(default_factory=dict)


class ResearchAgent:
    """Planner + executor loop over a single hybrid-search tool.

    Parameters
    ----------
    engine:
        An ``InferenceEngine`` that supports OpenAI-style ``tools`` in
        ``generate`` (Ollama with a tool-capable model).
    search:
        The HybridSearch instance the planner can call.
    model:
        Planner model tag (default ``gemma4:31b``).
    max_iterations:
        Hard ceiling on tool calls before the loop is forced into synthesis.
    temperature, max_tokens, num_ctx:
        Generation parameters passed through to ``engine.generate``.
    """

    def __init__(
        self,
        engine: InferenceEngine,
        search: HybridSearch,
        *,
        model: str = DEFAULT_PLANNER_MODEL,
        max_iterations: int = 5,
        temperature: float = 0.3,
        max_tokens: int = 1500,
        num_ctx: int = 16384,
    ) -> None:
        self._engine = engine
        self._search = search
        self._model = model
        self._max_iterations = int(max_iterations)
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)
        self._num_ctx = int(num_ctx)

    # ------------------------------------------------------------------
    # Argument parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time_range(raw: Any):
        if not raw or not isinstance(raw, dict):
            return None
        def _maybe(v):
            if not v:
                return None
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except ValueError:
                return None
        start = _maybe(raw.get("start"))
        end = _maybe(raw.get("end"))
        if start is None and end is None:
            return None
        return (start, end)

    def _execute_search(self, args: Dict[str, Any]) -> ToolInvocation:
        query = str(args.get("query", "") or "")
        person = args.get("person") or None
        time_range = self._parse_time_range(args.get("time_range"))
        sources = args.get("sources") or None
        if sources and not isinstance(sources, list):
            sources = [str(sources)]
        limit = int(args.get("limit", 20) or 20)
        limit = max(1, min(limit, 20))

        hits = self._search.search(
            query,
            person=person,
            time_range=time_range,
            sources=sources,
            limit=limit,
        )
        titles = [h.title or (h.content_snippet[:60] + "…") for h in hits[:5]]
        return ToolInvocation(
            arguments={
                "query": query,
                "person": person,
                "time_range": (
                    {"start": time_range[0].isoformat() if time_range and time_range[0] else None,
                     "end": time_range[1].isoformat() if time_range and time_range[1] else None}
                    if time_range else None
                ),
                "sources": sources,
                "limit": limit,
            },
            num_results=len(hits),
            top_titles=titles,
            raw_hits=hits,
        )

    # ------------------------------------------------------------------
    # Loop
    # ------------------------------------------------------------------

    def run(self, query: str) -> ResearchResult:
        """Run the loop end-to-end and return the synthesis plus a trace."""
        sys_msg = Message(
            role=Role.SYSTEM,
            content=SYSTEM_PROMPT.format(today=datetime.now().isoformat(timespec="minutes")),
        )
        messages: List[Message] = [sys_msg, Message(role=Role.USER, content=query)]

        invocations: List[ToolInvocation] = []
        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        iterations = 0
        for _ in range(self._max_iterations + 1):
            iterations += 1
            tools_arg = [SEARCH_TOOL_SPEC] if len(invocations) < self._max_iterations else None
            result = self._engine.generate(
                messages,
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                num_ctx=self._num_ctx,
                tools=tools_arg,
            )
            for k in total_usage:
                total_usage[k] += int(result.get("usage", {}).get(k, 0))

            content = result.get("content", "") or ""
            tool_calls_raw = result.get("tool_calls", []) or []

            if not tool_calls_raw:
                if content.strip():
                    return ResearchResult(
                        answer=content.strip(),
                        iterations=iterations,
                        tool_calls=invocations,
                        usage=total_usage,
                    )
                # Empty content with no tool call — push a synthesis prod
                if invocations:
                    messages.append(Message(role=Role.ASSISTANT, content=content))
                    messages.append(
                        Message(
                            role=Role.USER,
                            content=(
                                "Write your final answer now based on the search "
                                "results above. Cite specific hits by their id."
                            ),
                        )
                    )
                    continue
                return ResearchResult(
                    answer="(model returned no content and no tool calls)",
                    iterations=iterations,
                    tool_calls=invocations,
                    usage=total_usage,
                )

            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=content,
                tool_calls=[
                    ToolCall(
                        id=tc.get("id", f"call_{i}"),
                        name=tc.get("name", "search"),
                        arguments=tc.get("arguments", "{}") or "{}",
                    )
                    for i, tc in enumerate(tool_calls_raw)
                ],
            )
            messages.append(assistant_msg)

            for tc in tool_calls_raw:
                name = tc.get("name", "")
                raw_args = tc.get("arguments", "{}") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except json.JSONDecodeError:
                    args = {}

                if name != "search":
                    tool_output = json.dumps(
                        {"error": f"unknown tool {name!r}; only 'search' is available"}
                    )
                else:
                    inv = self._execute_search(args)
                    invocations.append(inv)
                    tool_output = json.dumps(
                        shape_results_for_model(inv.raw_hits), ensure_ascii=False
                    )

                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=tool_output,
                        tool_call_id=tc.get("id", ""),
                        name=name,
                    )
                )

            if len(invocations) >= self._max_iterations:
                messages.append(
                    Message(
                        role=Role.USER,
                        content=(
                            "You have used your tool-call budget. Write the final "
                            "synthesis now using only the search results above. "
                            "Cite specific hits by id."
                        ),
                    )
                )

        # Loop fell through (shouldn't happen unless max_iterations is 0).
        return ResearchResult(
            answer="(loop exhausted without final synthesis)",
            iterations=iterations,
            tool_calls=invocations,
            usage=total_usage,
        )


__all__ = [
    "ResearchAgent",
    "ResearchResult",
    "ToolInvocation",
    "SEARCH_TOOL_SPEC",
    "SYSTEM_PROMPT",
    "DEFAULT_PLANNER_MODEL",
    "shape_results_for_model",
]
