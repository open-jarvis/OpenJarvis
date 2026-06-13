"""Microphone recording with silence detection and audio playback helpers."""

from __future__ import annotations

import io
import wave
from typing import Optional

_SAMPLE_RATE = 16000
_CHANNELS = 1
_CHUNK = 1024
_SILENCE_THRESHOLD = 500      # RMS below this → silence
_SILENCE_SECONDS = 1.5        # seconds of silence before auto-stop
_MAX_RECORD_SECONDS = 30      # safety ceiling


def _rms(data: bytes) -> float:
    """Compute RMS amplitude of 16-bit PCM bytes."""
    import struct

    n = len(data) // 2
    if n == 0:
        return 0.0
    shorts = struct.unpack(f"{n}h", data[:n * 2])
    return (sum(s * s for s in shorts) / n) ** 0.5


def record_until_silence(
    *,
    sample_rate: int = _SAMPLE_RATE,
    silence_threshold: int = _SILENCE_THRESHOLD,
    silence_seconds: float = _SILENCE_SECONDS,
    max_seconds: float = _MAX_RECORD_SECONDS,
) -> bytes:
    """Record from the default microphone until silence is detected.

    Returns raw WAV bytes (16-bit mono).
    Raises RuntimeError if sounddevice/numpy are not installed.
    """
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        raise RuntimeError(
            "sounddevice and numpy are required for voice input. "
            "Install with: pip install sounddevice numpy"
        )

    chunks_per_second = sample_rate / _CHUNK
    silence_chunks = int(silence_seconds * chunks_per_second)
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


def play_wav(audio: bytes, sample_rate: int = 24000) -> None:
    """Play raw WAV bytes through the default output device.

    If the bytes are a valid WAV file, sample rate is read from the header;
    otherwise ``sample_rate`` is used as a fallback.
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
        data = np.array(struct.unpack(f"{n}h", audio[:n * 2]), dtype="float32") / 32768.0
        sr = sample_rate

    sd.play(data, sr)
    sd.wait()


__all__ = ["play_wav", "record_until_silence"]
