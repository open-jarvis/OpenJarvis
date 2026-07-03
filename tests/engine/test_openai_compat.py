"""Tests for the OpenAI-compatible engine base (covers vLLM + llama.cpp)."""

from __future__ import annotations

import httpx
import pytest

try:
    import respx

    _HAS_RESPX = True
except ImportError:  # respx is an optional test-only dep; MockTransport tests
    respx = None  # type: ignore[assignment]  # still run without it.
    _HAS_RESPX = False

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine._openai_compat import EngineContextLengthError
from openjarvis.engine.openai_compat_engines import VLLMEngine

# respx-backed tests exercise the SYNC client paths (generate/list_models/health)
# and skip cleanly when respx is absent; the async stream/timeout/disconnect tests
# below use httpx.MockTransport directly and never need respx.
requires_respx = pytest.mark.skipif(
    not _HAS_RESPX, reason="respx not installed (optional test-only dependency)"
)


def _sse_transport(sse_lines: list[str]) -> httpx.MockTransport:
    body = "\n".join(sse_lines) + "\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    return httpx.MockTransport(handler)


@pytest.fixture()
def engine() -> VLLMEngine:
    EngineRegistry.register_value("vllm", VLLMEngine)
    return VLLMEngine(host="http://testhost:8000")


@requires_respx
class TestOpenAICompatGenerate:
    def test_generate_returns_content(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {"content": "4"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 8,
                            "completion_tokens": 1,
                            "total_tokens": 9,
                        },
                        "model": "qwen3:8b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="2+2")], model="qwen3:8b"
            )
        assert result["content"] == "4"
        assert result["usage"]["total_tokens"] == 9

    def test_empty_choices_returns_graceful_fallback(
        self,
        engine: VLLMEngine,
    ) -> None:
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 0,
                            "total_tokens": 5,
                        },
                        "model": "test",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="hi")],
                model="test",
            )
        assert result["content"] == ""
        assert result["finish_reason"] == "error"

    def test_generate_connection_error(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )


@requires_respx
class TestOpenAICompatListModels:
    def test_list_models(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                return_value=httpx.Response(
                    200,
                    json={"data": [{"id": "model-a"}, {"id": "model-b"}]},
                )
            )
            assert engine.list_models() == ["model-a", "model-b"]


