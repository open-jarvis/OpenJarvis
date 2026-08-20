"""Tests for the extended model catalog -- all new ModelSpec entries."""

from __future__ import annotations

import pytest

from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import ModelSpec
from openjarvis.intelligence.model_catalog import (
    BUILTIN_MODELS,
    merge_discovered_models,
    register_builtin_models,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_spec(model_id: str) -> ModelSpec:
    """Lookup a spec from the BUILTIN_MODELS list (not registry)."""
    for spec in BUILTIN_MODELS:
        if spec.model_id == model_id:
            return spec
    raise KeyError(model_id)


# ---------------------------------------------------------------------------
# Local models
# ---------------------------------------------------------------------------


class TestLocalModelSpecs:
    """Verify every new local model has correct fields."""

    def test_gpt_oss_120b_model_id(self) -> None:
        spec = _get_spec("gpt-oss:120b")
        assert spec.model_id == "gpt-oss:120b"

    def test_gpt_oss_120b_params(self) -> None:
        spec = _get_spec("gpt-oss:120b")
        assert spec.parameter_count_b == 117.0
        assert spec.active_parameter_count_b == 5.1

    def test_gpt_oss_120b_context(self) -> None:
        spec = _get_spec("gpt-oss:120b")
        assert spec.context_length == 131072

    def test_gpt_oss_120b_engines(self) -> None:
        spec = _get_spec("gpt-oss:120b")
        assert "vllm" in spec.supported_engines
        assert "ollama" in spec.supported_engines

    def test_gpt_oss_120b_architecture(self) -> None:
        spec = _get_spec("gpt-oss:120b")
        assert spec.metadata["architecture"] == "moe"

    def test_qwen3_8b_model_id(self) -> None:
        spec = _get_spec("qwen3:8b")
        assert spec.model_id == "qwen3:8b"

    def test_qwen3_8b_params(self) -> None:
        spec = _get_spec("qwen3:8b")
        assert spec.parameter_count_b == 8.2

    def test_qwen3_8b_context(self) -> None:
        spec = _get_spec("qwen3:8b")
        assert spec.context_length == 32768

    def test_qwen3_8b_engines(self) -> None:
        spec = _get_spec("qwen3:8b")
        for e in ("vllm", "ollama", "llamacpp", "sglang"):
            assert e in spec.supported_engines

    def test_qwen3_8b_architecture(self) -> None:
        spec = _get_spec("qwen3:8b")
        assert spec.metadata["architecture"] == "dense"

    def test_glm_47_flash_params(self) -> None:
        spec = _get_spec("glm-4.7-flash")
        assert spec.parameter_count_b == 30.0
        assert spec.active_parameter_count_b == 3.0

    def test_glm_47_flash_context(self) -> None:
        spec = _get_spec("glm-4.7-flash")
        assert spec.context_length == 131072

    def test_glm_47_flash_engines(self) -> None:
        spec = _get_spec("glm-4.7-flash")
        assert "vllm" in spec.supported_engines
        assert "sglang" in spec.supported_engines

    def test_trinity_mini_params(self) -> None:
        spec = _get_spec("trinity-mini")
        assert spec.parameter_count_b == 26.0
        assert spec.active_parameter_count_b == 3.0

    def test_trinity_mini_context(self) -> None:
        spec = _get_spec("trinity-mini")
        assert spec.context_length == 128000

    def test_trinity_mini_engines(self) -> None:
        spec = _get_spec("trinity-mini")
        assert "vllm" in spec.supported_engines
        assert "llamacpp" in spec.supported_engines


# ---------------------------------------------------------------------------
# Cloud models
# ---------------------------------------------------------------------------


class TestCloudModelSpecs:
    """Verify every new cloud model has correct fields."""

    def test_gpt_5_mini_provider(self) -> None:
        spec = _get_spec("gpt-5-mini")
        assert spec.provider == "openai"
        assert spec.requires_api_key is True

    def test_gpt_5_mini_context(self) -> None:
        spec = _get_spec("gpt-5-mini")
        assert spec.context_length == 400000

    def test_gpt_5_mini_pricing(self) -> None:
        spec = _get_spec("gpt-5-mini")
        assert spec.metadata["pricing_input"] == pytest.approx(0.25)
        assert spec.metadata["pricing_output"] == pytest.approx(2.00)

    def test_claude_opus_4_6_provider(self) -> None:
        spec = _get_spec("claude-opus-4-6")
        assert spec.provider == "anthropic"
        assert spec.requires_api_key is True

    def test_claude_opus_4_6_context(self) -> None:
        spec = _get_spec("claude-opus-4-6")
        assert spec.context_length == 200000

    def test_claude_sonnet_4_6_provider(self) -> None:
        spec = _get_spec("claude-sonnet-4-6")
        assert spec.provider == "anthropic"
        assert spec.requires_api_key is True

    def test_claude_haiku_4_5_provider(self) -> None:
        spec = _get_spec("claude-haiku-4-5")
        assert spec.provider == "anthropic"
        assert spec.requires_api_key is True

    def test_claude_haiku_4_5_pricing(self) -> None:
        spec = _get_spec("claude-haiku-4-5")
        assert spec.metadata["pricing_input"] == pytest.approx(1.00)
        assert spec.metadata["pricing_output"] == pytest.approx(5.00)

    def test_gemini_25_pro_provider(self) -> None:
        spec = _get_spec("gemini-2.5-pro")
        assert spec.provider == "google"
        assert spec.requires_api_key is True
        assert spec.context_length == 1000000

    def test_gemini_25_flash_provider(self) -> None:
        spec = _get_spec("gemini-2.5-flash")
        assert spec.provider == "google"
        assert spec.context_length == 1000000

    def test_gemini_3_pro_provider(self) -> None:
        spec = _get_spec("gemini-3-pro")
        assert spec.provider == "google"
        assert spec.requires_api_key is True

    def test_gemini_3_flash_provider(self) -> None:
        spec = _get_spec("gemini-3-flash")
        assert spec.provider == "google"
        assert spec.requires_api_key is True

    def test_gemini_3_pro_pricing(self) -> None:
        spec = _get_spec("gemini-3-pro")
        assert spec.metadata["pricing_input"] == pytest.approx(2.00)
        assert spec.metadata["pricing_output"] == pytest.approx(12.00)


# ---------------------------------------------------------------------------
# Discovery / invariant tests
# ---------------------------------------------------------------------------


class TestQwen35ModelSpecs:
    """Verify Qwen3.5 MoE model entries."""

    def test_qwen35_2b(self) -> None:
        spec = _get_spec("qwen3.5:2b")
        assert spec.parameter_count_b == 2.0
        assert spec.active_parameter_count_b == 0.4
        assert spec.context_length == 131072
        assert spec.provider == "alibaba"
        assert spec.metadata["architecture"] == "moe"
        for e in ("ollama", "vllm", "llamacpp", "sglang"):
            assert e in spec.supported_engines

    def test_qwen35_9b(self) -> None:
        spec = _get_spec("qwen3.5:9b")
        assert spec.parameter_count_b == 9.0
        assert spec.active_parameter_count_b == 1.5
        assert spec.context_length == 131072

    def test_qwen35_27b(self) -> None:
        spec = _get_spec("qwen3.5:27b")
        assert spec.parameter_count_b == 27.0
        assert spec.active_parameter_count_b == 3.0

    def test_qwen35_35b(self) -> None:
        spec = _get_spec("qwen3.5:35b")
        assert spec.parameter_count_b == 35.0
        assert spec.active_parameter_count_b == 3.0
        assert "llamacpp" not in spec.supported_engines

    def test_qwen35_122b(self) -> None:
        spec = _get_spec("qwen3.5:122b")
        assert spec.parameter_count_b == 122.0
        assert spec.active_parameter_count_b == 10.0
        assert spec.min_vram_gb == 70.0

    def test_qwen35_397b(self) -> None:
        spec = _get_spec("qwen3.5:397b")
        assert spec.parameter_count_b == 397.0
        assert spec.active_parameter_count_b == 17.0
        assert spec.min_vram_gb == 220.0
        assert "ollama" not in spec.supported_engines
        assert "vllm" in spec.supported_engines


class TestIBMGraniteModelSpecs:
    """Verify IBM Granite model entries."""

    def test_granite33_8b(self) -> None:
        spec = _get_spec("granite3.3:8b")
        assert spec.parameter_count_b == 8.0
        assert spec.context_length == 128000
        assert spec.provider == "ibm"
        assert spec.metadata["architecture"] == "dense"
        assert "ollama" in spec.supported_engines
        assert "vllm" in spec.supported_engines

    def test_granite40_micro(self) -> None:
        spec = _get_spec("granite4.0-micro")
        assert spec.parameter_count_b == 3.0
        assert spec.context_length == 128000
        assert spec.provider == "ibm"
        assert spec.metadata["architecture"] == "dense"

    def test_granite40_h_small(self) -> None:
        spec = _get_spec("granite4.0-h-small")
        assert spec.parameter_count_b == 32.0
        assert spec.active_parameter_count_b == 9.0
        assert spec.context_length == 128000
        assert spec.provider == "ibm"
        assert spec.metadata["architecture"] == "moe"

    def test_granite_models_have_url(self) -> None:
        for mid in ("granite3.3:8b", "granite4.0-micro", "granite4.0-h-small"):
            spec = _get_spec(mid)
            assert "url" in spec.metadata
            assert "ibm.com" in spec.metadata["url"]


class TestModelDiscovery:
    def test_local_models_have_engine_compat(self) -> None:
        """Every local model has at least one supported engine."""
        for spec in BUILTIN_MODELS:
            if not spec.requires_api_key:
                assert len(spec.supported_engines) >= 1, (
                    f"{spec.model_id} has no supported engines"
                )

    def test_cloud_models_require_api_key(self) -> None:
        """All cloud models have requires_api_key=True."""
        cloud_ids = {
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-5-mini",
            "gpt-5-mini-2025-08-07",
            "claude-sonnet-4-20250514",
            "claude-opus-4-20250514",
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-haiku-4-5",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3-pro",
            "gemini-3-flash",
        }
        for spec in BUILTIN_MODELS:
            if spec.model_id in cloud_ids:
                assert spec.requires_api_key is True, (
                    f"{spec.model_id} should require API key"
                )

    def test_moe_models_have_active_params(self) -> None:
        """MoE models have active_parameter_count_b set."""
        moe_ids = {
            "gpt-oss:120b",
            "glm-4.7-flash",
            "trinity-mini",
            "qwen3.5:2b",
            "qwen3.5:9b",
            "qwen3.5:27b",
            "qwen3.5:35b",
            "qwen3.5:122b",
            "qwen3.5:397b",
            "granite4.0-h-small",
        }
        for spec in BUILTIN_MODELS:
            if spec.model_id in moe_ids:
                assert spec.active_parameter_count_b is not None
                assert spec.active_parameter_count_b > 0

    def test_all_models_have_context_length(self) -> None:
        """No model has zero or None context length."""
        for spec in BUILTIN_MODELS:
            assert spec.context_length > 0, (
                f"{spec.model_id} has context_length={spec.context_length}"
            )

    def test_merge_discovered_preserves_new(self) -> None:
        """merge_discovered_models works for all new model IDs."""
        register_builtin_models()
        new_ids = [
            "gpt-oss:120b",
            "glm-4.7-flash",
            "trinity-mini",
            "gpt-5-mini",
            "claude-opus-4-6",
            "gemini-3-pro",
        ]
        # Merging known IDs should not raise
        merge_discovered_models("vllm", new_ids)
        for mid in new_ids:
            assert ModelRegistry.contains(mid)

    def test_register_builtin_is_idempotent(self) -> None:
        """Calling register_builtin_models twice does not raise."""
        register_builtin_models()
        register_builtin_models()  # should not raise
        assert ModelRegistry.contains("qwen3:8b")
