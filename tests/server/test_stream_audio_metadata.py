"""The streaming chat path must carry per-response audio metadata.

``_handle_agent`` already decides whether a given run produced audio: it sets
``choices[0].message.audio`` only when that run wrote an audio file. The
non-streaming response returns it. Streaming used to drop it, which left
clients unable to tell a digest reply from an ordinary one -- so the desktop UI
asked ``/api/digest`` after every answer instead, a global question whose
"yes" means a digest exists somewhere, not that this answer is one. Once a
morning digest had ever produced a ``.wav``, every chat reply rendered an
audio player for it.
"""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("fastapi")

from openjarvis.server.models import (  # noqa: E402
    AudioMeta,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ChoiceMessage,
    UsageInfo,
)
from openjarvis.server.routes import _handle_agent_stream  # noqa: E402


def _response(audio: AudioMeta | None) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        model="test-model",
        choices=[
            Choice(
                message=ChoiceMessage(
                    role="assistant",
                    content="hello",
                    audio=audio,
                ),
                finish_reason="stop",
            )
        ],
        usage=UsageInfo(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )


def _collect(monkeypatch, response: ChatCompletionResponse) -> list[dict]:
    """Run the streaming handler and return its decoded SSE payloads."""
    monkeypatch.setattr(
        "openjarvis.server.routes._handle_agent",
        lambda *a, **k: response,
    )

    req = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    async def run() -> list[dict]:
        streaming = await _handle_agent_stream(object(), "test-model", req)
        payloads = []
        async for raw in streaming.body_iterator:
            for line in raw.splitlines():
                if not line.startswith("data: "):
                    continue
                data = line[len("data: ") :]
                if data == "[DONE]":
                    continue
                payloads.append(json.loads(data))
        return payloads

    return asyncio.run(run())


class TestStreamedAudioMetadata:
    def test_audio_is_forwarded_when_the_run_produced_it(self, monkeypatch):
        payloads = _collect(monkeypatch, _response(AudioMeta(url="/api/digest/audio")))

        with_audio = [p for p in payloads if "audio" in p]
        assert with_audio, "streaming dropped the audio metadata"
        assert with_audio[0]["audio"]["url"] == "/api/digest/audio"

    def test_audio_rides_on_the_finish_chunk(self, monkeypatch):
        payloads = _collect(monkeypatch, _response(AudioMeta(url="/api/digest/audio")))

        carrier = next(p for p in payloads if "audio" in p)
        assert carrier["choices"][0]["finish_reason"] == "stop"
        # Same chunk that already carries usage, so one parse point, not two.
        assert "usage" in carrier

    def test_no_audio_key_when_the_run_produced_none(self, monkeypatch):
        payloads = _collect(monkeypatch, _response(None))

        assert not [p for p in payloads if "audio" in p], (
            "an ordinary reply must not advertise audio; a client that sees "
            "this key renders a player for an unrelated recording"
        )

    def test_ordinary_reply_still_streams_content_and_usage(self, monkeypatch):
        payloads = _collect(monkeypatch, _response(None))

        content = "".join(
            p["choices"][0].get("delta", {}).get("content") or "" for p in payloads
        )
        assert content == "hello"
        assert any("usage" in p for p in payloads)
