"""Microphone recording with silence detection and audio playback helpers."""

from __future__ import annotations

import io
import threading
import time
import wave
from typing import Any, Callable

_SAMPLE_RATE = 16000
_CHANNELS = 1
_CHUNK = 1024
_SILENCE_THRESHOLD = 500  # RMS below this → silence
_SILENCE_SECONDS = 1.5  # seconds of silence before auto-stop
_STARTUP_SILENCE_SECONDS = 5.0  # give up early if speech never begins
_MAX_RECORD_SECONDS = 30  # safety ceiling


def _rms(data: bytes) -> float:
    """Compute RMS amplitude of 16-bit PCM bytes."""
    import struct

    n = len(data) // 2
    if n == 0:
        return 0.0
    shorts = struct.unpack(f"{n}h", data[: n * 2])
    return (sum(s * s for s in shorts) / n) ** 0.5


def record_until_silence(
    *,
    sample_rate: int = _SAMPLE_RATE,
    silence_threshold: int = _SILENCE_THRESHOLD,
    silence_seconds: float = _SILENCE_SECONDS,
    startup_silence_seconds: float = _STARTUP_SILENCE_SECONDS,
    max_seconds: float = _MAX_RECORD_SECONDS,
) -> bytes:
    """Record from the default microphone until silence is detected.

    Returns raw WAV bytes (16-bit mono).
    Raises RuntimeError if sounddevice is not installed.
    """
    try:
        import sounddevice as sd
    except ImportError:
        raise RuntimeError(
            "sounddevice is required for voice input. "
            "Install with: pip install sounddevice"
        )

    chunks_per_second = sample_rate / _CHUNK
    silence_chunks = int(silence_seconds * chunks_per_second)
    startup_silence_chunks = max(1, int(startup_silence_seconds * chunks_per_second))
    max_chunks = int(max_seconds * chunks_per_second)

    frames: list[bytes] = []
    silence_count = 0
    has_speech = False

    with sd.RawInputStream(
        samplerate=sample_rate,
        channels=_CHANNELS,
        dtype="int16",
        blocksize=_CHUNK,
    ) as stream:
        for _ in range(max_chunks):
            raw, _ = stream.read(_CHUNK)
            data = bytes(raw)
            frames.append(data)

            amplitude = _rms(data)
            if amplitude > silence_threshold:
                has_speech = True
                silence_count = 0
            elif not has_speech and len(frames) >= startup_silence_chunks:
                break
            elif has_speech:
                silence_count += 1
                if silence_count >= silence_chunks:
                    break

    return _frames_to_wav(frames, sample_rate)


def _frames_to_wav(frames: list[bytes], sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"".join(frames))
    return buf.getvalue()


def _play_loop(sd: Any, data: Any, sr: int, interrupt_check: Any) -> bool:
    """Play *data* via an ``sounddevice``-like object, honouring barge-in.

    Returns ``False`` when *interrupt_check* fired (playback stopped early),
    ``True`` when the audio finished playing.
    """
    if interrupt_check is None:
        sd.play(data, sr)
        sd.wait()
        return True

    sd.play(data, sr)
    try:
        while sd.get_stream().active:
            if interrupt_check():
                sd.stop()
                return False
            time.sleep(0.05)
    except RuntimeError:
        # No stream is playing (device raced us); nothing to interrupt.
        pass
    return True


def play_wav(
    audio: bytes,
    sample_rate: int = 24000,
    *,
    interrupt_check: "Callable[[], bool] | None" = None,
) -> bool:
    """Play raw WAV bytes through the default output device.

    If the bytes are a valid WAV file, sample rate is read from the header;
    otherwise ``sample_rate`` is used as a fallback.

    When *interrupt_check* is provided it is polled during playback (barge-in):
    returning ``True`` stops the audio immediately and this returns ``False``.
    Without it, playback blocks until the audio finishes and returns ``True``.
    """
    try:
        import numpy as np
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        raise RuntimeError(
            "sounddevice, numpy, and soundfile are required for voice output. "
            "Install with: pip install sounddevice numpy soundfile"
        )

    buf = io.BytesIO(audio)
    try:
        data, sr = sf.read(buf, dtype="float32")
    except Exception:
        # Fall back: treat as raw PCM
        import struct

        n = len(audio) // 2
        data = (
            np.array(struct.unpack(f"{n}h", audio[: n * 2]), dtype="float32") / 32768.0
        )
        sr = sample_rate

    return _play_loop(sd, data, sr, interrupt_check)


class BargeInMonitor:
    """Watches the microphone for user speech while Jarvis is talking.

    A background thread streams the microphone and latches ``triggered`` when
    several consecutive chunks exceed the energy threshold — the "speak over
    Jarvis to interrupt him" pattern. Pass :meth:`consume` to
    :func:`play_wav` as its *interrupt_check*.

    Note: there is no acoustic echo cancellation; with speakers + an open
    microphone the monitor can pick up Jarvis's own voice. Works best with
    headphones, or disable via ``JARVIS_BARGE_IN=0``.
    """

    def __init__(
        self,
        *,
        sample_rate: int = _SAMPLE_RATE,
        chunk: int = _CHUNK,
        energy_threshold: int = _SILENCE_THRESHOLD,
        sustained_chunks: int = 3,
        stream_factory: "Callable[[], Any] | None" = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._chunk = chunk
        self._energy_threshold = energy_threshold
        self._sustained_chunks = sustained_chunks
        self._stream_factory = stream_factory
        self._triggered = False
        self._sustained = 0
        self._failed = False
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        """Start monitoring. Returns ``False`` when no audio backend exists."""
        if self._thread is not None:
            return not self._failed
        self._thread = threading.Thread(
            target=self._run,
            name="barge-in-monitor",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Stop monitoring (idempotent)."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        try:
            import sounddevice as sd

            factory = self._stream_factory or (
                lambda: sd.RawInputStream(
                    samplerate=self._sample_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=self._chunk,
                )
            )
            with factory() as stream:
                while not self._stop.is_set():
                    raw, _ = stream.read(self._chunk)
                    self._register_energy(bytes(raw))
        except Exception:  # noqa: BLE001 — no mic means no barge-in
            self._failed = True

    def _register_energy(self, chunk: bytes) -> bool:
        """Count sustained loud chunks; latch the trigger. Returns triggered."""
        with self._lock:
            if _rms(chunk) > self._energy_threshold:
                self._sustained += 1
            else:
                self._sustained = 0
            if self._sustained >= self._sustained_chunks:
                self._triggered = True
                self._sustained = 0
            return self._triggered

    @property
    def triggered(self) -> bool:
        with self._lock:
            return self._triggered

    def consume(self) -> bool:
        """Return and clear the trigger flag (use as ``interrupt_check``)."""
        with self._lock:
            value = self._triggered
            self._triggered = False
            return value

    @property
    def failed(self) -> bool:
        """True when the monitor could not open the microphone."""
        return self._failed


__all__ = ["BargeInMonitor", "play_wav", "record_until_silence"]
