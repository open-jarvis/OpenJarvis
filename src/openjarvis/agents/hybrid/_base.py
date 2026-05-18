"""LocalCloudAgent — shared base for hybrid local+cloud paradigm agents.

The hybrid paradigms (Minions, Conductor, Archon, Advisors, SkillOrchestra,
ToolOrchestra) all coordinate at least two models: a small **local** model
served by vLLM over an OpenAI-compatible endpoint, and a **cloud** model
reached via the Anthropic or OpenAI SDK.

Why not just use OpenJarvis's :class:`InferenceEngine` for both? Two reasons:

1. The reference hybrid adapters (``hybrid-local-cloud-compute/adapters/``) make
   raw SDK calls because some of them (Minions, Archon) construct external
   library objects that themselves create their own SDK clients. We mirror that
   here so the n=500 numbers stay reproducible during the port.
2. Cloud-side quirks (Opus 4.7 temperature stripping, GPT-5 family
   ``max_completion_tokens``) are paradigm-shaped — Minions needs structured
   outputs on the supervisor turn, SkillOrchestra needs them on the router,
   baseline_cloud does not. Keeping the SDK calls in the agent layer lets each
   paradigm decide the schema rather than fighting a shared engine API.

The base class therefore provides only:

- Standard ``run()`` contract returning an :class:`AgentResult` whose
  ``metadata`` carries the hybrid-result fields (``tokens_local``,
  ``tokens_cloud``, ``cost_usd``, ``latency_s``, ``traces``).
- ``_call_anthropic`` / ``_call_openai`` / ``_call_vllm`` helpers that handle
  Opus 4.7 temperature stripping, GPT-5 token-arg naming, vLLM
  ``enable_thinking`` kwargs, and basic token bookkeeping.
- ``_soft_fail_metadata`` for deterministic failure rows (e.g. Qwen JSON
  malformation) so the runner doesn't crash the whole cell.

Agents register themselves with ``@AgentRegistry.register("name")`` and become
discoverable via the existing SDK / CLI flow. The runner constructs them with
the cloud ``(engine, model)`` as the canonical pair, and paradigm-specific
kwargs (``local_model``, ``local_endpoint``, ``cloud_endpoint``, …) follow.
"""

from __future__ import annotations

import json
import threading
import time
from abc import abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.agents.hybrid._prices import (
    NO_TEMP_PREFIXES,
    is_gpt5_family,
    supports_temperature,
)
from openjarvis.agents.hybrid._prices import (
    cost as estimate_cost,
)
from openjarvis.engine._stubs import InferenceEngine

# Anthropic server-side web_search: $10 per 1000 searches.
WEB_SEARCH_COST_PER_CALL = 0.01

ANTHROPIC_WEB_SEARCH_TOOL = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 8,
}


# ---------- Thread-local trace buffer ----------
#
# Every call through ``_call_anthropic`` / ``_call_openai`` / ``_call_vllm``
# appends an event to the active trace if one is open. ``run()`` opens a fresh
# trace per task and writes the digested log to
# ``<log_dir>/<task_id>.json`` when it's done. Thread-local so concurrent
# tasks in the runner's ThreadPoolExecutor don't stomp each other's trace.

_TRACE_STATE = threading.local()


def _trace_events() -> Optional[List[Dict[str, Any]]]:
    return getattr(_TRACE_STATE, "events", None)


def _record_event(event: Dict[str, Any]) -> None:
    events = _trace_events()
    if events is not None:
        events.append(event)


def _open_trace() -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    _TRACE_STATE.events = events
    return events


def _close_trace() -> None:
    if hasattr(_TRACE_STATE, "events"):
        delattr(_TRACE_STATE, "events")


def _serialize_block(block: Any) -> Dict[str, Any]:
    """Turn an Anthropic content block (text / tool_use / server_tool_use /
    web_search_tool_result / thinking) into a JSON-safe dict.

    Each block type carries different fields; we extract everything we can
    so the per-task log file is a complete record of what the model emitted
    (including every tool call request and tool result body).
    """
    out: Dict[str, Any] = {"type": getattr(block, "type", type(block).__name__)}
    for attr in (
        "id", "name", "input", "text", "thinking", "signature",
        "tool_use_id", "content",
    ):
        if hasattr(block, attr):
            val = getattr(block, attr)
            # Nested content (e.g. web_search_tool_result.content is a list of
            # citation/result blocks). Recurse for completeness.
            if attr == "content" and isinstance(val, list):
                out[attr] = [_serialize_block(b) for b in val]
            else:
                out[attr] = _jsonable(val)
    return out


