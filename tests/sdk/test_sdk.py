"""Tests for the Python SDK — Jarvis class and MemoryHandle."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import openjarvis
from openjarvis.core.config import JarvisConfig
from openjarvis.sdk import Jarvis, MemoryHandle


def _make_engine(content="Hello from SDK"):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


class TestJarvisInit:
    def test_default_config(self):
        j = Jarvis(config=JarvisConfig())
        assert j.config is not None
        j.close()

    def test_custom_config(self):
        cfg = JarvisConfig()
        j = Jarvis(config=cfg)
        assert j.config is cfg
        j.close()

    def test_version_property(self):
        j = Jarvis(config=JarvisConfig())
        assert j.version == openjarvis.__version__
        j.close()

    def test_engine_key_override(self):
        j = Jarvis(config=JarvisConfig(), engine_key="custom")
        assert j._engine_key == "custom"
        j.close()

    def test_model_override(self):
        j = Jarvis(config=JarvisConfig(), model="my-model")
        assert j._model_override == "my-model"
        j.close()


class TestJarvisAsk:
    def test_ask_returns_string(self):
        engine = _make_engine("The answer is 42.")
        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig(), model="test-model")
            result = j.ask("What is the answer?")
            assert result == "The answer is 42."
            j.close()

    def test_ask_with_model_override(self):
        engine = _make_engine()
        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig())
            j.ask("Hello", model="custom-model")
            # Verify engine.generate was called with the custom model
            call_kwargs = engine.generate.call_args
            assert call_kwargs[1]["model"] == "custom-model"
            j.close()

    def test_ask_with_agent(self):
        from openjarvis.agents._stubs import AgentResult
        from openjarvis.core.registry import AgentRegistry

        engine = _make_engine()

        class MockAgent:
            agent_id = "mock-agent"

            def __init__(self, eng, model, **kwargs):
                pass

            def run(self, input, context=None, **kwargs):
                return AgentResult(content="Agent response", turns=1)

        AgentRegistry.register_value("mock-agent", MockAgent)

        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig(), model="test-model")
            result = j.ask("Hello", agent="mock-agent")
            assert result == "Agent response"
            j.close()

    def test_ask_no_engine_raises(self):
        with patch("openjarvis.sdk.get_engine", return_value=None):
            j = Jarvis(config=JarvisConfig())
            with pytest.raises(RuntimeError, match="No inference engine"):
                j.ask("Hello")
            j.close()

    def test_ask_full_returns_dict(self):
        engine = _make_engine("Full response")
        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig(), model="test-model")
            result = j.ask_full("Hello")
            assert isinstance(result, dict)
            assert "content" in result
            assert "usage" in result
            assert result["content"] == "Full response"
            j.close()


class TestJarvisModels:
    def test_list_models(self):
        engine = _make_engine()
        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig())
            models = j.list_models()
            assert models == ["test-model"]
            j.close()

    def test_list_engines(self):
        from openjarvis.core.registry import EngineRegistry

        EngineRegistry.register_value("test-eng", object)
        j = Jarvis(config=JarvisConfig())
        engines = j.list_engines()
        assert "test-eng" in engines
        j.close()

    def test_list_engines_empty(self):
        j = Jarvis(config=JarvisConfig())
        engines = j.list_engines()
        assert isinstance(engines, list)
        j.close()


class TestMemoryHandle:
    def test_lazy_backend_init(self):
        cfg = JarvisConfig()
        handle = MemoryHandle(cfg)
        assert handle._backend is None
        handle.close()

    def test_close_idempotent(self):
        cfg = JarvisConfig()
        handle = MemoryHandle(cfg)
        handle.close()
        handle.close()  # should not raise

    def test_index_file(self, tmp_path):
        # Create a test file with enough content to produce chunks
        test_file = tmp_path / "test.txt"
        words = " ".join(f"word{i}" for i in range(100))
        test_file.write_text(words)

        # Mock the memory backend
        mock_backend = MagicMock()
        mock_backend.store.return_value = "doc-1"

        cfg = JarvisConfig()
        handle = MemoryHandle(cfg)
        handle._backend = mock_backend

        result = handle.index(str(test_file))
        assert result["chunks"] > 0
        assert "doc_ids" in result
        handle.close()

    def test_search_returns_results(self):
        mock_backend = MagicMock()
        mock_result = MagicMock()
        mock_result.content = "test content"
        mock_result.score = 0.9
        mock_result.source = "test.txt"
        mock_result.metadata = {}
        mock_backend.retrieve.return_value = [mock_result]

        cfg = JarvisConfig()
        handle = MemoryHandle(cfg)
        handle._backend = mock_backend

        results = handle.search("test query")
        assert len(results) == 1
        assert results[0]["content"] == "test content"
        handle.close()

    def test_search_empty(self):
        mock_backend = MagicMock()
        mock_backend.retrieve.return_value = []

        cfg = JarvisConfig()
        handle = MemoryHandle(cfg)
        handle._backend = mock_backend

        results = handle.search("nothing")
        assert results == []
        handle.close()

    def test_stats_returns_dict(self):
        mock_backend = MagicMock()
        mock_backend.count.return_value = 5

        cfg = JarvisConfig()
        handle = MemoryHandle(cfg)
        handle._backend = mock_backend

        stats = handle.stats()
        assert isinstance(stats, dict)
        assert stats["count"] == 5
        handle.close()


class TestJarvisStreaming:
    @pytest.mark.asyncio
    async def test_ask_stream_yields_tokens(self):
        engine = _make_engine()

        async def mock_stream(*args, **kwargs):
            for token in ["Hello", " ", "world"]:
                yield token

        engine.stream = mock_stream

        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig(), model="test-model")
            tokens = []
            async for token in j.ask_stream("Hi"):
                tokens.append(token)
            assert tokens == ["Hello", " ", "world"]
            j.close()

    @pytest.mark.asyncio
    async def test_ask_full_stream_yields_dicts(self):
        engine = _make_engine()

        async def mock_stream(*args, **kwargs):
            for token in ["Hello", " ", "world"]:
                yield token

        engine.stream = mock_stream

        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig(), model="test-model")
            chunks = []
            async for chunk in j.ask_full_stream("Hi"):
                chunks.append(chunk)

            # First three chunks are token dicts
            assert chunks[0] == {"token": "Hello", "index": 0}
            assert chunks[1] == {"token": " ", "index": 1}
            assert chunks[2] == {"token": "world", "index": 2}

            # Final chunk has done flag and full content
            final = chunks[-1]
            assert final["done"] is True
            assert final["content"] == "Hello world"
            assert final["model"] == "test-model"
            assert final["engine"] == "mock"
            j.close()

    @pytest.mark.asyncio
    async def test_ask_stream_with_model_override(self):
        engine = _make_engine()
        call_log: list = []

        async def mock_stream(*args, **kwargs):
            call_log.append(kwargs)
            for token in ["ok"]:
                yield token

        engine.stream = mock_stream

        with patch("openjarvis.sdk.get_engine", return_value=("mock", engine)):
            j = Jarvis(config=JarvisConfig())
            tokens = []
            async for token in j.ask_stream("Hi", model="custom-model"):
                tokens.append(token)
            assert tokens == ["ok"]
            assert call_log[0]["model"] == "custom-model"
            j.close()


class TestJarvisLifecycle:
    def test_close_releases_resources(self):
        j = Jarvis(config=JarvisConfig())
        j.close()
        assert j._engine is None

    def test_double_close_safe(self):
        j = Jarvis(config=JarvisConfig())
        j.close()
        j.close()  # should not raise
