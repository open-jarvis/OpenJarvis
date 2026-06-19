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

import json
from typing import Any, Dict, List

from openjarvis.agents.hybrid.expert_registry import ExpertTool, build_tool_specs
from openjarvis.agents.hybrid.toolorchestra.rollout import (
    UnifiedRollout,
    build_system_prompt,
    tool_call_tag,
)


def _system_prompt(tools: List[ExpertTool]) -> str:
    # Faithful ToolOrchestra system prompt (paper's prepare_sft_data.py format).
    return build_system_prompt(build_tool_specs(tools))


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
        {"role": "system", "content": _system_prompt(tools)},
        {"role": "user", "content": f"Problem: {question}"},
    ]

    for turn in rollout.turns:
        if turn.tool_name is None:
            # Final-answer turn.
            conversations.append({
                "role": "assistant",
                "content": (turn.reasoning or "").rstrip()
                + f"\nFINAL_ANSWER: {rollout.final_answer}",
            })
            continue
        tag = tool_call_tag(turn.tool_name, turn.arguments)
        reasoning = (turn.reasoning or "").rstrip()
        conversations.append({
            "role": "assistant",
            "content": (reasoning + "\n" + tag).strip(),
        })
        conversations.append({
            "role": "tool",
            "name": turn.tool_name,
            "content": turn.observation or "",
        })

    # If the rollout terminated on max_turns (no None turn), append the answer.
    if not rollout.turns or rollout.turns[-1].tool_name is not None:
        conversations.append({
            "role": "assistant",
            "content": f"FINAL_ANSWER: {rollout.final_answer}",
        })

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
        },
    }


__all__ = ["trajectory_to_record"]
