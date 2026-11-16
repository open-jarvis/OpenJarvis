"""Timing behavior for microphone silence detection."""

from __future__ import annotations

import struct
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from openjarvis.speech.voice_io import play_audio_file, record_until_silence


class _FakeStream:
    def __init__(self, frames: list[bytes]) -> None:
        self.frames = iter(frames)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def read(self, chunk: int):
        self.reads += 1
        return next(self.frames), False


def _install_audio(monkeypatch, stream: _FakeStream) -> None:
    fake_sd = SimpleNamespace(RawInputStream=lambda **kwargs: stream)
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)


def test_initial_silence_stops_at_startup_timeout(monkeypatch) -> None:
    silence = bytes(1024 * 2)
    stream = _FakeStream([silence] * 30)
    _install_audio(monkeypatch, stream)

    record_until_silence(
        sample_rate=1024,
        startup_silence_seconds=2,
        max_seconds=30,
    )

    assert stream.reads == 2


def test_post_speech_uses_normal_silence_window(monkeypatch) -> None:
    speech = struct.pack("1024h", *([1000] * 1024))
    silence = bytes(1024 * 2)
    stream = _FakeStream([speech, silence, silence, silence])
    _install_audio(monkeypatch, stream)

    record_until_silence(
        sample_rate=1024,
        silence_seconds=2,
        startup_silence_seconds=1,
        max_seconds=30,
    )

    assert stream.reads == 3


def _install_playback(monkeypatch, read):
    device = SimpleNamespace(play=Mock(), wait=Mock(), stop=Mock())
    monkeypatch.setitem(sys.modules, "sounddevice", device)
    monkeypatch.setitem(sys.modules, "soundfile", SimpleNamespace(read=read))
    return device


def test_play_audio_file_uses_the_decoded_sample_rate(tmp_path, monkeypatch):
    samples = object()
    read = Mock(return_value=(samples, 44100))
    device = _install_playback(monkeypatch, read)
    path = tmp_path / "digest.mp3"

    play_audio_file(path)

    read.assert_called_once_with(str(path), dtype="float32")
    device.play.assert_called_once_with(samples, 44100)
    device.wait.assert_called_once()
    device.stop.assert_called_once()


def test_play_audio_file_does_not_treat_decode_failures_as_raw_pcm(monkeypatch):
    device = _install_playback(
        monkeypatch, Mock(side_effect=RuntimeError("unsupported audio"))
    )
    with pytest.raises(RuntimeError, match="unsupported audio"):
        play_audio_file("invalid.mp3")
    device.play.assert_not_called()


@pytest.mark.parametrize(
    "failure", [RuntimeError("device failed"), KeyboardInterrupt()]
)
def test_play_audio_file_stops_on_failure_or_interrupt(monkeypatch, failure):
    device = _install_playback(monkeypatch, Mock(return_value=(object(), 16000)))
    device.wait.side_effect = failure
    with pytest.raises(type(failure)):
        play_audio_file("digest.wav")
    device.stop.assert_called_once()
