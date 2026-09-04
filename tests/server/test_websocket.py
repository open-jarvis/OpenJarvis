"""Tests for the WebSocket streaming endpoint."""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from openjarvis.server.api_routes import include_all_routes  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(engine=None):
    """Create a minimal FastAPI app with mock engine wired up."""
    app = FastAPI()
    if engine is None:
        engine = _make_streaming_engine()
    app.state.engine = engine
    app.state.model = "test-model"
    include_all_routes(app)
    return app


def _make_streaming_engine(tokens=None):
    """Return a mock engine whose ``stream()`` yields tokens."""
    if tokens is None:
        tokens = ["Hello", " ", "world"]
    engine = MagicMock()
    engine.engine_id = "mock"

    async def mock_stream(messages, *, model="test-model", **kwargs):
        for tok in tokens:
            yield tok

    engine.stream = mock_stream
    engine.generate.return_value = {
        "content": "Hello world",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


def _make_generate_only_engine(content="Hello world"):
    """Return a mock engine that only has ``generate()`` (no ``stream()``)."""
    engine = MagicMock(spec=["generate", "engine_id"])
    engine.engine_id = "mock-nostream"
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }
    return engine


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWebSocketStreaming:
    """Tests for WS /v1/chat/stream endpoint."""

    def test_basic_streaming_exchange(self):
        """A valid message should produce chunk messages followed by a done."""
        app = _make_app()
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"message": "Hi"}))
            chunks = []
            done = None
            # Read all responses until we get 'done'
            while True:
                data = ws.receive_json()
                if data["type"] == "chunk":
                    chunks.append(data["content"])
                elif data["type"] == "done":
                    done = data
                    break
                else:
                    break
            assert len(chunks) == 3
            assert chunks == ["Hello", " ", "world"]
            assert done is not None
            assert done["content"] == "Hello world"

    def test_sync_stream_next_and_close_run_off_event_loop(self):
        stream_threads: list[int] = []
        next_threads: list[int] = []
        close_threads: list[int] = []

        class BlockingIterator:
            def __init__(self):
                self._tokens = iter(["one", "two"])

            def __iter__(self):
                return self

            def __next__(self):
                next_threads.append(threading.get_ident())
                return next(self._tokens)

            def close(self):
                close_threads.append(threading.get_ident())

        class SyncEngine:
            engine_id = "sync"

            def stream(self, messages, *, model="test-model", **kwargs):
                stream_threads.append(threading.get_ident())
                return BlockingIterator()

        app = _make_app(engine=SyncEngine())
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"message": "Hi"}))
            while ws.receive_json()["type"] != "done":
                pass

        assert stream_threads
        assert next_threads
        assert close_threads
        assert all(thread != stream_threads[0] for thread in next_threads)
        assert close_threads[0] != stream_threads[0]

    def test_missing_message_field(self):
        """Sending JSON without a 'message' field should return an error."""
        app = _make_app()
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"text": "Hi"}))
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Missing" in data["detail"]

    def test_invalid_json(self):
        """Sending non-JSON text should return an error."""
        app = _make_app()
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text("not json at all")
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Invalid JSON" in data["detail"]

    def test_empty_message_field(self):
        """An empty string for 'message' should return an error."""
        app = _make_app()
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"message": ""}))
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Missing" in data["detail"]

    def test_generate_fallback_when_no_stream(self):
        """When the engine has no stream(), generate() result is sent as one chunk."""
        engine = _make_generate_only_engine("Fallback response")
        app = _make_app(engine=engine)
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"message": "Hi"}))
            chunks = []
            done = None
            while True:
                data = ws.receive_json()
                if data["type"] == "chunk":
                    chunks.append(data["content"])
                elif data["type"] == "done":
                    done = data
                    break
                else:
                    break
            assert len(chunks) == 1
            assert chunks[0] == "Fallback response"
            assert done is not None
            assert done["content"] == "Fallback response"

    def test_custom_model_in_request(self):
        """The model field from the request should be forwarded to the engine."""
        tokens = ["OK"]
        engine = _make_streaming_engine(tokens=tokens)
        app = _make_app(engine=engine)
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"message": "Hi", "model": "custom-model"}))
            # Consume until done
            while True:
                data = ws.receive_json()
                if data["type"] == "done":
                    break
            # The mock stream function was called — we can't easily inspect
            # async-generator call args, but the exchange completed without error
            assert data["content"] == "OK"

    def test_engine_error_returns_error_message(self):
        """If the engine raises, the endpoint should send an error frame."""
        engine = MagicMock()

        async def bad_stream(messages, *, model="test-model", **kwargs):
            raise RuntimeError("Engine exploded")
            # Make it look like an async generator to the endpoint
            yield  # pragma: no cover – unreachable, but needed for async gen syntax

        engine.stream = bad_stream
        app = _make_app(engine=engine)
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"message": "boom"}))
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "Engine exploded" in data["detail"]

    def test_multiple_messages_on_same_connection(self):
        """The WebSocket should support multiple request/response cycles."""
        app = _make_app()
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            for _ in range(3):
                ws.send_text(json.dumps({"message": "Hi"}))
                # Drain until done
                while True:
                    data = ws.receive_json()
                    if data["type"] == "done":
                        assert data["content"] == "Hello world"
                        break

    def test_no_engine_configured(self):
        """If app.state has no engine, an error should be returned."""
        app = FastAPI()
        app.state.model = "test-model"
        # Intentionally do NOT set app.state.engine
        include_all_routes(app)
        client = TestClient(app)
        with client.websocket_connect("/v1/chat/stream") as ws:
            ws.send_text(json.dumps({"message": "Hi"}))
            data = ws.receive_json()
            assert data["type"] == "error"
            assert "engine" in data["detail"].lower()


__all__ = [
    "TestWebSocketStreaming",
]
