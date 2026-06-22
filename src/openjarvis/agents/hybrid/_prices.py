"""Cloud-model pricing + per-family quirks for hybrid paradigm agents.

Ported verbatim from ``hybrid-local-cloud-compute/prices.py``. Kept as a
sibling to the agents rather than merged into ``engine/cloud.py``'s PRICING
on purpose: the hybrid harness is the authoritative cost reference for the
n=500 numbers in ``hybrid-local-cloud-compute/docs/results.md`` and we want
the OpenJarvis ports to charge identically.
"""

from __future__ import annotations

# USD per million tokens, (input, output). Local models = 0.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-7":             (5.00, 25.0),
    "claude-sonnet-4-6":           (3.00, 15.0),
    "claude-haiku-4-5":            (1.00, 5.00),
    "claude-haiku-4-5-20251001":   (1.00, 5.00),
    "gpt-5.5":                     (5.00, 30.0),
    "gpt-5":                       (1.25, 10.0),
    "gpt-5-mini":                  (0.25, 2.00),
    "gpt-5-mini-2025-08-07":       (0.25, 2.00),
    "gpt-4o":                      (0.15, 0.60),
    # Gemini Developer API prices (USD per 1M tokens). Pro models use tiered
    # pricing above 200K prompt tokens; GAIA prompts stay under that tier, so
    # charge the low-context standard rate.
    "gemini-3.1-pro-preview":       (2.00, 12.0),
    "gemini-3.1-pro-preview-customtools": (2.00, 12.0),
    "gemini-2.5-pro":              (1.25, 10.0),
    "gemini-2.5-flash":            (0.30, 2.50),
    "gemini-2.5-flash-lite":       (0.10, 0.40),
    # OpenRouter slugs (used by toolorchestra paper-match pool).
    # Prices are OpenRouter list (USD/1M tokens), 2026-05 snapshot.
    "qwen/qwen-2.5-coder-32b-instruct":  (0.08, 0.18),
    "qwen/qwen3-32b":                    (0.10, 0.30),
    "meta-llama/llama-3.3-70b-instruct": (0.13, 0.39),
}

# Models whose API rejects an explicit `temperature` param — callers should
# omit it for any model whose name starts with one of these prefixes.
NO_TEMP_PREFIXES: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-sonnet-4-7",
    "claude-haiku-4-7",
)


def cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD cost for one call. Unknown models price at 0 (e.g. local vLLM)."""
    pi, po = PRICES.get(model, (0.0, 0.0))
    return (prompt_tokens / 1_000_000) * pi + (completion_tokens / 1_000_000) * po


def supports_temperature(model: str) -> bool:
    return not model.startswith(NO_TEMP_PREFIXES)


def is_gpt5_family(model: str) -> bool:
    """GPT-5 series requires ``max_completion_tokens`` and forced temp=1."""
    return model.startswith("gpt-5")


def is_reasoning_model(model: str) -> bool:
    """Models that consume the output-token budget on hidden chain-of-thought
    before emitting visible answer text. At max_tokens=4096 these silently
    truncate with empty answers on GAIA (26/100 GPT-5, 18/100 Gemini Pro)."""
    m = (model or "").lower()
    return (
        is_gpt5_family(model)
        or "gemini-2.5-pro" in m
        or "gemini-3.1-pro" in m
    )


def default_max_output_tokens(model: str) -> int:
    """Sane default for ``max_tokens`` per cloud call. Reasoning models get
    a larger budget so their hidden thinking doesn't crowd out the answer."""
    return 16384 if is_reasoning_model(model) else 4096
