"""Serialize a verified unified-tool rollout into an SFT ``conversations`` record.

Output matches what ``OrchestratorSFTDataset`` consumes, and trains the model to
emit the ``<tool_call>{...}</tool_call>`` text form that
``toolorchestra.parsing._parse_rl_tool_call`` already reads back. One record =
one passing trajectory.

Roles: ``system`` (the unified tool catalog), ``user`` (the running ``Problem``
prompt), ``assistant`` (reasoning + a ``<tool_call>`` tag, or the final answer),
``tool`` (the executed observation).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from openjarvis.agents.hybrid.expert_registry import ExpertTool, build_tool_specs
from openjarvis.agents.hybrid.toolorchestra.rollout import (
    _OBS_CAP as _ROLLOUT_OBS_CAP,
    UnifiedRollout,
    build_system_prompt,
    tool_call_tag,
)


def _system_prompt(tools: List[ExpertTool], rollout: UnifiedRollout) -> str:
    # Faithful ToolOrchestra system prompt (paper's prepare_sft_data.py format).
    # Prefer the EXACT specs the policy saw this rollout (anonymized labels when
    # anonymize=True) so the saved <tools> block matches the assistant's
    # <tool_call> tags. Falling back to the real registry here is the bug that
    # leaked real model names+pricing into anonymized records.
    specs = rollout.tool_specs if rollout.tool_specs else build_tool_specs(tools)
    return build_system_prompt(specs)


def _normalize_think(text: str) -> str:
    """Ensure a reasoning block has matched tags. Qwen rollouts routinely yield a
    dangling ``</think>`` with NO opening ``<think>`` (the chat template consumes
    the opener in the prompt, so only the closer survives in the completion). Add
    the opener back so the trained turn is well-formed."""
    t = (text or "").lstrip()
    if "</think>" in t and "<think>" not in t:
        t = "<think>\n" + t
    return t


def _debox(text: str) -> str:
    """Unwrap every ``\\boxed{X}`` -> ``X`` (balanced braces). The format kills
    \\boxed everywhere, but small models keep emitting it in otherwise-correct
    answers — de-box to salvage them rather than reject the whole trajectory."""
    out, i = [], 0
    marker = r"\boxed{"
    while i < len(text):
        j = text.find(marker, i)
        if j == -1:
            out.append(text[i:])
            break
        out.append(text[i:j])
        k = j + len(marker)
        depth, inner = 1, []
        while k < len(text) and depth:
            c = text[k]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            inner.append(c)
            k += 1
        out.append("".join(inner))
        i = k + 1
    return "".join(out)


# Reasoning that PAROTS the training constraint back ("I must call a model per
# my instructions", "this is testing whether I need to route") — the model
# reasoning about its own harness. Never a good target: drop the whole line.
_LEAK_RE = re.compile(
    r"(?im)^.*\b(?:"
    r"the user (?:is|was|wants|has|had|needs|'s|would|will|asked"
    r"|'ve asked|has asked)\b|"
    r"asked me to\b|"  # echoes of an injected nudge turn
    r"make progress by delegat|"
    r"delegat\w+[^\n]*sub-?question|"
    r"(?:to |ask |send .{0,20}to )?one of the models\b|"
    r"instructions?|"  # any self-reference to the rules
    r"requirement|"
    r"at least one (?:model|tool|expert)|"  # "(call|invoke) at least one model"
    r"(?:call|invoke|route to|delegate to|use)\s+(?:a|one|at least one|the)\s+model\b|"
    r"route\s+(?:this|it|that)\b[^\n]{0,40}\bthrough\s+(?:a|one|the)\s+model\b|"
    r"without mentioning (?:any )?(?:tools?|reasoning|meta|steps)|"
    r"in the required format\b|"
    r"based on the (?:model|response|analysis|expert)|"  # response-acknowledgment
    r"the model (?:provided|confirmed|gave|returned|correctly|analy\w+"
    r"|respon\w+|said|indicated|identified)|"
    r"i (?:got|received|have) (?:a |the )?"
    r"(?:comprehensive |clear |good |detailed )?answer\b|"
    r"now i can (?:confidently )?(?:give|provide|state|answer)|"
    r"perfect[!,]|great[!,]|excellent[!,]|"  # narration exclamations
    r"as an orchestrator|"
    r"whose job is to (?:route|delegate|orchestrate)|"
    r"testing whether i (?:need|have|should|must)\b|"
    r"i(?:'m| am)? (?:required|instructed|supposed|expected) to\b"
    r")[^\n]*(?:\n|$)"
)
# A leading task-restatement opener ("The user is asking…") — the format
# explicitly bans this meta-text; drop it when it opens the reasoning.
_META_OPEN_RE = re.compile(
    r"(?is)^\s*(?:the user (?:is|was|wants|has|needs|would|'s)\b[^.\n]*[.\n]+\s*)+"
)


def _scrub_meta(text: str) -> str:
    """Remove harness-leakage lines and a leading 'The user is asking…' meta
    opener from a reasoning block. Both are disallowed by the system prompt, so
    they must not survive into the supervised target. Preserves a leading
    ``<think>`` marker so the block stays well-formed."""
    if not text:
        return text
    think = ""
    body = text
    m = re.match(r"(?is)^\s*(<think>)\s*", body)
    if m:
        think = "<think>\n"
        body = body[m.end() :]
    body = _LEAK_RE.sub("", body)
    body = _META_OPEN_RE.sub("", body).lstrip()
    return (think + body).strip() if think else body.strip()


# Control / special tokens that must never survive into a training target's
# final answer. Three shapes, in order of alternation:
#   1. closed pipe token  — ``<|im_end|>``, ``<|im_start|>``, ``<|eot_id|>``,
#      ``<|end_of_turn|>``, ``<|"|>`` (the stray-quote leak).
#   2. UNCLOSED pipe token — ``<|tool_call>`` (opened with ``<|`` but closed on a
#      bare ``>`` because the decode was cut before the second pipe).
#   3. named angle special tokens — gemma ``<start_of_turn>`` / ``<end_of_turn>``
#      and the sentinel set ``<eos> <bos> <pad> <unk> <s> </s>``.
# Deliberately narrow: only the ``<|...|>`` pipe form and this known name list
# match, so legitimate ``<``/``>`` in math/code (``x < 3 and y > 2``) is left
# untouched.
_CONTROL_TOKEN_RE = re.compile(
    r"<\|[^>]*?\|>"  # closed pipe token
    r"|<\|[^|>]*>"  # unclosed pipe token
    r"|</?(?:start_of_turn|end_of_turn|eos|bos|pad|unk|s)>"  # named angle tokens
)


def _strip_control_tokens(text: str) -> str:
    """Delete residual control/special tokens from an answer so a good answer
    with a stray token is salvaged rather than dropped. Loops (bounded) because
    removing one match can expose a nested/overlapping leftover (e.g.
    ``<|<|im_end|>|>``). Re-strips whitespace at the end."""
    if not text:
        return text
    out = text
    for _ in range(4):
        stripped = _CONTROL_TOKEN_RE.sub("", out)
        if stripped == out:
            break
        out = stripped
    return out.strip()


def _final_answer_block(text: str) -> str:
    """Render the final-answer assistant message with a single clean
    ``FINAL_ANSWER: <value>`` line. De-boxes the answer, strips leaked control
    tokens, and normalizes whatever spelling the model used (``FINALANSWER``,
    ``FINAL ANSWER``, no colon, …) to the exact tag. Keeps the think block at
    most once."""
    text = _debox(_normalize_think((text or "").strip()))
    # Normalize any final-answer marker spelling to the canonical form; take the
    # LAST one as the real answer (idempotent — never emits two tags).
    marks = list(re.finditer(r"(?im)FINAL[_\s]?ANSWER\s*:?", text))
    if marks:
        last = marks[-1]
        answer = _strip_control_tokens(text[last.end() :].strip())
        # Final turn = the bare short answer only. Drop EVERYTHING before
        # FINAL_ANSWER — both the visible "Perfect! Based on the model's response…"
        # narration AND the final-turn <think>, which is just confirmatory
        # "both models agree… I've verified…" fluff. The routing reasoning already
        # lives in the earlier tool-call turns, so nothing of value is lost, and
        # this kills all final-turn narration deterministically (any wording).
        return f"FINAL_ANSWER: {answer}"
    if "</think>" in text:
        # No explicit marker: the answer is whatever follows the final </think>.
        # Drop the think block (same rationale as above) — keep only the answer.
        _, _, answer = text.rpartition("</think>")
        answer = _strip_control_tokens(answer.strip())
        return (
            f"FINAL_ANSWER: {answer}"
            if answer
            else f"FINAL_ANSWER: {_strip_control_tokens(_scrub_meta(text))}"
        )
    return f"FINAL_ANSWER: {_strip_control_tokens(text)}"


def trajectory_to_record(
    task_id: str,
    question: str,
    tools: List[ExpertTool],
    rollout: UnifiedRollout,
    *,
    reward: float = 0.0,
    domain: str = "unknown",
) -> Dict[str, Any]:
    """Convert a passing :class:`UnifiedRollout` into one SFT JSONL record."""
    conversations: List[Dict[str, str]] = [
        {"role": "system", "content": _system_prompt(tools, rollout)},
        {"role": "user", "content": f"Problem: {question}"},
    ]

    for turn in rollout.turns:
        if turn.tool_name is None:
            # Final-answer turn. turn.reasoning is the model's actual output for
            # this turn (which already contains the answer); render it once.
            conversations.append(
                {
                    "role": "assistant",
                    "content": _final_answer_block(
                        turn.reasoning or rollout.final_answer
                    ),
                }
            )
            continue
        tag = tool_call_tag(turn.tool_name, turn.arguments)
        reasoning = _scrub_meta(_normalize_think((turn.reasoning or "").rstrip()))
        conversations.append(
            {
                "role": "assistant",
                "content": (reasoning + "\n" + tag).strip(),
            }
        )
        # Store the observation EXACTLY as the orchestrator saw it — the rollout
        # caps tool output at _OBS_CAP before the model reads it (rollout.py), but
        # this serializer used to store the FULL text. That trained the student on
        # context the teacher never had, and produced monster rows (a 212k-char
        # raw-HTML http_request dump = ~50k tokens of <!DOCTYPE> boilerplate) that
        # then got BEHEADED by the trainer's max-seq. Train on what the policy saw.
        obs = turn.observation or ""
        if len(obs) > _ROLLOUT_OBS_CAP:
            obs = obs[:_ROLLOUT_OBS_CAP] + "\n…[truncated]"
        conversations.append(
            {
                "role": "tool",
                "name": turn.tool_name,
                "content": obs,
            }
        )

    # If the rollout terminated on max_turns (no None turn), append the answer.
    if not rollout.turns or rollout.turns[-1].tool_name is not None:
        conversations.append(
            {
                "role": "assistant",
                "content": _final_answer_block(rollout.final_answer),
            }
        )

    return {
        "conversations": conversations,
        "task_id": task_id,
        "domain": domain,
        "reward": reward,
        "metrics": {
            "cost_usd": rollout.cost_usd,
            "tokens": rollout.tokens,
            "num_tool_calls": rollout.num_tool_calls,
            "num_turns": len(rollout.turns),
            # Present only when experts were anonymized: opaque label -> real
            # tool name, so analysis can recover which model was actually picked.
            **({"anon_map": rollout.anon_map} if rollout.anon_map else {}),
        },
    }


__all__ = ["trajectory_to_record"]
