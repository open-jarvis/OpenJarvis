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
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from openjarvis.connectors.hybrid_search import HybridSearch, SearchHit
from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.engine._base import InferenceEngine

logger = logging.getLogger(__name__)


DEFAULT_PLANNER_MODEL = "gemma4:31b"


CLARIFY_TOOL_SPEC: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "clarify",
        "description": (
            "Ask the user a clarifying question and wait for their answer. "
            "Only use AFTER at least one search has been attempted. Use when "
            "search results are ambiguous (e.g. three different people share "
            "a first name), search returned zero results and the query likely "
            "needs reframing, or the scope is too broad to synthesize "
            "meaningfully. Never use clarify before searching."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The clarifying question to ask the user. Be specific "
                        "about what you need to know to make progress."
                    ),
                },
            },
            "required": ["question"],
        },
    },
}


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


SYSTEM_PROMPT = """You are a research assistant with access to the user's personal knowledge corpus (their email, notes, calendar). You answer questions by calling two tools:

    search(query, person=None, time_range=None, sources=None, limit=20)
    clarify(question)

Strategy:
  1. If the user names a person, ALWAYS pass `person=` rather than relying on lexical match. Hybrid search will fuzzy-match name or address fragments.
  2. When the user mentions ANY time window — "this past week", "recently", "last month", "past few days", "yesterday" — you MUST translate it to a `time_range` parameter. Today is {today}.
  3. The `time_range` argument is a JSON object: `{{"start": "<ISO 8601>", "end": "<ISO 8601>"}}`. Either bound may be omitted, but pass at least one whenever the user gave you a temporal cue.
  4. If the first structured search returns nothing useful, broaden with a semantic query and drop filters one at a time.
  5. You have a clarify tool. Only use it AFTER at least one search attempt. Use it when: you found multiple ambiguous matches (e.g. 3 different people named John), search returned zero results and the query might need reframing, or the scope is too broad to synthesize meaningfully. Never use clarify before searching — always try first.
  6. After receiving a clarify response, use the information to construct a precise search with the correct person, time_range, and query parameters. Never send an empty query or a query with no parameters — extract every concrete signal from the user's reply (names, dates, topics) and put it on the call.
  7. Tool calls — search AND clarify — share a budget of 5 total. Spend wisely.

Synthesis rules:
  - Cite sources as individual numbers in square brackets. Always separate — write [4] [7] [20], never [4, 7, 20]. Never format citations as markdown links. Just the number in brackets: [1]. The `ref` field on each hit is the citation number.
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
    context window. Each hit gets a 1-indexed numeric ``ref`` so the synthesis
    can cite it as ``[N]``.
    """
    out_hits: List[Dict[str, Any]] = []
    visible = hits[:total_cap]
    for i, h in enumerate(visible):
        sender = h.participants[0] if h.participants else ""
        base = {
            "ref": i + 1,
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


def _hit_date(timestamp: str) -> str:
    """Pull a ``YYYY-MM-DD`` date out of a SearchHit timestamp (best effort)."""
    if not timestamp:
        return ""
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, AttributeError):
        return str(timestamp)[:10]


def _bare_doc_id(source: str, document_id: str) -> str:
    """Strip the connector prefix from a stored ``doc_id``.

    Gmail ingest writes ``doc_id="gmail:<hex_message_id>"`` so that ids stay
    unique across connectors. The Gmail web UI only resolves the bare hex
    message id; passing the full prefixed form 404s and bounces the user
    back to the inbox. Other connectors can be added here as we link out
    to them.
    """
    if not document_id:
        return ""
    prefix = f"{source}:"
    if source and document_id.startswith(prefix):
        return document_id[len(prefix):]
    return document_id


