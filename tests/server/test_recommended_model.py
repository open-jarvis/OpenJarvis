"""Tests for /v1/recommended-model endpoint."""

from __future__ import annotations

import pytest

try:
    import fastapi  # noqa: F401

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_recommended_model_picks_second_largest():
    """Should pick the second-largest local model."""
    from openjarvis.server.agent_manager_routes import _pick_recommended_model

    models = ["qwen3.5:0.8b", "qwen3.5:4b", "qwen3.5:9b", "qwen3.5:35b"]
    result = _pick_recommended_model(models)
    assert result["model"] == "qwen3.5:9b"


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_recommended_model_single_model():
    """With only one model, pick it."""
    from openjarvis.server.agent_manager_routes import _pick_recommended_model

    result = _pick_recommended_model(["qwen3.5:4b"])
    assert result["model"] == "qwen3.5:4b"


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_recommended_model_filters_cloud():
    """Cloud models should be excluded from recommendation."""
    from openjarvis.server.agent_manager_routes import _pick_recommended_model

    models = ["qwen3.5:4b", "gpt-4o", "claude-3.5-sonnet", "qwen3.5:9b"]
    result = _pick_recommended_model(models)
    assert result["model"] in ("qwen3.5:4b", "qwen3.5:9b")


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_parse_param_count():
    """Parse parameter counts from model names."""
    from openjarvis.server.agent_manager_routes import _parse_param_count

    assert _parse_param_count("qwen3.5:9b") == 9.0
    assert _parse_param_count("qwen3.5:0.8b") == 0.8
    assert _parse_param_count("qwen3.5:35b") == 35.0
    assert _parse_param_count("gpt-4o") == 0.0


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_recommended_model_skips_embed_only():
    """Embed-only models must never be recommended for chat."""
    from openjarvis.server.agent_manager_routes import _pick_recommended_model

    models = [
        "nomic-embed-text",
        "qwen3.5:4b",
        "mxbai-embed-large",
        "qwen3.5:9b",
    ]
    result = _pick_recommended_model(models)
    assert result["model"] == "qwen3.5:4b"
    assert "embed" not in result["model"]


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_recommended_model_embed_only_returns_empty():
    """If only embedders are installed, recommend nothing (not nomic-embed)."""
    from openjarvis.server.agent_manager_routes import _pick_recommended_model

    result = _pick_recommended_model(["nomic-embed-text", "mxbai-embed-large"])
    assert result["model"] == ""
    assert "No local chat model" in result["reason"]


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_is_embed_only_model():
    from openjarvis.server.agent_manager_routes import _is_embed_only_model

    assert _is_embed_only_model("nomic-embed-text")
    assert _is_embed_only_model("mxbai-embed-large")
    assert _is_embed_only_model("text-embedding-3-small")
    assert not _is_embed_only_model("qwen3.5:4b")
    assert not _is_embed_only_model("codegemma:7b")
