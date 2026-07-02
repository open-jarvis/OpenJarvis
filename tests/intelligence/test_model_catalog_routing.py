"""Tests for Pass-2 model catalog lane metadata."""

from __future__ import annotations

from openjarvis.core.registry import ModelRegistry
from openjarvis.intelligence.model_catalog import (
    infer_routing_metadata,
    merge_discovered_models,
    register_builtin_models,
)


def test_builtin_router_models_have_lane_metadata() -> None:
    register_builtin_models()
    qwen = ModelRegistry.get("qwen2.5:1.5b")
    llama = ModelRegistry.get("llama3.2:1b")
    assert qwen.metadata.get("routing_lane") == "router_control"
    assert llama.metadata.get("routing_lane") == "router_control"
    assert qwen.metadata.get("stable_json") is True


def test_builtin_openrouter_free_has_free_fallback_lane() -> None:
    register_builtin_models()
    free = ModelRegistry.get("openrouter/free")
    assert free.metadata.get("routing_lane") == "free_fallback"
    assert free.metadata.get("cost_band") == "free"


def test_builtin_code_and_vision_models_have_expected_lanes() -> None:
    register_builtin_models()
    coder = ModelRegistry.get("qwen2.5-coder:7b")
    vision = ModelRegistry.get("openrouter/qwen/qwen3-vl-32b-instruct")
    assert coder.metadata.get("routing_lane") == "code_specialist"
    assert vision.metadata.get("routing_lane") == "multimodal_vision"


def test_infer_routing_metadata_for_premium_and_long_context() -> None:
    premium = infer_routing_metadata("openrouter/deepseek/deepseek-v3.2")
    longctx = infer_routing_metadata("openrouter/meta-llama/llama-4-scout")
    assert premium.get("routing_lane") == "premium_workhorse"
    assert longctx.get("routing_lane") == "long_context_research"


def test_merge_discovered_models_applies_lane_metadata() -> None:
    merge_discovered_models(
        "cloud",
        ["openrouter/free", "openrouter/qwen/qwen3-vl-32b-instruct"],
    )
    free = ModelRegistry.get("openrouter/free")
    vision = ModelRegistry.get("openrouter/qwen/qwen3-vl-32b-instruct")
    assert free.metadata.get("routing_lane") == "free_fallback"
    assert vision.metadata.get("routing_lane") == "multimodal_vision"
