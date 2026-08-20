"""Model-alias pool for the SkillOrchestra eval orchestrator.

The original SkillOrchestra (``config/models.py`` + ``config/pool_config.json``)
maps stage aliases — ``search-1/2/3``, ``reasoner-1/2/3``,
``answer-1/2/3/4``, ``answer-math-1/2`` — onto a pool of 6+ models served
via SGLang. OpenJarvis runs a 2-model world (one local vLLM student + one
cloud model), so the default pool *collapses* the alias tiers onto
local/cloud by cost rank: the dearer ``-1`` / ``-2`` aliases (and
``answer-math-1``) route to the cloud model, the cheaper ``-3`` / ``-4``
aliases (and ``answer-math-2``) route to the local model. This mirrors
``stage_router.WeightedAverageStrategy.COST_TIERS``.

A cell overrides any alias through ``method_cfg.model_pool``::

    method_cfg.model_pool = {
        "search-1" = { model = "claude-opus-4-7", endpoint = "anthropic" },
        "search-3" = { model = "Qwen/Qwen3.5-27B-FP8", endpoint = "http://localhost:8001/v1" },
        ...
    }

``endpoint`` is ``anthropic`` / ``openai`` / ``gemini`` for a cloud model,
or an OpenAI-compatible base URL (``http://...``) for a local vLLM model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Stage -> ordered alias list. Matches stage_router._get_models_for_stage
# and orchestration/tools.json exactly.
STAGE_ALIASES: Dict[str, List[str]] = {
    "search": ["search-1", "search-2", "search-3"],
    "reasoning": ["reasoner-1", "reasoner-2", "reasoner-3"],
    "answer": [
        "answer-1",
        "answer-2",
        "answer-3",
        "answer-4",
        "answer-math-1",
        "answer-math-2",
    ],
}

# Every alias the orchestrator can emit, flat.
ALL_ALIASES: List[str] = [a for aliases in STAGE_ALIASES.values() for a in aliases]

# Default tier: which aliases collapse onto the cloud model vs the local
# model. Dearer ``-1``/``-2`` (+ answer-math-1) -> cloud; cheaper -> local.
_CLOUD_ALIASES = {
    "search-1",
    "search-2",
    "reasoner-1",
    "reasoner-2",
    "answer-1",
    "answer-2",
    "answer-math-1",
}


@dataclass
class ModelSpec:
    """A resolved alias: which concrete model on which endpoint."""

    alias: str
    model: str
    endpoint: str  # "anthropic" | "openai" | "gemini" | "http://..."
    kind: str  # "cloud" | "local"

    @property
    def is_local(self) -> bool:
        return self.kind == "local"


def _endpoint_kind(endpoint: str) -> str:
    return "local" if endpoint.startswith("http") else "cloud"


def build_pool(
    *,
    local_model: Optional[str],
    local_endpoint: Optional[str],
    cloud_model: str,
    cloud_endpoint: str,
    overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> Dict[str, ModelSpec]:
    """Resolve every alias to a :class:`ModelSpec`.

    Default mapping collapses the alias tiers onto the cell's local/cloud
    pair; ``overrides`` (from ``method_cfg.model_pool``) wins per alias.
    """
    pool: Dict[str, ModelSpec] = {}
    have_local = bool(local_model and local_endpoint)
    for alias in ALL_ALIASES:
        to_cloud = alias in _CLOUD_ALIASES or not have_local
        if to_cloud:
            pool[alias] = ModelSpec(alias, cloud_model, cloud_endpoint, "cloud")
        else:
            pool[alias] = ModelSpec(
                alias,
                local_model,
                local_endpoint,
                "local",  # type: ignore[arg-type]
            )

    for alias, spec in (overrides or {}).items():
        if alias not in pool:
            continue
        model = spec.get("model")
        endpoint = spec.get("endpoint")
        if not model or not endpoint:
            continue
        pool[alias] = ModelSpec(alias, model, endpoint, _endpoint_kind(endpoint))
    return pool


def call_alias(
    agent: Any,
    spec: ModelSpec,
    *,
    user: str,
    system: Optional[str] = None,
    max_tokens: int = 8000,
    temperature: float = 1.0,
) -> Tuple[str, int, int, float]:
    """Single text-generation call through a resolved alias.

    Returns ``(text, tokens_in, tokens_out, cost_usd)``. Dispatches to the
    right :class:`LocalCloudAgent` SDK helper by endpoint. ``temperature``
    defaults to 1.0 — the value the original ``call_tool`` uses for every
    worker call (``eval_frames.py:657``).
    """
    if spec.is_local:
        text, p, c = agent._call_vllm(
            spec.model,
            spec.endpoint,
            user=user,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            enable_thinking=False,
            trace_role="local",
        )
        return text, p, c, 0.0

    ep = spec.endpoint.lower()
    if ep == "anthropic":
        text, p, c, _ = agent._call_anthropic(
            spec.model,
            user=user,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            trace_role="cloud",
        )
    elif ep == "openai":
        text, p, c = agent._call_openai(
            spec.model,
            user=user,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            trace_role="cloud",
        )
    elif ep == "gemini":
        text, p, c = agent._call_gemini(
            spec.model,
            user=user,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            trace_role="cloud",
        )
    else:
        raise ValueError(f"unsupported pool endpoint: {spec.endpoint!r}")
    return text, p, c, agent.cost_usd(spec.model, p, c)
