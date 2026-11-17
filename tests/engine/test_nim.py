"""Tests for the NVIDIA NIM inference engine."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.nim import NIMEngine

_HOST = "https://nim.test"
_CHAT_URL = f"{_HOST}/v1/chat/completions"


def _message() -> list[Message]:
    return [Message(role=Role.USER, content="Hello")]


def test_generate_preserves_tools_on_unsupported_request(respx_mock) -> None:
    """A 400 must not be retried after silently removing requested tools."""
    route = respx_mock.post(_CHAT_URL).mock(
        return_value=httpx.Response(400, json={"detail": "tools unsupported"})
    )
    engine = NIMEngine(host=_HOST)

    with pytest.raises(httpx.HTTPStatusError):
        engine.generate(
            _message(),
            model="nim-model",
            tools=[{"type": "function", "function": {"name": "lookup"}}],
        )

    assert route.call_count == 1
    payload = json.loads(route.calls[0].request.content)
    assert payload["tools"][0]["function"]["name"] == "lookup"
    assert payload["tool_choice"] == "auto"
    engine.close()


@pytest.mark.asyncio
async def test_stream_uses_async_http_and_sends_auth(respx_mock, monkeypatch) -> None:
    monkeypatch.setenv("NIM_API_KEY", "secret-token")
    body = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            "data: [DONE]",
        ]
    )
    route = respx_mock.post(_CHAT_URL).mock(return_value=httpx.Response(200, text=body))
    engine = NIMEngine(host=_HOST)
    engine._client.stream = MagicMock(  # type: ignore[method-assign]
        side_effect=AssertionError("sync client used from async stream")
    )

    chunks = [chunk async for chunk in engine.stream(_message(), model="nim-model")]

    assert chunks == ["Hello", " world"]
    assert route.calls[0].request.headers["Authorization"] == "Bearer secret-token"
    engine._client.close()


@pytest.mark.asyncio
async def test_stream_full_parses_tool_and_usage_chunks(respx_mock) -> None:
    body = "\n".join(
        [
            "data: "
            + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "function": {
                                            "name": "lookup",
                                            "arguments": "{}",
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ]
                }
            ),
            "data: "
            + json.dumps(
                {
                    "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
                    "usage": {"total_tokens": 9},
                }
            ),
            "data: [DONE]",
        ]
    )
    respx_mock.post(_CHAT_URL).mock(return_value=httpx.Response(200, text=body))
    engine = NIMEngine(host=_HOST)

    chunks = [
        chunk async for chunk in engine.stream_full(_message(), model="nim-model")
    ]

    assert chunks[0].tool_calls is not None
    assert chunks[0].tool_calls[0]["function"]["name"] == "lookup"
    assert chunks[1].finish_reason == "tool_calls"
    assert chunks[1].usage == {"total_tokens": 9}
    engine.close()


def test_generate_maps_connection_errors(respx_mock) -> None:
    respx_mock.post(_CHAT_URL).mock(side_effect=httpx.ConnectError("offline"))
    engine = NIMEngine(host=_HOST)

    with pytest.raises(EngineConnectionError, match="not reachable"):
        engine.generate(_message(), model="nim-model")

    engine.close()


@pytest.mark.parametrize("status", [502, 503, 504])
def test_generate_maps_gateway_errors(respx_mock, status) -> None:
    respx_mock.post(_CHAT_URL).mock(return_value=httpx.Response(status))
    engine = NIMEngine(host=_HOST)

    with pytest.raises(EngineConnectionError, match=str(status)):
        engine.generate(_message(), model="nim-model")

    engine.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
@pytest.mark.parametrize("method", ["stream", "stream_full"])
async def test_stream_maps_gateway_errors(respx_mock, status, method) -> None:
    respx_mock.post(_CHAT_URL).mock(return_value=httpx.Response(status))
    engine = NIMEngine(host=_HOST)

    with pytest.raises(EngineConnectionError, match=str(status)):
        async for _ in getattr(engine, method)(_message(), model="nim-model"):
            pass

    engine._client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 429])
@pytest.mark.parametrize("method", ["generate", "stream", "stream_full"])
async def test_non_gateway_status_is_preserved(respx_mock, status, method) -> None:
    route = respx_mock.post(_CHAT_URL).mock(return_value=httpx.Response(status))
    engine = NIMEngine(host=_HOST)

    try:
        with pytest.raises(httpx.HTTPStatusError) as error:
            if method == "generate":
                engine.generate(_message(), model="nim-model")
            else:
                async for _ in getattr(engine, method)(_message(), model="nim-model"):
                    pass
        assert error.value.response.status_code == status
        assert route.call_count == 1
    finally:
        engine.close()


def test_health_falls_back_to_models(respx_mock) -> None:
    respx_mock.get(f"{_HOST}/v1/health/ready").mock(return_value=httpx.Response(404))
    models = respx_mock.get(f"{_HOST}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    engine = NIMEngine(host=_HOST)

    assert engine.health() is True
    assert models.called
    engine.close()


class TestCloudReporting:
    """Whether NIM declares itself a cloud engine.

    Engine fallback prefers a replacement on the same local/cloud boundary.
    NIMEngine inherited ``is_cloud = False`` from the base class while
    defaulting to NVIDIA's hosted API, so the check read False and a remote
    endpoint counted as local: with the preferred engine unavailable, `nim`
    beat `ollama` on alphabetical order and the server answered from a
    hosted model while a healthy local Ollama sat unused.
    """

    def test_the_default_host_is_reported_as_cloud(self, monkeypatch) -> None:
        monkeypatch.delenv("NIM_HOST", raising=False)

        assert NIMEngine().is_cloud is True

    def test_the_class_default_is_cloud_before_instantiation(self) -> None:
        # Fallback may consult the class rather than an instance.
        assert NIMEngine.is_cloud is True

    @pytest.mark.parametrize(
        "host",
        [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://[::1]:8000",
            "http://nim.local",
        ],
    )
    def test_a_self_hosted_nim_is_not_cloud(self, host: str) -> None:
        assert NIMEngine(host=host).is_cloud is False

    def test_a_remote_host_is_cloud(self) -> None:
        assert NIMEngine(host="https://integrate.api.nvidia.com").is_cloud is True

    def test_the_env_host_is_honoured(self, monkeypatch) -> None:
        monkeypatch.setenv("NIM_HOST", "http://localhost:9000")

        assert NIMEngine().is_cloud is False