@requires_respx
class TestOpenAICompatHealth:
    def test_health_true(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            assert engine.health() is True

    def test_health_false(self, engine: VLLMEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8000/v1/models").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


@requires_respx
class TestOpenAICompatStream:
    @pytest.mark.asyncio
    async def test_stream_sse(self, engine: VLLMEngine) -> None:
        sse_lines = (
            'data: {"choices":[{"delta":{"content":"Hi"}}]}\n'
            'data: {"choices":[{"delta":{"content":" there"}}]}\n'
            "data: [DONE]\n"
        )
        with respx.mock:
            respx.post("http://testhost:8000/v1/chat/completions").mock(
                return_value=httpx.Response(200, text=sse_lines)
            )
            tokens = []
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hello")], model="m"
            ):
                tokens.append(tok)
        assert tokens == ["Hi", " there"]


class TestStreamIsAsyncAndBounded:
    """Regression pins for BC2: the stream path is async (never blocks the event
    loop on the SYNC httpx client) and a wedged/oversized upstream is bounded and
    mapped to a clean error instead of hanging or surfacing raw HTTP."""

    @pytest.mark.asyncio
    async def test_timeout_is_applied_to_async_stream_client(self) -> None:
        # HARDENED: assert the configured timeout is actually APPLIED to the async
        # stream client, not merely stored on the engine. Deleting
        # ``timeout=self._timeout`` from ``_make_async_client`` drops the client to
        # httpx's 5s default and fails this (a stored-only assertion would not).
        engine = VLLMEngine(host="http://testhost:8000", timeout=180.0)
        assert engine._timeout == 180.0
        client = engine._make_async_client()
        try:
            assert client.timeout == httpx.Timeout(180.0)
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_stream_does_not_use_blocking_sync_client(self) -> None:
        # PIN: the old code iterated ``self._client`` (a SYNC httpx.Client) inside
        # this ``async def``, blocking the single uvicorn worker between tokens.
        # The async path must not touch the sync client at all.
        engine = VLLMEngine(host="http://localhost:8000")
        engine._async_transport = _sse_transport(
            [
                'data: {"choices":[{"delta":{"content":"Hi"}}]}',
                'data: {"choices":[{"delta":{"content":" there"}}]}',
                "data: [DONE]",
            ]
        )

        class _Boom:
            def stream(self, *a, **k):  # pragma: no cover - must never run
                raise AssertionError("streaming used the blocking sync client")

        engine._client = _Boom()  # type: ignore[assignment]
        tokens = [
            tok
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hello")], model="m"
            )
        ]
        assert tokens == ["Hi", " there"]

    @pytest.mark.asyncio
    async def test_wedged_read_is_bounded_by_timeout(self) -> None:
        # A wedged upstream read trips the (small, honoured) timeout and maps to a
        # clean EngineConnectionError rather than hanging the caller.
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            # httpx populates request.extensions["timeout"] with the per-op timeouts
            # that were actually applied to THIS request; capturing it here proves
            # the configured 0.05s reached the wire, not just the engine attribute.
            seen["timeout"] = request.extensions["timeout"]
            raise httpx.ReadTimeout("wedged upstream", request=request)

        engine = VLLMEngine(host="http://localhost:8000", timeout=0.05)
        engine._async_transport = httpx.MockTransport(handler)
        with pytest.raises(EngineConnectionError):
            async for _ in engine.stream(
                [Message(role=Role.USER, content="Hello")], model="m"
            ):
                pass
        # HARDENED: the configured timeout was APPLIED to the request. Deleting
        # ``timeout=self._timeout`` from ``_make_async_client`` drops this to httpx's
        # 5.0s default and fails the assertion.
        assert seen["timeout"]["read"] == 0.05

    @pytest.mark.asyncio
    async def test_context_length_400_maps_to_context_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                text=(
                    "This model's maximum context length is 4096 tokens. "
                    "However, you requested 5200 tokens. Please reduce the length."
                ),
            )

        engine = VLLMEngine(host="http://localhost:8000")
        engine._async_transport = httpx.MockTransport(handler)
        with pytest.raises(EngineContextLengthError) as excinfo:
            async for _ in engine.stream(
                [Message(role=Role.USER, content="Hello")], model="m"
            ):
                pass
        assert getattr(excinfo.value, "is_context_length_error", False) is True

    @pytest.mark.asyncio
    async def test_other_upstream_error_maps_to_connection_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="internal server error")

        engine = VLLMEngine(host="http://localhost:8000")
        engine._async_transport = httpx.MockTransport(handler)
        with pytest.raises(EngineConnectionError) as excinfo:
            async for _ in engine.stream(
                [Message(role=Role.USER, content="Hello")], model="m"
            ):
                pass
        # A generic upstream failure is NOT reported as a context-length problem.
        assert not isinstance(excinfo.value, EngineContextLengthError)

    @pytest.mark.asyncio
    async def test_mid_stream_disconnect_maps_to_connection_error(self) -> None:
        # PIN: a server dying MID-STREAM raises httpx.RemoteProtocolError from
        # aiter_lines. Before the except tuple was widened it propagated raw; it
        # must now surface as a clean EngineConnectionError.
        class _MidStreamCrashStream(httpx.AsyncByteStream):
            def __init__(self, request: httpx.Request) -> None:
                self._request = request

            async def __aiter__(self):
                yield b'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
                raise httpx.RemoteProtocolError(
                    "peer closed connection mid-stream", request=self._request
                )

            async def aclose(self) -> None:  # pragma: no cover - trivial
                pass

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=_MidStreamCrashStream(request))

        engine = VLLMEngine(host="http://localhost:8000")
        engine._async_transport = httpx.MockTransport(handler)
        tokens: list[str] = []
        with pytest.raises(EngineConnectionError) as excinfo:
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hello")], model="m"
            ):
                tokens.append(tok)
        # The disconnect happened AFTER the first token was delivered (mid-stream),
        # and did not masquerade as a context-length error.
        assert tokens == ["Hi"]
        assert not isinstance(excinfo.value, EngineContextLengthError)
