"""Serialize a winning :class:`RenderedEpisode` into a ``conversations`` record.

Output schema matches what
:class:`~openjarvis.learning.intelligence.orchestrator.sft_trainer.OrchestratorSFTDataset`
already consumes::

    {"conversations": [{"role": "system"|"user"|"assistant"|"tool", "content": ...}],
     "paradigm": ..., "reward": ..., "metrics": {...}}

The assistant turns use the canonical THOUGHT/TOOL/INPUT format from
``prompt_registry``; the routing tool encodes the tier the orchestrator chose
(``local_model`` / ``mid_model`` / ``frontier_model`` / ``web_search``).
"""

from __future__ import annotations

from typing import Any, Dict

from openjarvis.learning.intelligence.orchestrator.prompt_registry import (
    build_system_prompt,
)
from openjarvis.learning.intelligence.orchestrator.sft_data.paradigms import (
    RenderedEpisode,
)

# Routing vocabulary the orchestrator learns to emit.
TIER_TOOL = {
    "local": "local_model",
    "mid": "mid_model",
    "frontier": "frontier_model",
    "search": "web_search",
}
ROUTING_TOOLS = ["local_model", "mid_model", "frontier_model", "web_search"]

_SYSTEM_PROMPT = build_system_prompt(ROUTING_TOOLS)


def to_record(rendered: RenderedEpisode, *, reward: float = 0.0) -> Dict[str, Any]:
    """Convert a winning rendering into one SFT JSONL record."""
    ep = rendered.episode
    conversations: list[dict[str, str]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": ep.initial_prompt},
    ]

    n = len(ep.steps)
    for i, (step, tier_key) in enumerate(zip(ep.steps, rendered.step_tiers)):
        tool = TIER_TOOL.get(tier_key, "local_model")
        if step.action.is_final_answer or i == n - 1:
            conversations.append(
                {
                    "role": "assistant",
                    "content": (
                        f"THOUGHT: {step.action.thought}\n"
                        f"TOOL: {tool}\n"
                        f"INPUT: {step.action.tool_input}"
                    ),
                }
            )
            conversations.append(
                {"role": "tool", "name": tool, "content": step.observation.content}
            )
            conversations.append(
                {
                    "role": "assistant",
                    "content": (
                        "THOUGHT: The result answers the task.\n"
                        f"FINAL_ANSWER: {ep.final_answer}"
                    ),
                }
            )
        else:
            conversations.append(
                {
                    "role": "assistant",
                    "content": (
                        f"THOUGHT: {step.action.thought}\n"
                        f"TOOL: {tool}\n"
                        f"INPUT: {step.action.tool_input}"
                    ),
                }
            )
            conversations.append(
                {"role": "tool", "name": tool, "content": step.observation.content}
            )

    return {
        "conversations": conversations,
        "task_id": ep.task_id,
        "paradigm": rendered.paradigm,
        "reward": reward,
        "metrics": {
            "cost_usd": ep.total_cost_usd,
            "energy_joules": ep.total_energy_joules,
            "latency_seconds": ep.total_latency_seconds,
            "tokens": ep.total_tokens,
            "max_power_watts": ep.max_power_watts,
            "num_steps": n,
        },
    }


__all__ = ["ROUTING_TOOLS", "TIER_TOOL", "to_record"]
