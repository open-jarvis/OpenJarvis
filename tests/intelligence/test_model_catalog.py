"""Tests for the built-in model catalog."""

from __future__ import annotations

from openjarvis.core.registry import ModelRegistry
from openjarvis.core.types import ModelSpec
from openjarvis.intelligence.model_catalog import (
    BUILTIN_MODELS,
    merge_discovered_models,
    register_builtin_models,
    resolve_model_id_for_engine,
)


class TestRegisterBuiltinModels:
    def test_registers_all(self) -> None:
        register_builtin_models()
        for spec in BUILTIN_MODELS:
            assert ModelRegistry.contains(spec.model_id)

    def test_does_not_overwrite_existing(self) -> None:
        custom = ModelSpec(
            model_id="qwen3:8b",
            name="Custom Qwen",
            parameter_count_b=99.0,
            context_length=999,
        )
        ModelRegistry.register_value("qwen3:8b", custom)
        register_builtin_models()
        assert ModelRegistry.get("qwen3:8b").name == "Custom Qwen"

    def test_builtins_have_required_fields(self) -> None:
        for spec in BUILTIN_MODELS:
            assert spec.model_id
            assert spec.name
            assert spec.context_length > 0 or spec.requires_api_key


class TestMergeDiscoveredModels:
    def test_merge_new_model(self) -> None:
        merge_discovered_models("ollama", ["new-model:latest"])
        assert ModelRegistry.contains("new-model:latest")
        spec = ModelRegistry.get("new-model:latest")
        assert "ollama" in spec.supported_engines

    def test_merge_existing_not_overwritten(self) -> None:
        register_builtin_models()
        original = ModelRegistry.get("qwen3:8b")
        merge_discovered_models("ollama", ["qwen3:8b"])
        assert ModelRegistry.get("qwen3:8b").name == original.name


class TestResolveModelIdForEngine:
    def test_resolves_mlx_repo(self) -> None:
        assert resolve_model_id_for_engine("qwen3.5:4b", "mlx") == (
            "mlx-community/Qwen3.5-4B-OptiQ-4bit"
        )

    def test_unknown_model_is_unchanged(self) -> None:
        assert resolve_model_id_for_engine("custom/model", "mlx") == "custom/model"

    def test_non_mlx_engine_is_unchanged(self) -> None:
        assert resolve_model_id_for_engine("qwen3.5:4b", "ollama") == "qwen3.5:4b"
