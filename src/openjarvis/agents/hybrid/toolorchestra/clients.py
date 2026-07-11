"""Orchestrator vLLM tool-call client for ToolOrchestraAgent."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def _call_orchestrator_with_tool_calls(
    model: str,
    endpoint: str,
    *,
    user: str,
    system: str,
    max_tokens: int,
    temperature: float,
    tools: List[Dict[str, Any]],
    timeout: float = 600.0,
) -> Tuple[str, int, int, Any]:
    """Orchestrator-aware vLLM call. Returns (text, p_tok, c_tok, tool_calls).

    Mirrors ``LocalCloudAgent._call_vllm`` but ALSO surfaces the SDK-level
    ``tool_calls`` object so the RL-mode parser can match against it
    directly. Otherwise vLLM's tool parser silently swallows the tool call
    into the SDK field while leaving ``content == ''`` — and the text-tag
    parser sees nothing, falling through to the answer-1 fallback. (Bug
    observed 2026-05-19 on the paper-match smoke; same path was buggy on
    the default pool too, just less reproducibly.)
    """
    from openai import OpenAI

    client = OpenAI(base_url=endpoint, api_key="EMPTY", timeout=timeout)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    choice = resp.choices[0]
    message = choice.message
    text = message.content or ""
    tool_calls = getattr(message, "tool_calls", None)
    u = resp.usage
    p = getattr(u, "prompt_tokens", 0) if u else 0
    c = getattr(u, "completion_tokens", 0) if u else 0
    return text, p, c, tool_calls
