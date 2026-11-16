"""Exercise credential-safe errors beyond the ElevenLabs backend boundary."""

from __future__ import annotations

import dataclasses
import json
import logging
import traceback
from unittest.mock import Mock

import httpx
import pytest

from openjarvis.speech import elevenlabs_tts
from openjarvis.speech.elevenlabs_tts import ElevenLabsTTSBackend

_KEY = "sk_review_" + "credential_sentinel_" * 3


@pytest.mark.parametrize("error_type", [httpx.LocalProtocolError, httpx.ReadTimeout])
def test_tool_events_and_persisted_trace_keep_credentials_private(
    monkeypatch, tmp_path, caplog, error_type
):
    from openjarvis.agents._stubs import AgentResult
    from openjarvis.core.events import EventBus, EventType
    from openjarvis.core.registry import TTSRegistry
    from openjarvis.core.types import StepType, ToolCall
    from openjarvis.tools._stubs import ToolExecutor
    from openjarvis.tools.text_to_speech import TextToSpeechTool
    from openjarvis.traces.collector import TraceCollector
    from openjarvis.traces.store import TraceStore

    monkeypatch.setenv("ELEVENLABS_API_KEY", _KEY)
    TTSRegistry.register_value("elevenlabs", ElevenLabsTTSBackend)
    post = Mock(side_effect=error_type(f"provider diagnostic: {_KEY}"))
    monkeypatch.setattr(elevenlabs_tts.httpx, "post", post)
    bus = EventBus(record_history=True)
    executor = ToolExecutor([TextToSpeechTool()], bus=bus)

    class SpeechAgent:
        agent_id = "speech-credential-regression"

        def run(self, *args, **kwargs):
            result = executor.execute(
                ToolCall(
                    id="speech",
                    name="text_to_speech",
                    arguments=json.dumps(
                        {
                            "text": "A synthetic sample.",
                            "backend": "elevenlabs",
                            "output_dir": str(tmp_path / "audio"),
                        }
                    ),
                )
            )
            assert not result.success
            return AgentResult(content=result.content, tool_results=[result])

    store = TraceStore(tmp_path / "traces.db")
    try:
        collector = TraceCollector(SpeechAgent(), store=store, bus=bus)
        result = collector.run("Speak the sample.")
        post.assert_called_once()
        trace = store.get(collector.last_trace.trace_id)
        assert trace is not None
        assert any(step.step_type == StepType.TOOL_CALL for step in trace.steps)
        assert any(event.event_type == EventType.TOOL_CALL_END for event in bus.history)
        recorded = "\n".join(
            [
                repr(result),
                json.dumps(dataclasses.asdict(trace), default=str),
                repr(bus.history),
                caplog.text,
            ]
        )
        assert _KEY not in recorded
    finally:
        store.close()


def test_audio_read_failure_has_a_safe_logged_traceback(monkeypatch, caplog):
    class UnreadableAudio:
        def raise_for_status(self):
            pass

        @property
        def content(self):
            raise httpx.ReadError(f"response diagnostic: {_KEY}")

    monkeypatch.setattr(
        elevenlabs_tts.httpx, "post", Mock(return_value=UnreadableAudio())
    )
    with pytest.raises(RuntimeError, match="ElevenLabs request failed") as caught:
        ElevenLabsTTSBackend(api_key=_KEY).synthesize("A synthetic sample.")
    try:
        raise caught.value
    except RuntimeError:
        logging.getLogger(__name__).exception("Speech audio could not be read")
    assert _KEY not in str(caught.value)
    assert _KEY not in "".join(traceback.format_exception(caught.value))
    assert _KEY not in caplog.text


@pytest.mark.parametrize("operation", ["synthesize", "available_voices"])
@pytest.mark.parametrize("failure", ["transport", "stream"])
def test_httpx_transport_failures_do_not_escape_with_credentials(
    monkeypatch, caplog, operation, failure
):
    received = []

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadError(f"stream diagnostic: {_KEY}")
            yield b""  # pragma: no cover - preserves the byte-stream protocol

    def handler(request):
        received.append(request.headers["xi-api-key"])
        if failure == "transport":
            raise httpx.LocalProtocolError(
                f"header diagnostic: {_KEY}", request=request
            )
        return httpx.Response(200, request=request, stream=BrokenStream())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        method = "post" if operation == "synthesize" else "get"
        monkeypatch.setattr(elevenlabs_tts.httpx, method, getattr(client, method))
        backend = ElevenLabsTTSBackend(api_key=_KEY)
        with pytest.raises(RuntimeError, match="ElevenLabs request failed") as caught:
            if operation == "synthesize":
                backend.synthesize("A synthetic sample.")
            else:
                backend.available_voices()
    assert received == [_KEY]
    assert _KEY not in "".join(traceback.format_exception(caught.value))
    assert _KEY not in caplog.text
