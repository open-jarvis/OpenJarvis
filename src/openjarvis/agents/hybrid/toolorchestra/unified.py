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
from typing import Any, Callable, Dict, List, Optional, Tuple

from openjarvis.agents.hybrid._prices import cost as _model_cost
from openjarvis.agents.hybrid.expert_registry import ExpertTool, to_worker_dict
from openjarvis.agents.hybrid.toolorchestra.parsing import _parse_rl_tool_call
from openjarvis.agents.hybrid.toolorchestra.rollout import (
    UnifiedRollout,
    run_unified_rollout,
)
from openjarvis.agents.hybrid.toolorchestra.workers import _call_worker


def make_call_orchestrator(
    model: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 1.0,
    max_tokens: int = 4096,
    timeout: float = 600.0,
) -> Callable[..., Tuple[str, List[Tuple[str, Dict[str, Any]]], int, int]]:
    """Teacher-orchestrator caller. ``base_url=None`` → OpenAI cloud; set it to a
    vLLM endpoint (with ``api_key="EMPTY"``) to drive a local served teacher.
    """

    def call_orchestrator(system: str, user: str, specs: List[Dict[str, Any]]):
        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY", timeout=timeout)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            tools=specs,
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
            from openjarvis.core.registry import ToolRegistry
            from openjarvis.tools._stubs import ToolExecutor

            instances = []
            for name in ToolRegistry.keys():
                entry = ToolRegistry.get(name)
                try:
                    instances.append(entry() if isinstance(entry, type) else entry)
                except Exception:
                    continue
            # Auto-approve confirmation-gated tools (shell_exec, git_commit, ...):
            # rollouts/eval run headless in a sandbox, so there is no human to
            # confirm. Without this, those tools return a "requires confirmation"
            # error instead of executing — which would silently break TerminalBench.
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

    def dispatch(tool: ExpertTool, arguments: Dict[str, Any]):
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
        text, p, c, is_local, extra_cost, _n = _call_worker(worker, prompt, cfg)
        usd = (0.0 if is_local else _model_cost(str(tool.model), p, c)) + float(extra_cost)
        return text, usd, int(p) + int(c), bool(is_local)

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
            teacher_model, base_url=base_url, api_key=api_key, temperature=temperature,
        ),
        dispatch=make_dispatch(cfg),
        max_turns=max_turns,
    )


__all__ = ["make_call_orchestrator", "make_dispatch", "teacher_rollout"]
