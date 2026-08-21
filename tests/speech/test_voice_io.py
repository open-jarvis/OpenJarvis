"""Timing behavior for microphone silence detection."""

from __future__ import annotations

import struct
import sys
from types import SimpleNamespace

from openjarvis.speech.voice_io import record_until_silence


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