def _hit_url(source: str, document_id: str) -> str:
    """Build a clickable URL for a hit, when we know how to link it.

    Gmail and Slack are the linkable sources today; anything else falls
    back to an empty string and the client renders a non-clickable
    citation chip.

    Gmail ids land here in two flavors:

    - **Hex message id** (``19dfa2ccbeff78b0``) — what the OAuth Gmail
      connector stores. Resolves directly via ``#all/<id>`` permalink.
    - **RFC822 Message-ID** (``<CABCD@mail.gmail.com>``) — what the IMAP
      connector stores, since IMAP doesn't expose Gmail's internal hex
      id. The permalink form would 404; instead route through Gmail's
      search URL with the ``rfc822msgid:`` operator, which lands the user
      on the specific message.

    Slack doc_ids encode workspace + channel + timestamp as
    ``slack:{team_domain}:{channel_id}:{ts}`` so the permalink
    ``https://{team_domain}.slack.com/archives/{channel_id}/p{ts}`` can
    be reconstructed without a side lookup. Legacy two-segment ids
    (``slack:{channel_id}:{ts}`` from earlier ingests) fall back to the
    workspace-less ``slack.com/archives/...`` form.
    """
    if source == "gmail" and document_id:
        msg_id = _bare_doc_id(source, document_id)
        if not msg_id:
            return ""
        if "@" in msg_id or "<" in msg_id or ">" in msg_id:
            rfc_id = msg_id.strip("<>")
            return f"https://mail.google.com/mail/u/0/#search/rfc822msgid:{rfc_id}"
        return f"https://mail.google.com/mail/u/0/#all/{msg_id}"
    if source == "slack" and document_id:
        bare = _bare_doc_id(source, document_id)
        if not bare:
            return ""
        parts = bare.split(":")
        if len(parts) >= 3:
            team_domain, channel_id, ts = parts[0], parts[1], ":".join(parts[2:])
        elif len(parts) == 2:
            team_domain = ""
            channel_id, ts = parts
        else:
            return ""
        if not channel_id or not ts:
            return ""
        ts_clean = ts.replace(".", "")
        if team_domain:
            return f"https://{team_domain}.slack.com/archives/{channel_id}/p{ts_clean}"
        return f"https://slack.com/archives/{channel_id}/p{ts_clean}"
    return ""


