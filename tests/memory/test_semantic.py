"""Tests for semantic fact ranking via local embeddings."""

from __future__ import annotations

from types import SimpleNamespace

from openjarvis.memory.store import Fact
from openjarvis.tools.storage.context import ContextConfig, inject_context
from openjarvis.tools.storage.semantic import (
    SemanticFactRanker,
    build_semantic_ranker,
)


class _FakeEmbedder:
    """Deterministic unit vectors; dot-product == cosine by construction."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.dim_calls = 0

    def embed(self, texts: list[str]):
        import numpy as np

        return np.asarray(
            [self._vectors[text] for text in texts], dtype=np.float32
        )

    def dim(self) -> int:
        self.dim_calls += 1
        return 2


def test_ranker_orders_by_similarity() -> None:
    embedder = _FakeEmbedder(
        {
            "query": [1.0, 0.0],
            "about weather": [1.0, 0.0],
            "about music": [0.0, 1.0],
        }
    )
    ranker = SemanticFactRanker(embedder)
    scores = ranker.rank("query", ["about music", "about weather"])
    assert scores[0] < scores[1]


def test_ranker_caches_fact_embeddings() -> None:
    embedder = _FakeEmbedder(
        {"query": [1.0, 0.0], "fact": [1.0, 0.0]}
    )
    ranker = SemanticFactRanker(embedder)
    ranker.rank("query", ["fact"])
    ranker.rank("query", ["fact"])
    # Two queries + one fact = 3 embed calls; the fact is not re-embedded.
    assert len(ranker._cache) == 1


def test_ranker_empty_texts_returns_empty() -> None:
    ranker = SemanticFactRanker(_FakeEmbedder({"query": [1.0, 0.0]}))
    assert ranker.rank("query", []) == []


def test_inject_context_ranks_facts_by_semantics() -> None:
    # Newest fact is about music; the query is about weather. With the ranker
    # the weather fact must win the budget despite being older.
    facts = [
        Fact(text="The user listens to jazz", source="auto", trust="auto"),
        Fact(text="The user lives in Paris", source="auto", trust="auto"),
    ]
    embedder = _FakeEmbedder(
        {
            "query": [1.0, 0.0],
            "The user listens to jazz": [0.0, 1.0],
            "The user lives in Paris": [1.0, 0.0],
        }
    )
    ranker = SemanticFactRanker(embedder)

    messages = inject_context(
        "What is the weather in my city?",
        [],
        None,
        config=ContextConfig(max_context_tokens=8),
        facts=facts,
        ranker=ranker,
    )

    assert messages
    content = messages[0].content
    assert "Paris" in content
    assert "jazz" not in content


def test_inject_context_ranker_failure_falls_back_to_recency() -> None:
    facts = [Fact(text="The user listens to jazz", source="auto", trust="auto")]

    class _ExplodingRanker:
        def rank(self, query, texts):
            raise RuntimeError("embedding server down")

    messages = inject_context(
        "query",
        [],
        None,
        config=ContextConfig(max_context_tokens=8),
        facts=facts,
        ranker=_ExplodingRanker(),
    )
    assert messages
    assert "jazz" in messages[0].content


def test_build_semantic_ranker_returns_none_when_disabled() -> None:
    config = SimpleNamespace(memory=SimpleNamespace(semantic_enabled=False))
    assert build_semantic_ranker(config) is None


def test_build_semantic_ranker_returns_none_when_ollama_missing(monkeypatch) -> None:
    class _BrokenEmbedder:
        def __init__(self, model: str = "", **kwargs):
            raise RuntimeError("no ollama server")

    monkeypatch.setattr(
        "openjarvis.tools.storage.embeddings.OllamaEmbedder",
        _BrokenEmbedder,
    )
    config = SimpleNamespace(
        memory=SimpleNamespace(
            semantic_enabled=True,
            embedding_model="nomic-embed-text",
        )
    )
    # The embedder fails to build: must not raise, just report unavailability.
    assert build_semantic_ranker(config) is None


def test_build_semantic_ranker_env_flag_override(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_SEMANTIC_MEMORY", "0")
    config = SimpleNamespace(memory=SimpleNamespace(semantic_enabled=True))
    assert build_semantic_ranker(config) is None
