"""Tests for the API server routes."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(content="Hello from server", models=None):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = models or ["test-model"]
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }

    # Set up async stream
    async def mock_stream(
        messages,
        *,
        model,
        temperature=0.7,
        max_tokens=1024,
        **kwargs,
    ):
        for token in ["Hello", " ", "world"]:
            yield token

    engine.stream = mock_stream
    return engine


def _make_agent(content="Hello from agent"):
    from openjarvis.agents._stubs import AgentResult

    agent = MagicMock()
    agent.agent_id = "mock"
    agent.run.return_value = AgentResult(content=content, turns=1)
    return agent


@pytest.fixture
def client():
    engine = _make_engine()
    app = create_app(engine, "test-model")
    return TestClient(app)


@pytest.fixture
def client_with_agent():
    engine = _make_engine()
    agent = _make_agent()
    app = create_app(engine, "test-model", agent=agent)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Chat completions tests
# ---------------------------------------------------------------------------


class TestChatCompletions:
    def test_basic_completion(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "Hello from server"

    def test_invalid_model_returns_korean_message(self):
        engine = _make_engine(models=["qwen3:0.6b"])
        app = create_app(engine, "qwen3:0.6b")
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3.5:27b",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert (
            data["choices"][0]["message"]["content"]
            == "선택한 모델을 Ollama에서 찾을 수 없습니다. 설치된 모델을 선택해주세요."
        )

    def test_invalid_model_streams_korean_message(self):
        engine = _make_engine(models=["qwen3:0.6b"])
        app = create_app(engine, "qwen3:0.6b")
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3.5:27b",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )

        assert resp.status_code == 200
        assert "선택한 모델을 Ollama에서 찾을 수 없습니다" in resp.text

    def test_completion_has_usage(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = resp.json()
        assert data["usage"]["total_tokens"] == 8

    def test_completion_has_id(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = resp.json()
        assert data["id"].startswith("chatcmpl-")

    def test_custom_temperature(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "temperature": 0.1,
            },
        )
        assert resp.status_code == 200

    def test_with_system_message(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Be helpful"},
                    {"role": "user", "content": "Hello"},
                ],
            },
        )
        assert resp.status_code == 200

    def test_with_tools(self):
        engine = _make_engine()
        engine.generate.return_value = {
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "calc", "arguments": '{"expr":"2+2"}'},
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "test-model",
            "finish_reason": "tool_calls",
        }
        app = create_app(engine, "test-model")
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Calc"}],
                "tools": [{"type": "function", "function": {"name": "calc"}}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["tool_calls"] is not None

    def test_agent_mode(self, client_with_agent):
        resp = client_with_agent.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello from agent"

    def test_agent_with_conversation(self, client_with_agent):
        resp = client_with_agent.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Be helpful"},
                    {"role": "user", "content": "Hello"},
                ],
            },
        )
        assert resp.status_code == 200

    def test_streaming(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        # Parse SSE events
        lines = resp.text.strip().split("\n")
        data_lines = [ln for ln in lines if ln.startswith("data:")]
        assert len(data_lines) > 0
        # Last should be [DONE]
        assert data_lines[-1].strip() == "data: [DONE]"

    def test_streaming_content(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        # Collect content tokens from stream
        content = ""
        for line in resp.text.strip().split("\n"):
            if line.startswith("data:") and "[DONE]" not in line:
                data = json.loads(line[5:].strip())
                choices = data.get("choices", [{}])
                delta_content = (
                    choices[0]
                    .get(
                        "delta",
                        {},
                    )
                    .get("content")
                )
                if delta_content:
                    content += delta_content
        assert content == "Hello world"

    def test_finish_reason_default(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = resp.json()
        assert data["choices"][0]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Voice speak tests
# ---------------------------------------------------------------------------


class TestVoiceSpeak:
    def test_voice_speak_success(self, client, monkeypatch):
        from openjarvis.voice.tts import SpeakResult

        calls = []

        def fake_speak(*args, **kwargs):
            calls.append((args, kwargs))
            return SpeakResult(
                ok=True,
                message="음성 응답 중...",
                text="안녕하세요",
                chunks=["안녕하세요"],
            )

        monkeypatch.setattr("openjarvis.voice.tts.speak_macos_say", fake_speak)

        resp = client.post(
            "/v1/voice/speak",
            json={"text": "안녕하세요", "voice": "Yuna", "rate": 175},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "ok": True,
            "engine": "macos_say",
            "message": "음성 응답 중...",
            "text": "안녕하세요",
            "chunks": ["안녕하세요"],
        }
        assert calls == [
            (
                ("안녕하세요",),
                {
                    "voice": "Yuna",
                    "rate": 175,
                    "max_chars": 400,
                    "pause_ms": 250,
                    "naturalize": True,
                },
            )
        ]

    def test_voice_speak_empty_text_returns_json_error(self, client, monkeypatch):
        from openjarvis.voice.tts import SpeakResult

        def fake_speak(*args, **kwargs):
            return SpeakResult(ok=False, message="읽을 음성 응답이 없습니다.")

        monkeypatch.setattr("openjarvis.voice.tts.speak_macos_say", fake_speak)

        resp = client.post("/v1/voice/speak", json={"text": ""})

        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert resp.json()["message"] == "읽을 음성 응답이 없습니다."

    def test_voice_speak_stop(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "openjarvis.voice.tts.stop_macos_say",
            lambda: calls.append(True),
        )

        resp = client.post("/v1/voice/speak", json={"stop": True})

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["message"] == "음성 응답을 중지했습니다."
        assert calls == [True]

    def test_voice_speak_failure_does_not_raise(self, client, monkeypatch):
        from openjarvis.voice.tts import SpeakResult

        def fake_speak(*args, **kwargs):
            return SpeakResult(
                ok=False,
                message="TTS 음성을 찾을 수 없습니다. macOS 음성 설정을 확인해주세요.",
            )

        monkeypatch.setattr("openjarvis.voice.tts.speak_macos_say", fake_speak)

        resp = client.post("/v1/voice/speak", json={"text": "안녕하세요"})

        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert (
            resp.json()["message"]
            == "TTS 음성을 찾을 수 없습니다. macOS 음성 설정을 확인해주세요."
        )


# ---------------------------------------------------------------------------
# Models endpoint tests
# ---------------------------------------------------------------------------


class TestModelsEndpoint:
    def test_list_models(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "test-model"

    def test_model_object_format(self, client):
        resp = client.get("/v1/models")
        data = resp.json()
        model = data["data"][0]
        assert model["object"] == "model"
        assert "owned_by" in model

    def test_multiple_models(self):
        engine = _make_engine(models=["model-a", "model-b", "model-c"])
        app = create_app(engine, "model-a")
        client = TestClient(app)
        resp = client.get("/v1/models")
        data = resp.json()
        assert len(data["data"]) == 3


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_healthy(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_unhealthy(self):
        engine = _make_engine()
        engine.health.return_value = False
        app = create_app(engine, "test-model")
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# App creation tests
# ---------------------------------------------------------------------------


class TestCreateApp:
    def test_app_state(self):
        engine = _make_engine()
        app = create_app(engine, "test-model")
        assert app.state.engine is engine
        assert app.state.model == "test-model"

    def test_app_with_agent(self):
        engine = _make_engine()
        agent = _make_agent()
        app = create_app(engine, "test-model", agent=agent)
        assert app.state.agent is agent

    def test_app_without_agent(self):
        engine = _make_engine()
        app = create_app(engine, "test-model")
        assert app.state.agent is None
