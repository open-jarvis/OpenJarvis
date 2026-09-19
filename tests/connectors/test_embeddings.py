"""Tests for openjarvis.connectors.embeddings.default_embedder."""

from __future__ import annotations

import pytest

from openjarvis.connectors import embeddings


def test_default_embedder_returns_instance_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings.OllamaEmbedder, "is_available", lambda self: True)
    emb = embeddings.default_embedder()
    assert isinstance(emb, embeddings.OllamaEmbedder)
    assert emb.model_version == f"ollama:{embeddings.DEFAULT_EMBED_MODEL}"


def test_default_embedder_returns_none_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings.OllamaEmbedder, "is_available", lambda self: False)
    assert embeddings.default_embedder() is None


def test_embedder_host_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit host > OLLAMA_HOST env > built-in default, like OllamaEngine."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert embeddings.OllamaEmbedder()._host == embeddings.DEFAULT_OLLAMA_HOST

    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434/")
    assert embeddings.OllamaEmbedder()._host == "http://127.0.0.1:11434"

    explicit = embeddings.OllamaEmbedder(host="http://gpu-box:11434")
    assert explicit._host == "http://gpu-box:11434"
