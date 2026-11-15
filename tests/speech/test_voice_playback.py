"""WAV decoding and gapless stream playback for spoken replies."""

from __future__ import annotations

import io
import struct
import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from openjarvis.speech.voice_io import StreamPlayer, decode_audio


def _wav(samples: list[int], rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# decode_audio
# ---------------------------------------------------------------------------


def test_decode_pcm16_wav_reads_rate_and_scales_to_float():
    samples, rate = decode_audio(_wav([0, 16384, -32768], rate=22050))
    assert rate == 22050
    assert samples.dtype == np.float32
    assert samples.tolist() == pytest.approx([0.0, 0.5, -1.0])


def test_decode_stereo_wav_is_downmixed_to_mono():
    samples, _ = decode_audio(_wav([16384, 0, -16384, 0], channels=2))
    assert samples.tolist() == pytest.approx([0.25, -0.25])


def test_decode_non_wav_bytes_falls_back_to_raw_pcm(monkeypatch):
    monkeypatch.setitem(sys.modules, "soundfile", None)  # force the raw path
    samples, rate = decode_audio(struct.pack("<2h", 16384, -16384), sample_rate=8000)
    assert rate == 8000
    assert samples.tolist() == pytest.approx([0.5, -0.5])


# ---------------------------------------------------------------------------
# StreamPlayer
# ---------------------------------------------------------------------------


class _FakeOutputStream:
    def __init__(self, log: list, **kwargs) -> None:
        self.log = log
        self.rate = kwargs["samplerate"]
        log.append(("open", self.rate))

    def start(self):
        self.log.append(("start", self.rate))

    def write(self, data):
        assert data.dtype == np.float32 and data.shape[1] == 1
        self.log.append(("write", self.rate, len(data)))

    def stop(self):
        self.log.append(("stop", self.rate))

    def abort(self):
        self.log.append(("abort", self.rate))

    def close(self):
        self.log.append(("close", self.rate))


@pytest.fixture
def device(monkeypatch) -> list:
    log: list = []
    fake_sd = SimpleNamespace(OutputStream=lambda **kw: _FakeOutputStream(log, **kw))
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    return log


def test_player_holds_back_audio_until_the_prebuffer_fills(device):
    player = StreamPlayer(prebuffer_seconds=0.25)
    player.write(np.zeros(1000, dtype=np.float32), 8000)  # 0.125 s
    assert device == []
    player.write(np.zeros(1000, dtype=np.float32), 8000)  # 0.25 s: start
    assert device == [
        ("open", 8000),
        ("start", 8000),
        ("write", 8000, 1000),
        ("write", 8000, 1000),
    ]
    player.write(np.zeros(500, dtype=np.float32), 8000)  # streamed directly
    assert device[-1] == ("write", 8000, 500)


def test_close_plays_out_a_reply_shorter_than_the_prebuffer(device):
    player = StreamPlayer(prebuffer_seconds=1.0)
    player.write(np.zeros(100, dtype=np.float32), 8000)
    player.close()
    assert device == [
        ("open", 8000),
        ("start", 8000),
        ("write", 8000, 100),
        ("stop", 8000),
        ("close", 8000),
    ]


def test_sample_rate_change_drains_and_reopens(device):
    player = StreamPlayer(prebuffer_seconds=0.0)
    player.write(np.zeros(10, dtype=np.float32), 8000)
    player.write(np.zeros(10, dtype=np.float32), 16000)
    player.close()
    events = [e[0] + "@" + str(e[1]) for e in device]
    assert events == [
        "open@8000",
        "start@8000",
        "write@8000",
        "stop@8000",
        "close@8000",
        "open@16000",
        "start@16000",
        "write@16000",
        "stop@16000",
        "close@16000",
    ]


def test_writes_are_split_into_short_blocks(device):
    player = StreamPlayer(prebuffer_seconds=0.0)
    player.write(np.zeros(2500, dtype=np.float32), 8000)
    assert [e[2] for e in device if e[0] == "write"] == [1024, 1024, 452]


def test_interrupt_from_another_thread_stops_writing_without_touching_device(
    device,
):
    player = StreamPlayer(prebuffer_seconds=0.0)
    player.write(np.zeros(10, dtype=np.float32), 8000)
    player.interrupt()  # e.g. Ctrl-C handled on the main thread
    player.write(np.zeros(5000, dtype=np.float32), 8000)
    assert [e[0] for e in device] == ["open", "start", "write"]
    player.abort()  # the playing thread then releases the device
    assert [e[0] for e in device][-2:] == ["abort", "close"]


def test_play_wav_silences_the_device_on_ctrl_c(monkeypatch):
    pytest.importorskip("soundfile")
    from openjarvis.speech.voice_io import play_wav

    calls: list[str] = []

    class _Stream:
        checks = 0

        @property
        def active(self):
            _Stream.checks += 1
            if _Stream.checks == 2:  # Ctrl-C while the clip is playing
                raise KeyboardInterrupt
            return True

    fake_sd = SimpleNamespace(
        play=lambda data, sr: calls.append("play"),
        get_stream=lambda: _Stream(),
        stop=lambda: calls.append("stop"),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    with pytest.raises(KeyboardInterrupt):
        play_wav(_wav([0] * 100))
    assert calls == ["play", "stop"]


def test_abort_discards_queued_audio(device):
    player = StreamPlayer(prebuffer_seconds=0.0)
    player.write(np.zeros(10, dtype=np.float32), 8000)
    player.abort()
    player.close()  # nothing left to play
    assert [e[0] for e in device] == ["open", "start", "write", "abort", "close"]
