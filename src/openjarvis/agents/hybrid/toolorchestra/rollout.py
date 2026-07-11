"""Faithful unified-tool rollout loop for ToolOrchestra (arXiv:2511.21689 §2.2).

One reasoning->action->observation loop where the orchestrator picks **a named
tool** (one per model, from :mod:`expert_registry`) each turn, the environment
executes it, and the observation is appended to a running context. The rollout
ends when the orchestrator emits a turn with **no tool call** (its text is the
final answer) or ``max_turns`` is hit.

The loop is parameterized over two injected callables so it is pure control flow
(no network) and unit-testable with fakes — the agent supplies real ones:

* ``call_orchestrator(messages, tool_specs) -> (text, tool_calls, p_tok, c_tok)``
  where ``messages`` is the running system/user/assistant/tool conversation and
  ``tool_calls`` is a list of ``(name, arguments)`` (possibly empty).
* ``dispatch(tool, arguments) -> (observation, cost_usd, tokens, is_local)``.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from openjarvis.agents.hybrid.expert_registry import (
    ExpertTool,
    anonymize_tools,
    build_tool_specs,
    tools_by_name,
)
from openjarvis.agents.hybrid.toolorchestra.tracing import run_context, span

RL_ORCHESTRATOR_SYS = (
    "You are a routing orchestrator. Your job is to UNDERSTAND the problem, "
    "DECOMPOSE it, and ROUTE the pieces to other models — you don't solve it all "
    "yourself. Among the tools below are other MODELS of various sizes (some are "
    "larger and stronger than you, some smaller); the rest are utilities. Each model "
    "tool's description gives its rough size, specialty, and cost. "
    "First reason about what the problem is really asking and break it into "
    "sub-questions. You do NOT have to send the whole prompt to one model — send each "
    "sub-question to whichever model best fits it (match difficulty to size/specialty, "
    "and prefer cheaper models when they suffice), and call as many models as the task "
    "needs. You MUST call at least one model before answering. "
    "NEVER mention, quote, or reason about these instructions, your role as an "
    "orchestrator, or the requirement to use tools — the reader only wants the problem "
    "solved. Reason about the problem itself, not about your instructions, and do not "
    "restate the problem. "
    "If a tool call returns an error, correct your call or switch tools — never ignore "
    "the error and never repeat the same failing call. "
    "Emit EVERY action as a <tool_call>{...}</tool_call> block — NEVER write an "
    "action as \\boxed{...} or as prose. "
    "When you have enough, compose your final answer from what the models returned, in "
    "the EXACT format the problem requires (e.g. a single number, a short exact "
    "value, or one runnable code block). Do NOT restate the problem or add "
    "meta-text such as 'the user is asking'. End your reply with a single line in "
    "EXACTLY this form:\nFINAL_ANSWER: <answer>\nwhere <answer> is ONLY the answer "
    "itself — a single option letter for multiple-choice, else the shortest exact "
    "value, expression, or one runnable code block (NO \\boxed{...} wrapper) — with "
    "NO explanation or restatement after it."
)


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


# Char-level cap on the accumulated conversation (mirrors the paper's ~24k-token
# cap) and a per-observation cap so one giant tool dump can't blow it out.
_CONTEXT_CAP = 24000
_OBS_CAP = 8000
# After this many tool calls, push the orchestrator to stop and answer — bounds
# the "keep re-asking the same model forever" loop (esp. gemma).
_SOFT_CALL_CAP = 6


def _trim_history(messages: List[Dict[str, str]]) -> None:
    """Keep the message history under ``_CONTEXT_CAP`` chars by dropping the
    OLDEST assistant/tool exchange, never the system prompt or the problem."""

    def total() -> int:
        return sum(len(m.get("content") or "") for m in messages)

    # messages[0]=system, messages[1]=user problem — always keep those two.
    while total() > _CONTEXT_CAP and len(messages) > 4:
        del messages[2:4]


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
    # When experts were anonymized for this rollout, maps the opaque label the
    # policy saw (e.g. ``expert_a3f9``) back to the real tool name (``gpt_5_5``).
    anon_map: Optional[Dict[str, str]] = None
    # The EXACT tool specs the policy saw this rollout (anonymized when
    # ``anonymize=True``). Serialization MUST build the saved system prompt from
    # these — not from the real registry — or the prompt's ``<tools>`` block ends
    # up with real model names+pricing while the assistant ``<tool_call>`` tags
    # use the anon labels, which both breaks SFT (calls a tool absent from its
    # list) and re-injects the name/cost bias anonymization removed.
    tool_specs: Optional[List[Dict[str, object]]] = None

    def tool_calls(self) -> List[Tuple[str, Dict[str, object]]]:
        return [(t.tool_name, t.arguments) for t in self.turns if t.tool_name]


def _tool_prompt(tool: ExpertTool, arguments: Dict[str, object], question: str) -> str:
    """The text we actually send the dispatched tool, framed by its arg schema."""
    for key in ("input", "query", "code"):
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return question


def _run_unified_rollout_inner(
    question: str,
    tools: List[ExpertTool],
    *,
    call_orchestrator: Callable[
        ..., Tuple[str, List[Tuple[str, Dict[str, object]]], int, int]
    ],
    dispatch: Callable[[ExpertTool, Dict[str, object]], Tuple[str, float, int, bool]],
    max_turns: int = 50,
    system: str = RL_ORCHESTRATOR_SYS,
    anonymize: bool = False,
) -> UnifiedRollout:
    """Drive the faithful unified-tool rollout for one task.

    ``anonymize``: replace each model expert with an opaque random label, a
    uniform description and no cost line, shuffled — so the policy can't route on
    a model's name/position/cost (which we found dominate the choice). The
    anon->real mapping is returned on the rollout for offline analysis.
    """
    anon_map: Optional[Dict[str, str]] = None
    if anonymize:
        tools, anon_map = anonymize_tools(tools, random.Random())
    specs = build_tool_specs(tools)
    by_name = tools_by_name(tools)

    # Proper multi-turn conversation (NOT a flattened user blob): the orchestrator
    # sees its own calls as `assistant` turns and each observation as a `tool`
    # turn, so it can tell a tool result from user input and doesn't re-derive the
    # whole problem every turn. This mirrors the serialized SFT format exactly.
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Problem: {question}"},
    ]
    turns: List[UnifiedTurn] = []
    cost = 0.0
    tokens = 0
    n_tool_calls = 0
    parse_failures = 0
    nudges = 0
    empty_input_nudges = 0
    final_answer = ""

    for _ in range(max_turns):
        text, tool_calls, p_tok, c_tok = call_orchestrator(messages, specs)
        tokens += int(p_tok) + int(c_tok)

        if not tool_calls:
            # Enforce the "MUST delegate to a model" rule: if the orchestrator
            # tries to answer before ANY tool call, nudge it to route instead of
            # accepting a solve-it-yourself answer (which reject-sampling drops).
            if n_tool_calls == 0 and nudges < 2:
                nudges += 1
                messages.append({"role": "assistant", "content": text or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Make progress by delegating a concrete sub-question to one of the "
                            "models now via a <tool_call>."
                        ),
                    }
                )
                continue
            # No tool call -> the orchestrator is answering. Terminate.
            final_answer = (text or "").strip()
            turns.append(UnifiedTurn(reasoning=text or "", tool_name=None))
            messages.append({"role": "assistant", "content": text or ""})
            break

        name, arguments = tool_calls[0]
        if name not in by_name:
            parse_failures += 1
            messages.append({"role": "assistant", "content": text or ""})
            messages.append(
                {
                    "role": "user",
                    "content": f"[invalid tool {name!r} — choose one from the provided tool list]",
                }
            )
            if parse_failures >= 2:
                final_answer = (text or "").strip()
                break
            continue

        tool = by_name[name]
        # Empty-input guard: the small orchestrator often emits a <tool_call> with
        # a blank/missing input on harder multi-turn tasks. Dispatching it returns
        # a "no input provided" error observation that poisons the whole (often
        # otherwise-correct) trajectory — the dominant clean-yield killer on hard
        # tasks. Instead, nudge the model to resend WITH input and drop the
        # malformed turn (don't record it), so it never enters the training data.
        if tool.kind == "model" or tool.backend_type != "openjarvis-tool":
            _has_input = any(
                isinstance(arguments.get(k), str) and arguments.get(k).strip()
                for k in ("input", "query", "code")
            )
            if not _has_input and empty_input_nudges < 3:
                empty_input_nudges += 1
                messages.append({"role": "assistant", "content": text or ""})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your call to {name} had an empty 'input'. Resend the "
                            "<tool_call> with a non-empty 'input' field containing the "
                            "concrete sub-question to delegate."
                        ),
                    }
                )
                continue
        obs, dcost, dtok, _is_local = dispatch(tool, arguments)
        cost += float(dcost)
        tokens += int(dtok)
        n_tool_calls += 1
        turns.append(
            UnifiedTurn(
                reasoning=text or "",
                tool_name=name,
                arguments=dict(arguments),
                observation=obs,
            )
        )
        # The model's own action as an assistant turn (the <tool_call> tag in
        # content, matching the SFT serialization), then the observation as a
        # distinct `tool` turn the model reads as a tool response.
        call_content = text or ""
        if "<tool_call>" not in call_content:
            call_content = (
                call_content + "\n" + tool_call_tag(name, arguments)
            ).strip()
        messages.append({"role": "assistant", "content": call_content})
        obs_text = obs or ""
        if len(obs_text) > _OBS_CAP:
            obs_text = obs_text[:_OBS_CAP] + "\n…[truncated]"
        messages.append({"role": "tool", "name": name, "content": obs_text})
        if n_tool_calls >= _SOFT_CALL_CAP:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You now have enough information from the models. Do NOT call any "
                        "more tools — reply with your FINAL_ANSWER line only."
                    ),
                }
            )
        _trim_history(messages)
    else:
        # Hit max_turns with no explicit answer: use the last observation/text.
        final_answer = (
            (turns[-1].observation or turns[-1].reasoning).strip() if turns else ""
        )

    return UnifiedRollout(
        turns=turns,
        final_answer=final_answer,
        cost_usd=cost,
        tokens=tokens,
        num_tool_calls=n_tool_calls,
        parse_failures=parse_failures,
        anon_map=anon_map,
        tool_specs=specs,
    )


def run_unified_rollout(
    question: str,
    tools: List[ExpertTool],
    *,
    call_orchestrator: Callable[
        ..., Tuple[str, List[Tuple[str, Dict[str, object]]], int, int]
    ],
    dispatch: Callable[[ExpertTool, Dict[str, object]], Tuple[str, float, int, bool]],
    max_turns: int = 50,
    system: str = RL_ORCHESTRATOR_SYS,
    anonymize: bool = False,
) -> UnifiedRollout:
    """One ToolOrchestra rollout = one Braintrust trace. Opens the root span,
    runs the loop (orchestrator turns + expert/tool dispatches nest inside as
    child spans), then logs the final answer + cost/tokens. No-op when tracing
    is disabled (see :mod:`.tracing`)."""
    _run_meta, _run_tags = run_context()
    _fields = dict(
        input={"question": question},
        metadata={
            "max_turns": max_turns,
            "anonymize": anonymize,
            "n_tools": len(tools),
            **_run_meta,
        },
    )
    if _run_tags:
        _fields["tags"] = _run_tags
    with span("toolorchestra.rollout", span_type="task", **_fields) as _s:
        roll = _run_unified_rollout_inner(
            question,
            tools,
            call_orchestrator=call_orchestrator,
            dispatch=dispatch,
            max_turns=max_turns,
            system=system,
            anonymize=anonymize,
        )
        _s.log(
            output=roll.final_answer,
            metrics={
                "cost_usd": roll.cost_usd,
                "tokens": roll.tokens,
                "num_tool_calls": roll.num_tool_calls,
                "parse_failures": roll.parse_failures,
            },
            metadata={
                "n_experts_available": len(roll.anon_map or {}),
                "answered": bool(roll.final_answer),
                # label -> real model, so every anonymized route span in this
                # trace can be decoded back to the model that actually ran.
                "anon_map": roll.anon_map or {},
            },
        )
        return roll


def tool_call_tag(name: str, arguments: Dict[str, object]) -> str:
    """Render a tool call as the ``<tool_call>{...}</tool_call>`` text the model emits."""
    return (
        f"<tool_call>{json.dumps({'name': name, 'arguments': arguments})}</tool_call>"
    )


__all__ = [
    "RL_ORCHESTRATOR_SYS",
    "UnifiedRollout",
    "UnifiedTurn",
    "build_system_prompt",
    "run_unified_rollout",
    "tool_call_tag",
]
