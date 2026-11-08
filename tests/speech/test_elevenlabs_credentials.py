"""Keep ElevenLabs credentials out of provider errors and downstream logs."""

from __future__ import annotations

import logging
import traceback
from unittest.mock import Mock

import httpx
import pytest

from openjarvis.speech import elevenlabs_tts
from openjarvis.speech.elevenlabs_tts import ElevenLabsTTSBackend

_KEY = "sk_" + "a" * 48


@pytest.mark.parametrize("source", ["argument", "environment"])
def test_key_whitespace_is_normalized_before_request(monkeypatch, source):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    key = f" \t{_KEY}\r\n"
    if source == "environment":
        monkeypatch.setenv("ELEVENLABS_API_KEY", key)
        backend = ElevenLabsTTSBackend()
    else:
        backend = ElevenLabsTTSBackend(api_key=key)
    post = Mock(
        return_value=httpx.Response(
            200,
            content=b"audio",
            request=httpx.Request("POST", "https://api.elevenlabs.io/v1/test"),
        )
    )
    monkeypatch.setattr(elevenlabs_tts.httpx, "post", post)

    assert backend.synthesize("hello").audio == b"audio"
    assert post.call_args.kwargs["headers"]["xi-api-key"] == _KEY


@pytest.mark.parametrize("source", ["argument", "environment"])
def test_whitespace_only_key_is_unconfigured(monkeypatch, source):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    if source == "environment":
        monkeypatch.setenv("ELEVENLABS_API_KEY", " \r\n\t")
        backend = ElevenLabsTTSBackend()
    else:
        backend = ElevenLabsTTSBackend(api_key=" \r\n\t")
    assert not backend.health()
    assert backend.available_voices() == []
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY not set"):
        backend.synthesize("hello")


@pytest.mark.parametrize(
    "bad_key",
    [_KEY + "\nextra", _KEY + "\x00extra", _KEY + " internal", _KEY + "\u00e9"],
)
def test_invalid_key_is_rejected_without_revealing_it(monkeypatch, bad_key):
    post = Mock()
    monkeypatch.setattr(elevenlabs_tts.httpx, "post", post)
    with pytest.raises(ValueError, match="ElevenLabs API key") as caught:
        ElevenLabsTTSBackend(api_key=bad_key).synthesize("hello")
    assert _KEY not in "".join(traceback.format_exception(caught.value))
    post.assert_not_called()


@pytest.mark.parametrize("operation", ["synthesize", "available_voices"])
@pytest.mark.parametrize(
    "error_type",
    [
        httpx.ConnectError,
        httpx.ReadError,
        httpx.ReadTimeout,
        httpx.LocalProtocolError,
        ValueError,
    ],
)
def test_request_errors_do_not_reveal_keys(monkeypatch, caplog, operation, error_type):
    backend = ElevenLabsTTSBackend(api_key=_KEY)
    request = Mock(side_effect=error_type(f"provider diagnostic containing {_KEY}"))
    monkeypatch.setattr(
        elevenlabs_tts.httpx, "post" if operation == "synthesize" else "get", request
    )
    with pytest.raises(RuntimeError, match="ElevenLabs request failed") as caught:
        if operation == "synthesize":
            backend.synthesize("hello")
        else:
            backend.available_voices()
    try:
        raise caught.value
    except RuntimeError:
        logging.getLogger(__name__).exception("Speech request failed")
    assert _KEY not in str(caught.value)
    assert _KEY not in "".join(traceback.format_exception(caught.value))
    assert _KEY not in caplog.text


@pytest.mark.parametrize("operation", ["synthesize", "available_voices"])
def test_status_errors_keep_status_without_provider_body(monkeypatch, operation):
    response = httpx.Response(
        401,
        text=f"echoed credential {_KEY}",
        request=httpx.Request("POST", "https://api.elevenlabs.io/v1/" + _KEY),
    )
    monkeypatch.setattr(
        elevenlabs_tts.httpx,
        "post" if operation == "synthesize" else "get",
        Mock(return_value=response),
    )
    backend = ElevenLabsTTSBackend(api_key=_KEY)
    with pytest.raises(RuntimeError, match="HTTP 401") as caught:
        if operation == "synthesize":
            backend.synthesize("hello")
        else:
            backend.available_voices()
    assert _KEY not in "".join(traceback.format_exception(caught.value))


def test_invalid_voice_response_hides_provider_diagnostics(monkeypatch):
    response = Mock()
    response.json.side_effect = ValueError(f"malformed payload {_KEY}")
    monkeypatch.setattr(elevenlabs_tts.httpx, "get", Mock(return_value=response))
    with pytest.raises(RuntimeError, match="ElevenLabs request failed") as caught:
        ElevenLabsTTSBackend(api_key=_KEY).available_voices()
    assert _KEY not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "payload",
    [{"voices": "invalid"}, {"voices": [{}]}, {"voices": [{"voice_id": 123}]}],
)
def test_malformed_voice_entries_are_rejected(monkeypatch, payload):
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "https://api.elevenlabs.io/v1/voices"),
    )
    monkeypatch.setattr(elevenlabs_tts.httpx, "get", Mock(return_value=response))
    with pytest.raises(RuntimeError, match="ElevenLabs request failed"):
        ElevenLabsTTSBackend(api_key=_KEY).available_voices()
