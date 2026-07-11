"""Slot -> worker expert mapping for ToolOrchestraAgent."""

from __future__ import annotations

from typing import Any, Dict, Optional

# Default model used when an `anthropic-web-search` entry omits `model`.
_DEFAULT_WEB_SEARCH_MODEL = "claude-haiku-4-5"

# Map the orchestrator's `model` slot to a concrete OpenJarvis worker spec.
# Tiers ranked by the upstream tools.json table (`*-1` = frontier,
# `*-2` = mid, `*-3` = local). math-1 / math-2 collapse onto the same
# tiers since we don't have Qwen-Math served.
#
# Each entry is a callable `(local_model, local_endpoint, cloud_model) -> worker_dict`
# so the substitution is deferred until we know the cell's resolved local/cloud
# pair. Worker dicts share the schema validated by `_resolve_worker_pool`.


def _expert_for(
    slot: str,
    local_model: Optional[str],
    local_endpoint: Optional[str],
    cloud_model: str,
    cloud_endpoint: str = "anthropic",
) -> Dict[str, Any]:
    """Map an upstream model slot (`answer-1`, `search-3`, …) to a worker spec.

    Routing policy:
      - `*-1` (frontier tier)  -> cloud (`cloud_model`), wtype keyed off
                                  `cloud_endpoint` ("anthropic"/"openai"/"gemini")
      - `*-2` (mid tier)       -> cloud `gpt-5-mini` (matches the paper's
                                  cost tier for mid OpenAI calls)
      - `*-3` (local tier)     -> local vLLM (`local_model`)
      - `answer-math-*`        -> same tiers as the numeric suffix
      - `search-*`             -> provider-native web search when the cloud
                                  endpoint supports it; otherwise Anthropic
    """
    if slot.startswith("search"):
        ep = (cloud_endpoint or "anthropic").lower()
        if ep == "openai":
            return {
                "name": f"search:{slot}",
                "type": "openai-web-search",
                "model": cloud_model,
            }
        if ep == "gemini":
            return {
                "name": f"search:{slot}",
                "type": "gemini-web-search",
                "model": cloud_model,
            }
        return {
            "name": f"search:{slot}",
            "type": "anthropic-web-search",
            "model": _DEFAULT_WEB_SEARCH_MODEL,
        }
    if slot.endswith("-1") or slot.endswith("-math-1"):
        ep = (cloud_endpoint or "anthropic").lower()
        if ep not in ("anthropic", "openai", "gemini"):
            ep = "anthropic"
        return {
            "name": f"frontier:{slot}",
            "type": ep,
            "model": cloud_model,
        }
    if slot.endswith("-2") or slot.endswith("-math-2"):
        return {
            "name": f"mid:{slot}",
            "type": "openai",
            "model": "gpt-5-mini",
        }
    # `*-3` / `*-4` collapse to local vLLM (paper uses Qwen3-32B etc.;
    # we substitute whatever local model the cell wired up).
    if local_model and local_endpoint:
        return {
            "name": f"local:{slot}",
            "type": "vllm",
            "model": local_model,
            "base_url": local_endpoint,
        }
    # Fallback if no local — gpt-5-mini.
    return {
        "name": f"mid-fallback:{slot}",
        "type": "openai",
        "model": "gpt-5-mini",
    }


# ============================================================================
# Paper-match expert mapping (2026-05-19).
# ============================================================================
# Maps the orchestrator's `model` slot to a paper-match worker spec. Differs
# from `_expert_for` in that it pulls in OpenRouter-hosted code/math/generalist
# models and routes `search` through Tavily, while `enhance_reasoning` is
# expected to produce code that the caller pipes through a Modal sandbox
# (handled at dispatch time, not here).
#
# Slot map (paper-faithful where we can; substitutions noted in toolorchestra
# paper-match docs `docs/26.5.19/toolorchestra-papermatch.md`):
#
#   reasoner-1 -> GPT-5 (frontier reasoner)
#   reasoner-2 -> GPT-5-mini (mid)
#   reasoner-3 -> local Qwen (Orchestrator-8B endpoint also serves this)
#   answer-1   -> GPT-5
#   answer-2   -> GPT-5-mini
#   answer-3   -> Llama-3.3-70B (OpenRouter, generalist tier-3 per spec)
#   answer-4   -> local Qwen
#   answer-math-1 -> Qwen-2.5-Coder-32B via OpenRouter
#                    (paper uses Qwen-2.5-Math-72B; not on OpenRouter — see doc)
#   answer-math-2 -> Qwen-2.5-Coder-32B via OpenRouter
#                    (paper uses Qwen-2.5-Math-7B; not on OpenRouter — see doc)
#   search-*   -> Tavily search (paper)
#
# `enhance_reasoning` is dispatched through the coder specialist regardless of
# slot tier — the orchestrator emits one of `reasoner-{1,2,3}` and the caller
# routes the same way in all three cases, then optionally extracts a python
# code block and execs it in Modal. (We keep the slot-aware routing inside the
# `reasoner-*` map above for parity, but the `enhance_reasoning` tool itself
# pins the coder regardless. See `_run_rl_paper` dispatch.)

_PAPER_CODER_OPENROUTER = "qwen/qwen-2.5-coder-32b-instruct"
_PAPER_GENERALIST_TIER3_OPENROUTER = "meta-llama/llama-3.3-70b-instruct"


def _paper_expert_for(
    slot: str,
    local_model: Optional[str],
    local_endpoint: Optional[str],
    cloud_model: str,
    cloud_endpoint: str = "openai",
) -> Dict[str, Any]:
    """Paper-match counterpart of ``_expert_for``.

    Differs from ``_expert_for``:
      - Search slots go to ``tavily-search`` (not Anthropic web_search).
      - Tier-3 generalist answer (``answer-3``) routes to Llama-3.3-70B via
        OpenRouter rather than collapsing onto the local vLLM.
      - Math slots route to the OpenRouter code specialist (Qwen-2.5-Coder-32B)
        as a substitute for the unavailable Qwen-2.5-Math-{72B,7B}.
      - ``reasoner-1`` / ``answer-1`` route to GPT-5 by default (paper).
    """
    if slot.startswith("search"):
        return {
            "name": f"tavily:{slot}",
            "type": "tavily-search",
            "model": "tavily",
        }
    if slot in ("answer-math-1", "answer-math-2"):
        return {
            "name": f"math-coder:{slot}",
            "type": "openrouter",
            "model": _PAPER_CODER_OPENROUTER,
        }
    if slot == "answer-3":
        return {
            "name": f"generalist-llama:{slot}",
            "type": "openrouter",
            "model": _PAPER_GENERALIST_TIER3_OPENROUTER,
        }
    if slot.endswith("-1"):
        # Tier-1 frontier reasoner / answer — paper uses GPT-5.
        return {
            "name": f"frontier:{slot}",
            "type": "openai",
            "model": "gpt-5",
        }
    if slot.endswith("-2"):
        return {
            "name": f"mid:{slot}",
            "type": "openai",
            "model": "gpt-5-mini",
        }
    # `*-3` / `*-4` collapse onto the local vLLM (the orchestrator endpoint
    # also serves the local Qwen for the rare local-tier slot).
    if local_model and local_endpoint:
        return {
            "name": f"local:{slot}",
            "type": "vllm",
            "model": local_model,
            "base_url": local_endpoint,
        }
    return {
        "name": f"mid-fallback:{slot}",
        "type": "openai",
        "model": "gpt-5-mini",
    }
