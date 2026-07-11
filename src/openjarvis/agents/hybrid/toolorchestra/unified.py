"""Real backends for the unified-tool rollout — the bridge between the pure
:func:`run_unified_rollout` loop and live model/tool calls.

``make_call_orchestrator`` returns the ``call_orchestrator`` callable (a teacher
LLM emitting tool calls over the unified spec); ``make_dispatch`` returns the
``dispatch`` callable (executes a chosen tool via ``_call_worker``). Both are
import-safe — the OpenAI SDK is imported lazily so this module loads without
network or keys.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from openjarvis.agents.hybrid._prices import cost as _model_cost
from openjarvis.agents.hybrid.expert_registry import ExpertTool, to_worker_dict
from openjarvis.agents.hybrid.toolorchestra.parsing import _parse_rl_tool_call
from openjarvis.agents.hybrid.toolorchestra.rollout import (
    UnifiedRollout,
    build_system_prompt,
    run_unified_rollout,
)
from openjarvis.agents.hybrid.toolorchestra.tracing import span
from openjarvis.agents.hybrid.toolorchestra.workers import _call_worker

# Guards the lazy, one-time build of the shared ToolExecutor in
# ``_dispatch_openjarvis_tool``: with concurrent rollouts (parallel rejection
# sampling) several threads can reach the build at once and would each instantiate
# the full tool registry. The lock makes it build-once.
_EXECUTOR_BUILD_LOCK = threading.Lock()


def make_call_orchestrator(
    model: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 1.0,
    max_tokens: int = 4096,
    timeout: float = 600.0,
    native_tools: bool = True,
    frequency_penalty: float = 0.2,
    presence_penalty: float = 0.0,
    repetition_penalty: float = 1.15,
) -> Callable[..., Tuple[str, List[Tuple[str, Dict[str, Any]]], int, int]]:
    """Teacher-orchestrator caller. ``base_url=None`` → OpenAI cloud; set it to a
    vLLM endpoint (with ``api_key="EMPTY"``) to drive a local served teacher.

    ``native_tools`` picks the tool-calling convention, and the two modes MUST NOT
    be mixed on the same model:

    * ``True`` (default — DATA GENERATION with a *base* model): pass the OpenAI
      ``tools=`` param so the server's native tool template + parser (gemma4 /
      qwen3_xml / hermes) drive the base model, which only emits reliable tool
      calls that way. The rollout captures ``(name, arguments)`` and the serializer
      re-renders them into the canonical JSON ``<tool_call>`` form regardless.
    * ``False`` (SERVING a *fine-tuned* model): bake the ``<tools>`` block + JSON
      ``<tool_call>`` format into the system prompt (exactly what the serializer
      trained on) and DROP ``tools=``. If ``tools=`` is set here, the served chat
      template injects its own XML ``<function=>`` instructions, which conflict
      with the JSON format the model learned -> it falls back to ``\\boxed{}`` and
      never routes. ``_parse_rl_tool_call`` scrapes the JSON tag from raw text.
    """

    # Create the client ONCE and reuse it for every turn. Creating a fresh OpenAI
    # client per call (as before) leaks an httpx connection pool each time -> under
    # heavy parallel generation, sockets pile up in CLOSE-WAIT, the run degrades and
    # has to be restarted. The orchestrator is the highest-frequency call, so reusing
    # one client here removes the dominant leak. httpx clients are thread-safe.
    from openai import OpenAI

    from openjarvis.agents.hybrid.toolorchestra.tracing import wrap_client

    client = wrap_client(
        OpenAI(base_url=base_url, api_key=api_key or "EMPTY", timeout=timeout)
    )

    def call_orchestrator(messages: List[Dict[str, Any]], specs: List[Dict[str, Any]]):
        # ``messages`` is the full running conversation (system/user/assistant/tool)
        # built by run_unified_rollout — pass it through so the model sees its own
        # prior calls + tool responses, not a flattened user blob.
        if native_tools:
            # Base-model generation: native tool template drives the tool calls.
            send = messages
            kwargs = {"tools": specs} if specs else {}
        else:
            # Fine-tuned serving: JSON format is baked into the system prompt and
            # tools= is dropped (see make_call_orchestrator docstring).
            send = list(messages)
            if specs and send and send[0].get("role") == "system":
                send[0] = {"role": "system", "content": build_system_prompt(specs)}
            kwargs = {}
        # repetition_penalty is a vLLM extra (not OpenAI-native); only send it to a
        # local vLLM endpoint (base_url set), never to the cloud frontier APIs.
        if base_url and repetition_penalty and repetition_penalty != 1.0:
            kwargs.setdefault("extra_body", {})["repetition_penalty"] = (
                repetition_penalty
            )
        resp = client.chat.completions.create(
            model=model,
            messages=send,
            temperature=temperature,
            max_tokens=max_tokens,
            frequency_penalty=frequency_penalty,
            presence_penalty=presence_penalty,
            **kwargs,
        )
        msg = resp.choices[0].message
        text = msg.content or ""
        sdk_tool_calls = getattr(msg, "tool_calls", None)
        u = resp.usage
        p = getattr(u, "prompt_tokens", 0) if u else 0
        c = getattr(u, "completion_tokens", 0) if u else 0

        parsed = _parse_rl_tool_call(text, sdk_tool_calls)
        tool_calls = [(parsed["name"], parsed["arguments"])] if parsed else []
        return text, tool_calls, int(p), int(c)

    return call_orchestrator


def _dispatch_openjarvis_tool(
    tool: ExpertTool,
    arguments: Dict[str, Any],
    executor_holder: Dict[str, Any],
) -> Tuple[str, float, int, bool]:
    """Execute a bridged real OpenJarvis tool via its ``ToolExecutor``.

    Builds the executor lazily (cached in ``executor_holder``) and degrades to a
    clear error string — never a crash — if the tool registry / executor can't be
    instantiated. Returns ``(content, cost_usd, total_tokens, is_local=True)``.
    """
    try:
        executor = executor_holder.get("executor")
        if executor is None:
            with _EXECUTOR_BUILD_LOCK:
                # Re-check inside the lock: another thread may have built it while
                # we waited.
                executor = executor_holder.get("executor")
                if executor is None:
                    from openjarvis.core.registry import ToolRegistry
                    from openjarvis.tools._stubs import ToolExecutor

                    instances = []
                    for name in ToolRegistry.keys():
                        entry = ToolRegistry.get(name)
                        try:
                            instances.append(
                                entry() if isinstance(entry, type) else entry
                            )
                        except Exception:
                            continue
                    # Auto-approve confirmation-gated tools (shell_exec,
                    # git_commit, ...): rollouts/eval run headless in a sandbox, so
                    # there is no human to confirm. Without this, those tools return
                    # a "requires confirmation" error instead of executing — which
                    # would silently break TerminalBench.
                    executor = ToolExecutor(
                        instances,
                        interactive=True,
                        confirm_callback=lambda _prompt: True,
                    )
                    executor_holder["executor"] = executor

        from openjarvis.core.types import ToolCall

        call = ToolCall(
            id=f"orch-{tool.name}",
            name=str(tool.model),
            arguments=json.dumps(arguments or {}),
        )
        result = executor.execute(call)
        usage = getattr(result, "usage", None) or {}
        total_tokens = int(usage.get("total_tokens", 0) or 0)
        return (
            str(getattr(result, "content", "")),
            float(getattr(result, "cost_usd", 0.0) or 0.0),
            total_tokens,
            True,
        )
    except Exception as exc:  # never crash the rollout on a tool-bridge failure
        return (f"[openjarvis-tool error: {tool.model}: {exc}]", 0.0, 0, True)


def make_dispatch(
    cfg: Optional[Dict[str, Any]] = None,
) -> Callable[[ExpertTool, Dict[str, Any]], Tuple[str, float, int, bool]]:
    """Tool-execution caller: run the chosen tool and return (obs, cost, tokens, is_local)."""
    cfg = cfg or {}
    executor_holder: Dict[str, Any] = {}

    def _dispatch_inner(tool: ExpertTool, arguments: Dict[str, Any]):
        # Bridged real OpenJarvis tools run through the ToolExecutor, not
        # the model/worker path.
        if tool.backend_type == "openjarvis-tool":
            return _dispatch_openjarvis_tool(tool, arguments or {}, executor_holder)

        worker = to_worker_dict(tool)
        prompt = ""
        for key in ("input", "query", "code"):
            val = arguments.get(key)
            if isinstance(val, str) and val.strip():
                prompt = val
                break
        if not prompt.strip():
            # The orchestrator emitted a tool call with no/empty input. Don't hit
            # the API (it 400s on empty content) — return a usable error so the
            # rollout keeps going instead of dropping.
            return (
                f"[{tool.name}: no input provided — supply a non-empty "
                "'input' to delegate]",
                0.0,
                0,
                True,
            )
        text, p, c, is_local, extra_cost, _n = _call_worker(worker, prompt, cfg)
        usd = (0.0 if is_local else _model_cost(str(tool.model), p, c)) + float(
            extra_cost
        )
        return text, usd, int(p) + int(c), bool(is_local)

    def dispatch(tool: ExpertTool, arguments: Dict[str, Any]):
        # One span per route so the trace tree shows which expert/tool was called,
        # with the delegated input, the returned observation, and cost/tokens. The
        # wrapped OpenAI/Anthropic call (if any) nests one level deeper.
        # Span is titled with the REAL model that actually ran (``tool.model``) so
        # the trace reads clearly even under anonymization; ``anon_label`` in the
        # metadata records the opaque label the orchestrator actually saw/chose.
        real_model = str(tool.model)
        with span(
            f"route:{real_model}",
            span_type="tool",
            input=arguments,
            metadata={
                "real_model": real_model,
                "anon_label": tool.name,
                "backend": tool.backend_type,
            },
        ) as s:
            obs, usd, toks, is_local = _dispatch_inner(tool, arguments)
            s.log(
                output=obs,
                metrics={"cost_usd": usd, "tokens": toks},
                metadata={"is_local": is_local},
            )
            return obs, usd, toks, is_local

    return dispatch


def teacher_rollout(
    question: str,
    tools: List[ExpertTool],
    *,
    teacher_model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 1.0,
    max_turns: int = 50,
    cfg: Optional[Dict[str, Any]] = None,
) -> UnifiedRollout:
    """Convenience: one full teacher rollout with real backends."""
    return run_unified_rollout(
        question,
        tools,
        call_orchestrator=make_call_orchestrator(
            teacher_model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
        ),
        dispatch=make_dispatch(cfg),
        max_turns=max_turns,
    )


__all__ = ["make_call_orchestrator", "make_dispatch", "teacher_rollout"]
