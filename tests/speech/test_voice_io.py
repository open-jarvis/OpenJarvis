"""Timing behavior for microphone silence detection."""

from __future__ import annotations

import struct
import sys
from types import SimpleNamespace

from openjarvis.speech.voice_io import BargeInMonitor, _play_loop, record_until_silence


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


# -- barge-in (speak over Jarvis to interrupt him) ---------------------------


def _loud_chunk() -> bytes:
    return struct.pack("<400h", *([20000] * 400))


def _quiet_chunk() -> bytes:
    return b"\x00" * 800


def test_monitor_latches_after_sustained_loud_chunks() -> None:
    monitor = BargeInMonitor(sustained_chunks=3)
    assert monitor._register_energy(_loud_chunk()) is False
    assert monitor._register_energy(_loud_chunk()) is False
    assert monitor._register_energy(_loud_chunk()) is True
    assert monitor.triggered is True
    assert monitor.consume() is True
    assert monitor.triggered is False


def test_monitor_resets_counter_on_silence() -> None:
    monitor = BargeInMonitor(sustained_chunks=3)
    monitor._register_energy(_loud_chunk())
    monitor._register_energy(_loud_chunk())
    monitor._register_energy(_quiet_chunk())
    assert monitor._register_energy(_loud_chunk()) is False


def test_play_loop_returns_false_when_interrupted() -> None:
    class _FakeStream:
        active = True

    class _FakeSD:
        def __init__(self) -> None:
            self.stopped = False
            self.stream = _FakeStream()

        def play(self, data, sr) -> None:
            pass

        def get_stream(self):
            return self.stream

        def stop(self) -> None:
            self.stopped = True

        def wait(self) -> None:
            pass

    sd = _FakeSD()
    result = _play_loop(sd, b"audio", 24000, interrupt_check=lambda: True)
    assert result is False
    assert sd.stopped is True


def test_play_loop_returns_true_when_playback_finishes() -> None:
    class _FakeStream:
        def __init__(self) -> None:
            self.active = True

    class _FakeSD:
        def __init__(self) -> None:
            self.stream = _FakeStream()

        def play(self, data, sr) -> None:
            pass

        def get_stream(self):
            # Simulate playback finishing after the first poll.
            self.stream.active = False
            return self.stream

        def stop(self) -> None:
            raise AssertionError("must not stop a finished stream")

        def wait(self) -> None:
            pass

    result = _play_loop(_FakeSD(), b"audio", 24000, interrupt_check=lambda: False)
    assert result is True


def test_play_loop_without_interrupt_check_blocks() -> None:
    class _FakeSD:
        def __init__(self) -> None:
            self.played = False
            self.waited = False

        def play(self, data, sr) -> None:
            self.played = True

        def wait(self) -> None:
            self.waited = True

    sd = _FakeSD()
    assert _play_loop(sd, b"audio", 24000, interrupt_check=None) is True
    assert sd.played and sd.waited