def build_sources_for_client(
    hits: List[SearchHit],
    *,
    total_cap: int = 20,
) -> List[Dict[str, Any]]:
    """Produce the citation-friendly sources list streamed to the frontend.

    One entry per hit, in the same order the planner sees them — so a
    ``[N]`` citation in the synthesis maps to ``sources[N - 1]`` on the
    client. We don't deduplicate by ``document_id``: separate chunks of the
    same email each get their own citation slot since the planner may quote
    different parts.
    """
    out: List[Dict[str, Any]] = []
    for i, h in enumerate(hits[:total_cap]):
        sender = h.participants[0] if h.participants else ""
        out.append(
            {
                "ref": i + 1,
                "title": h.title,
                "sender": sender,
                "date": _hit_date(h.timestamp),
                "source_id": _bare_doc_id(h.source, h.document_id),
                "url": _hit_url(h.source, h.document_id),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


@dataclass
class ToolInvocation:
    """One tool call together with what the planner asked for and got.

    ``tool_name`` is ``"search"`` or ``"clarify"``. For search calls,
    ``num_results``, ``top_titles`` and ``raw_hits`` are populated; for
    clarify calls, ``response`` holds the user's answer.
    """

    arguments: Dict[str, Any]
    num_results: int = 0
    top_titles: List[str] = field(default_factory=list)
    raw_hits: List[SearchHit] = field(default_factory=list)
    tool_name: str = "search"
    response: str = ""


def _default_clarify_handler(question: str) -> str:
    """Prompt the user on stdout and read a one-line answer from stdin.

    Empty answers are echoed back as a sentinel so the planner doesn't think
    the user was silent because of an upstream error.
    """
    print(file=sys.stderr)
    print(f"\033[1m🤔 Clarification needed:\033[0m {question}", file=sys.stderr)
    try:
        answer = input("> ").strip()
    except EOFError:
        return "(no answer provided)"
    return answer or "(user did not provide a clarification)"


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
    on_event:
        Optional callback fired at loop milestones so callers (e.g. the SSE
        research router) can stream progress without rewriting the loop.
        Receives a dict in one of these shapes:
          - ``{"type": "search_call", "arguments": {...}}`` — about to call search
          - ``{"type": "search_result", "num_hits": N, "top_titles": [...], "sources": [{"ref": 1, "title": ..., "sender": ..., "date": ..., "source_id": ..., "url": ...}, ...]}`` — search returned
          - ``{"type": "clarify_call", "question": "..."}`` — about to ask for clarification
          - ``{"type": "clarify_response", "response": "..."}`` — clarification received
          - ``{"type": "final_answer", "text": "..."}`` — synthesis ready
        The callback runs on the same thread as ``run`` and must be non-blocking.
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
        clarify_handler: Optional[Callable[[str], str]] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._engine = engine
        self._search = search
        self._model = model
        self._max_iterations = int(max_iterations)
        self._temperature = float(temperature)
        self._max_tokens = int(max_tokens)
        self._num_ctx = int(num_ctx)
        self._clarify_handler = clarify_handler or _default_clarify_handler
        self._on_event = on_event

    def _emit(self, event: Dict[str, Any]) -> None:
        """Fire ``self._on_event`` if set; swallow callback errors."""
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception as exc:  # noqa: BLE001
            logger.debug("on_event callback raised %s — ignoring", exc)

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
            tool_name="search",
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

    def _execute_clarify(self, args: Dict[str, Any]) -> ToolInvocation:
        question = str(args.get("question", "") or "").strip()
        if not question:
            return ToolInvocation(
                tool_name="clarify",
                arguments={"question": ""},
                response="(no question provided by agent — skipping clarify)",
            )
        answer = self._clarify_handler(question)
        return ToolInvocation(
            tool_name="clarify",
            arguments={"question": question},
            response=answer,
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
            tools_arg = (
                [SEARCH_TOOL_SPEC, CLARIFY_TOOL_SPEC]
                if len(invocations) < self._max_iterations
                else None
            )
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
                    answer = content.strip()
                    self._emit({"type": "final_answer", "text": answer})
                    return ResearchResult(
                        answer=answer,
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
                                "results above. Cite sources as [1], [2], etc."
                            ),
                        )
                    )
                    continue
                fallback = "(model returned no content and no tool calls)"
                self._emit({"type": "final_answer", "text": fallback})
                return ResearchResult(
                    answer=fallback,
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

                if name == "search":
                    # Guard against the planner pre-empting clarify before any
                    # search has run — silently accept; the rule lives in the
                    # system prompt as guidance, not enforcement.
                    self._emit({"type": "search_call", "arguments": args})
                    inv = self._execute_search(args)
                    invocations.append(inv)
                    self._emit(
                        {
                            "type": "search_result",
                            "num_hits": inv.num_results,
                            "top_titles": inv.top_titles,
                            "sources": build_sources_for_client(inv.raw_hits),
                        }
                    )
                    tool_output = json.dumps(
                        shape_results_for_model(inv.raw_hits), ensure_ascii=False
                    )
                elif name == "clarify":
                    # Enforce the "search first" rule at runtime so we don't
                    # surprise the user with a clarification before showing any
                    # work. If the planner jumps to clarify with no searches
                    # behind it, return an error and let the loop try again.
                    if not any(i.tool_name == "search" for i in invocations):
                        tool_output = json.dumps(
                            {
                                "error": (
                                    "clarify is only available after at least "
                                    "one search call. Run search first, then "
                                    "use clarify if the results are ambiguous "
                                    "or empty."
                                )
                            }
                        )
                    else:
                        self._emit(
                            {"type": "clarify_call", "question": str(args.get("question", ""))}
                        )
                        inv = self._execute_clarify(args)
                        invocations.append(inv)
                        self._emit(
                            {"type": "clarify_response", "response": inv.response}
                        )
                        tool_output = json.dumps(
                            {
                                "question": inv.arguments.get("question", ""),
                                "user_response": inv.response,
                            }
                        )
                else:
                    tool_output = json.dumps(
                        {
                            "error": (
                                f"unknown tool {name!r}; available tools are "
                                "'search' and 'clarify'"
                            )
                        }
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
                            "You have used your tool-call budget (search + "
                            "clarify combined). Write the final synthesis now "
                            "using only the search results and clarifications "
                            "above. Cite sources as [1], [2], etc."
                        ),
                    )
                )

        # Loop fell through without the model producing a text response.
        # Force one final tool-less synthesis call so the caller always gets
        # an answer — bailing out with a sentinel string is never useful to
        # the user, who already paid for the searches.
        messages.append(
            Message(
                role=Role.USER,
                content=(
                    "You've used all your search attempts. Synthesize your "
                    "findings now from whatever you've found so far. Do not "
                    "request more tool calls — write the final answer as "
                    "plain text, citing sources as [1], [2], etc. where you can. "
                    "If the searches returned nothing usable, say so plainly."
                ),
            )
        )
        iterations += 1
        final = self._engine.generate(
            messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            num_ctx=self._num_ctx,
            tools=None,
        )
        for k in total_usage:
            total_usage[k] += int(final.get("usage", {}).get(k, 0))
        answer = (final.get("content", "") or "").strip()
        if not answer:
            answer = (
                "(no synthesis available — the search budget was exhausted "
                "and the model returned no text response)"
            )
        self._emit({"type": "final_answer", "text": answer})
        return ResearchResult(
            answer=answer,
            iterations=iterations,
            tool_calls=invocations,
            usage=total_usage,
        )


__all__ = [
    "ResearchAgent",
    "ResearchResult",
    "ToolInvocation",
    "SEARCH_TOOL_SPEC",
    "CLARIFY_TOOL_SPEC",
    "SYSTEM_PROMPT",
    "DEFAULT_PLANNER_MODEL",
    "shape_results_for_model",
    "build_sources_for_client",
]