def _serialize_openai_tool_calls(tool_calls: Any) -> List[Dict[str, Any]]:
    """vLLM / OpenAI returns ChatCompletionMessageToolCall objects. Pull out
    id, type, name, and the (JSON-string) arguments so they're round-trippable."""
    out: List[Dict[str, Any]] = []
    if not tool_calls:
        return out
    for tc in tool_calls:
        fn = getattr(tc, "function", None)
        out.append({
            "id": getattr(tc, "id", None),
            "type": getattr(tc, "type", "function"),
            "function": {
                "name": getattr(fn, "name", None) if fn else None,
                "arguments": getattr(fn, "arguments", None) if fn else None,
            },
        })
    return out


def _jsonable(v: Any) -> Any:
    """Best-effort JSON-friendly conversion. Pydantic models → .model_dump(),
    dataclasses untouched (json.dumps handles them via default=str)."""
    if hasattr(v, "model_dump"):
        try:
            return v.model_dump()
        except Exception:
            pass
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    return v


class LocalCloudAgent(BaseAgent):
    """Base for paradigm agents that coordinate a local + cloud model pair.

    Subclasses implement :meth:`_run_paradigm` rather than ``run`` so the
    base can wrap timing, metadata shaping, and soft-fail handling
    uniformly.

    The :meth:`run` contract takes the formatted task prompt as ``input``
    and reads paradigm-shaped data from ``context.metadata``:

    - ``context.metadata["task"]``: optional dict (the bench's raw task
      row, used by paradigms that look at hints / problem_statement / etc.).
    - ``context.metadata["task_id"]``: optional string identifier.

    Construction args:
    - ``engine``, ``model``: the cloud engine + model id (satisfies
      :class:`BaseAgent`'s contract; only used incidentally — we make raw
      SDK calls).
    - ``local_model``, ``local_endpoint``: vLLM-served local model and its
      OpenAI-compatible endpoint, e.g. ``"http://localhost:8001/v1"``.
    - ``cloud_endpoint``: ``"anthropic"`` or ``"openai"`` — picks the
      cloud SDK.
    - ``cfg``: paradigm-specific knobs (max_tokens, schemas, mode, …).
    """

    accepts_tools: bool = False

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        local_model: Optional[str] = None,
        local_endpoint: Optional[str] = None,
        cloud_endpoint: str = "anthropic",
        cfg: Optional[Dict[str, Any]] = None,
        bus: Optional[Any] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._cloud_model = model
        self._cloud_endpoint = (cloud_endpoint or "anthropic").lower()
        self._local_model = local_model
        self._local_endpoint = local_endpoint
        self._cfg: Dict[str, Any] = dict(cfg or {})

    # ------------------------------------------------------------------
    # SDK call helpers — raw clients, paradigm-shaped quirks applied
    # ------------------------------------------------------------------

    @staticmethod
    def _call_anthropic(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        tools: Optional[list] = None,
        tool_choice: Optional[dict] = None,
        output_config: Optional[dict] = None,
        timeout: float = 600.0,
        max_retries: int = 5,
        trace_role: str = "cloud",
    ) -> Tuple[str, int, int, int]:
        """Single Anthropic call. Returns (text, p_tok, c_tok, n_web_searches).

        Strips ``temperature`` for Opus 4.7+ (rejected by the API). Captures
        the call into the active per-task trace if one is open.
        """
        import anthropic

        client = anthropic.Anthropic(timeout=timeout, max_retries=max_retries)
        kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            kwargs["system"] = system
        if supports_temperature(model):
            kwargs["temperature"] = temperature
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if output_config:
            kwargs["output_config"] = output_config
        t0 = time.time()
        msg = client.messages.create(**kwargs)
        latency = time.time() - t0
        text = "".join(b.text for b in msg.content if hasattr(b, "text"))
        srv = getattr(msg.usage, "server_tool_use", None)
        n_searches = getattr(srv, "web_search_requests", 0) if srv else 0
        content_blocks = [_serialize_block(b) for b in msg.content]
        tool_use_blocks = [b for b in content_blocks if b.get("type") in (
            "tool_use", "server_tool_use",
        )]
        tool_result_blocks = [b for b in content_blocks if b.get("type") in (
            "web_search_tool_result", "tool_result",
        )]
        _record_event({
            "kind": "anthropic",
            "role": trace_role,
            "model": model,
            "system": system,
            "user": user,
            "response": text,
            "content_blocks": content_blocks,
            "tool_calls": tool_use_blocks,
            "tool_results": tool_result_blocks,
            "tokens_in": msg.usage.input_tokens,
            "tokens_out": msg.usage.output_tokens,
            "n_web_searches": n_searches,
            "tools_declared": tools,
            "tool_choice": tool_choice,
            "output_config": output_config,
            "stop_reason": getattr(msg, "stop_reason", None),
            "latency_s": latency,
            "ts": time.time(),
        })
        return text, msg.usage.input_tokens, msg.usage.output_tokens, n_searches

    @staticmethod
    def _call_openai(
        model: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        response_format: Optional[dict] = None,
        tools: Optional[list] = None,
        tool_choice: Optional[Any] = None,
        timeout: float = 600.0,
        trace_role: str = "cloud",
    ) -> Tuple[str, int, int]:
        """Single OpenAI call. Returns (text, p_tok, c_tok). Trace-captured;
        also records any tool_calls the model emits."""
        from openai import OpenAI

        client = OpenAI(timeout=timeout)
        messages: list = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        kwargs: Dict[str, Any] = {"model": model, "messages": messages}
        if is_gpt5_family(model):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = temperature
        if response_format is not None:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        t0 = time.time()
        resp = client.chat.completions.create(**kwargs)
        latency = time.time() - t0
        choice = resp.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls = _serialize_openai_tool_calls(getattr(message, "tool_calls", None))
        reasoning = getattr(message, "reasoning_content", None) or getattr(
            message, "reasoning", None
        )
        u = resp.usage
        p = getattr(u, "prompt_tokens", 0) if u else 0
        c = getattr(u, "completion_tokens", 0) if u else 0
        _record_event({
            "kind": "openai",
            "role": trace_role,
            "model": model,
            "system": system,
            "user": user,
            "response": text,
            "tool_calls": tool_calls,
            "reasoning_content": reasoning,
            "tokens_in": p,
            "tokens_out": c,
            "response_format": response_format,
            "tools_declared": tools,
            "tool_choice": tool_choice,
            "finish_reason": getattr(choice, "finish_reason", None),
            "latency_s": latency,
            "ts": time.time(),
        })
        return text, p, c

    @staticmethod
    def _call_vllm(
        model: str,
        endpoint: str,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        enable_thinking: bool = False,
        tools: Optional[list] = None,
        tool_choice: Optional[Any] = None,
        timeout: float = 600.0,
        trace_role: str = "local",
    ) -> Tuple[str, int, int]:
        """Local vLLM (OpenAI-compatible) call. Returns (text, p_tok, c_tok).
        Captures the full response into the trace — including any tool_calls
        the local model emits (vLLM exposes them in
        ``resp.choices[0].message.tool_calls`` when ``--enable-auto-tool-choice``
        is on)."""
        from openai import OpenAI

        client = OpenAI(base_url=endpoint, api_key="EMPTY", timeout=timeout)
        messages: list = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        kwargs: Dict[str, Any] = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
        )
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        t0 = time.time()
        resp = client.chat.completions.create(**kwargs)
        latency = time.time() - t0
        choice = resp.choices[0]
        message = choice.message
        text = message.content or ""
        tool_calls = _serialize_openai_tool_calls(getattr(message, "tool_calls", None))
        reasoning = getattr(message, "reasoning_content", None) or getattr(
            message, "reasoning", None
        )
        u = resp.usage
        p = getattr(u, "prompt_tokens", 0) if u else 0
        c = getattr(u, "completion_tokens", 0) if u else 0
        _record_event({
            "kind": "vllm",
            "role": trace_role,
            "model": model,
            "endpoint": endpoint,
            "system": system,
            "user": user,
            "response": text,
            "tool_calls": tool_calls,
            "reasoning_content": reasoning,
            "tokens_in": p,
            "tokens_out": c,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "enable_thinking": enable_thinking,
            "tools_declared": tools,
            "tool_choice": tool_choice,
            "finish_reason": getattr(choice, "finish_reason", None),
            "latency_s": latency,
            "ts": time.time(),
        })
        return text, p, c

    def _call_cloud(
        self,
        *,
        user: str,
        system: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
        **kwargs: Any,
    ) -> Tuple[str, int, int]:
        """Dispatch a single cloud call by ``self._cloud_endpoint``.

        Returns (text, p_tok, c_tok). For Anthropic, the web_search count
        is discarded — paradigms that care should call ``_call_anthropic``
        directly.
        """
        if self._cloud_endpoint == "anthropic":
            text, p, c, _ = self._call_anthropic(
                self._cloud_model,
                user=user,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
            return text, p, c
        if self._cloud_endpoint == "openai":
            return self._call_openai(
                self._cloud_model,
                user=user,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
        raise ValueError(f"unsupported cloud endpoint: {self._cloud_endpoint!r}")

    # ------------------------------------------------------------------
    # Result shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _soft_fail_metadata(reason: str) -> Dict[str, Any]:
        """Metadata for a soft-fail row (Qwen JSON broke, Anthropic 400, etc.).

        The agent still returns an :class:`AgentResult` with empty content;
        the runner records it as score=0 without crashing the cell.
        """
        return {
            "tokens_local": 0,
            "tokens_cloud": 0,
            "cost_usd": 0.0,
            "latency_s": 0.0,
            "soft_error": reason,
            "traces": {"soft_error": reason},
        }

    @staticmethod
    def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
        return estimate_cost(model, prompt_tokens, completion_tokens)

    # ------------------------------------------------------------------
    # Run contract
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)
        t0 = time.time()
        events = _open_trace()
        meta: Dict[str, Any]
        answer: str = ""
        soft_reason: Optional[str] = None
        exc_obj: Optional[BaseException] = None
        try:
            try:
                answer, meta = self._run_paradigm(input, context, **kwargs)
            except Exception as exc:
                soft = self._is_soft_failure(exc)
                if soft is None:
                    exc_obj = exc
                    raise
                soft_reason = soft
                meta = self._soft_fail_metadata(soft)
        finally:
            # Persist the trace before the trace state is closed (and even on
            # hard failure, so we get a record of what we did before it broke).
            self._write_trace_log(
                context, input, answer, meta if "meta" in locals() else {},
                events, soft_reason, exc_obj,
            )
            _close_trace()
        meta.setdefault("latency_s", time.time() - t0)
        if soft_reason is not None:
            self._emit_turn_end(soft_error=soft_reason)
            return AgentResult(content="", metadata=meta, turns=0)
        self._emit_turn_end(**{k: v for k, v in meta.items() if k != "traces"})
        return AgentResult(
            content=answer,
            metadata=meta,
            turns=int(meta.get("turns", 0) or 0),
        )

    @staticmethod
    def record_trace_event(event: Dict[str, Any]) -> None:
        """Public hook for paradigm code that bypasses the SDK helpers
        (Minions's protocol loop, Archon's layer pipeline, …) to drop a
        custom event into the current task's trace.
        """
        _record_event({**event, "ts": event.get("ts", time.time())})

    def _write_trace_log(
        self,
        context: Optional[AgentContext],
        input: str,
        answer: str,
        meta: Dict[str, Any],
        events: List[Dict[str, Any]],
        soft_reason: Optional[str],
        exc: Optional[BaseException],
    ) -> None:
        log_dir = None
        task_id = "unknown"
        if context is not None:
            log_dir = context.metadata.get("log_dir")
            task_id = context.metadata.get("task_id") or task_id
        if not log_dir:
            return
        try:
            out_dir = Path(log_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            blob = {
                "task_id": task_id,
                "agent": self.agent_id,
                "cloud_model": self._cloud_model,
                "cloud_endpoint": self._cloud_endpoint,
                "local_model": self._local_model,
                "local_endpoint": self._local_endpoint,
                "cfg": self._cfg,
                "input": input,
                "answer": answer,
                "metadata": meta,
                "events": events,
                "soft_error": soft_reason,
                "error": (
                    f"{type(exc).__name__}: {exc}" if exc is not None else None
                ),
            }
            (out_dir / f"{task_id}.json").write_text(
                json.dumps(blob, indent=2, default=str)
            )
        except Exception:
            # Logging must never break a run.
            pass

    @abstractmethod
    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        """Run the paradigm. Return ``(final_answer, metadata)``.

        Metadata should include the hybrid-shape fields:
        ``tokens_local``, ``tokens_cloud``, ``cost_usd``, optional
        ``latency_s`` (the base fills it if absent), and a ``traces`` dict.
        """

    # Subclasses override to declare deterministic failure modes they
    # want the base to swallow into a soft-fail row.
    def _is_soft_failure(self, exc: BaseException) -> Optional[str]:
        return None


__all__ = [
    "ANTHROPIC_WEB_SEARCH_TOOL",
    "LocalCloudAgent",
    "NO_TEMP_PREFIXES",
    "WEB_SEARCH_COST_PER_CALL",
    "estimate_cost",
    "is_gpt5_family",
    "supports_temperature",
]
