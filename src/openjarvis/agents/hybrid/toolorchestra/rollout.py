"""Faithful unified-tool rollout loop for ToolOrchestra (arXiv:2511.21689 §2.2).

One reasoning->action->observation loop where the orchestrator picks **a named
tool** (one per model, from :mod:`expert_registry`) each turn, the environment
executes it, and the observation is appended to a running context. The rollout
ends when the orchestrator emits a turn with **no tool call** (its text is the
final answer) or ``max_turns`` is hit.

The loop is parameterized over two injected callables so it is pure control flow
(no network) and unit-testable with fakes — the agent supplies real ones:

* ``call_orchestrator(system, user, tool_specs) -> (text, tool_calls, p_tok, c_tok)``
  where ``tool_calls`` is a list of ``(name, arguments)`` (possibly empty).
* ``dispatch(tool, arguments) -> (observation, cost_usd, tokens, is_local)``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from openjarvis.agents.hybrid.expert_registry import (
    ExpertTool,
    build_tool_specs,
    tools_by_name,
)

RL_ORCHESTRATOR_SYS = "You are good at using tools."


def build_system_prompt(specs: List[Dict[str, object]]) -> str:
    """Faithful ToolOrchestra system prompt (arXiv:2511.21689, verbatim from
    their ``prepare_sft_data.py``): the ``RL_ORCHESTRATOR_SYS`` preamble + the
    Qwen-style ``<tools>``/``<tool_call>`` block. Deliberately contains NO
    routing/delegation instructions — cost-aware routing is learned from the RL
    reward, not prompted.
    """
    tools_block = "\n".join(json.dumps(s) for s in specs)
    return (
        f"{RL_ORCHESTRATOR_SYS}\n\n# Tools\n\n"
        "You may call one or more functions to assist with the user query.\n\n"
        "You are provided with function signatures within <tools></tools> "
        "XML tags:\n"
        f"<tools>\n{tools_block}\n</tools>\n\n"
        "For each function call, return a json object with function name and "
        "arguments within <tool_call></tool_call> XML tags:\n"
        '<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}'
        "\n</tool_call>"
    )

# Char-level cap on the accumulated context (mirrors the paper's ~24k-token cap).
_CONTEXT_CAP = 24000


@dataclass
class UnifiedTurn:
    """One orchestrator turn. ``tool_name is None`` marks the final-answer turn."""

    reasoning: str
    tool_name: Optional[str] = None
    arguments: Dict[str, object] = field(default_factory=dict)
    observation: Optional[str] = None


@dataclass
class UnifiedRollout:
    turns: List[UnifiedTurn]
    final_answer: str
    cost_usd: float = 0.0
    tokens: int = 0
    num_tool_calls: int = 0
    parse_failures: int = 0

    def tool_calls(self) -> List[Tuple[str, Dict[str, object]]]:
        return [(t.tool_name, t.arguments) for t in self.turns if t.tool_name]


def _tool_prompt(tool: ExpertTool, arguments: Dict[str, object], question: str) -> str:
    """The text we actually send the dispatched tool, framed by its arg schema."""
    for key in ("input", "query", "code"):
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return question


def run_unified_rollout(
    question: str,
    tools: List[ExpertTool],
    *,
    call_orchestrator: Callable[..., Tuple[str, List[Tuple[str, Dict[str, object]]], int, int]],
    dispatch: Callable[[ExpertTool, Dict[str, object]], Tuple[str, float, int, bool]],
    max_turns: int = 50,
    system: str = RL_ORCHESTRATOR_SYS,
) -> UnifiedRollout:
    """Drive the faithful unified-tool rollout for one task."""
    specs = build_tool_specs(tools)
    by_name = tools_by_name(tools)

    context = ""
    turns: List[UnifiedTurn] = []
    cost = 0.0
    tokens = 0
    n_tool_calls = 0
    parse_failures = 0
    final_answer = ""

    for _ in range(max_turns):
        user = (
            f"Problem: {question}\n\n{context or '(no context yet)'}\n\n"
            "Choose an appropriate tool, or answer directly if you have enough."
        )
        text, tool_calls, p_tok, c_tok = call_orchestrator(system, user, specs)
        tokens += int(p_tok) + int(c_tok)

        if not tool_calls:
            # No tool call -> the orchestrator is answering. Terminate.
            final_answer = (text or "").strip()
            turns.append(UnifiedTurn(reasoning=text or "", tool_name=None))
            break

        name, arguments = tool_calls[0]
        if name not in by_name:
            parse_failures += 1
            context = (context + f"\n[invalid tool {name!r} — choose from the list]")[-_CONTEXT_CAP:]
            if parse_failures >= 2:
                final_answer = (text or "").strip()
                break
            continue

        tool = by_name[name]
        obs, dcost, dtok, _is_local = dispatch(tool, arguments)
        cost += float(dcost)
        tokens += int(dtok)
        n_tool_calls += 1
        turns.append(UnifiedTurn(
            reasoning=text or "", tool_name=name, arguments=dict(arguments),
            observation=obs,
        ))
        context = (context + f"\n[{name}] {obs}")[-_CONTEXT_CAP:]
    else:
        # Hit max_turns with no explicit answer: use the last observation/text.
        final_answer = (turns[-1].observation or turns[-1].reasoning).strip() if turns else ""

    return UnifiedRollout(
        turns=turns, final_answer=final_answer, cost_usd=cost, tokens=tokens,
        num_tool_calls=n_tool_calls, parse_failures=parse_failures,
    )


def tool_call_tag(name: str, arguments: Dict[str, object]) -> str:
    """Render a tool call as the ``<tool_call>{...}</tool_call>`` text the model emits."""
    return f"<tool_call>{json.dumps({'name': name, 'arguments': arguments})}</tool_call>"


__all__ = [
    "RL_ORCHESTRATOR_SYS",
    "UnifiedRollout",
    "UnifiedTurn",
    "build_system_prompt",
    "run_unified_rollout",
    "tool_call_tag",
]
