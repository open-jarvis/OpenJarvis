"""Microphone input and audio playback for the Jarvis voice loop.

Dependencies (install via ``uv sync --extra voice``):
    sounddevice  — cross-platform audio I/O
    soundfile    — WAV decoding for playback
    numpy        — array handling
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

# Default audio parameters — 16 kHz mono int16 (Whisper-compatible)
SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "int16"
FRAME_MS = 30  # 30 ms frames (compatible with webrtcvad)
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)  # 480 samples


# ---------------------------------------------------------------------------
# Microphone stream
# ---------------------------------------------------------------------------


class MicrophoneStream:
    """Yields raw PCM bytes from the default (or named) microphone.

    Each yielded chunk is exactly ``frame_ms`` milliseconds of 16-bit
    mono audio at ``sample_rate`` Hz — ready to pass to the VAD.

    Usage::

        stream = MicrophoneStream()
        for frame in stream.frames():
            process(frame)
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        frame_ms: int = FRAME_MS,
        device: Optional[str] = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.device = device or None  # None → system default
        self._frame_samples = int(sample_rate * frame_ms / 1000)

    def frames(self) -> Iterator[bytes]:
        """Open the microphone and yield PCM byte frames indefinitely.

        Raises ``ImportError`` if sounddevice is not installed.
        Stops when the caller breaks or the generator is garbage-collected.
        """
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise ImportError(
                "sounddevice is required for the voice loop.\n"
                "Install with:  uv sync --extra voice"
            ) from exc

        import numpy as np

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            device=self.device,
            blocksize=self._frame_samples,
        ) as stream:
            logger.debug(
                "Microphone open: %d Hz, %d ms frames, device=%s",
                self.sample_rate,
                self.frame_ms,
                self.device,
            )
            while True:
                block, _overflowed = stream.read(self._frame_samples)
                yield block.astype(np.int16).tobytes()


# ---------------------------------------------------------------------------
# PCM helpers
# ---------------------------------------------------------------------------


def pcm_to_wav(
    pcm_bytes: bytes,
    sample_rate: int = SAMPLE_RATE,
    channels: int = CHANNELS,
) -> bytes:
    """Wrap raw int16 PCM bytes in a WAV container (stdlib only)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit → 2 bytes per sample
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Audio playback
# ---------------------------------------------------------------------------


class AudioPlayer:
    """Plays WAV audio bytes through the default (or named) speaker.

    Requires ``sounddevice`` and ``soundfile``.
    """

    def __init__(self, device: Optional[str] = None) -> None:
        self.device = device or None

    def play(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        sample_rate: int = 24_000,
    ) -> None:
        """Decode and play audio bytes, blocking until playback finishes.

        Parameters
        ----------
        audio:
            Raw audio bytes (WAV preferred; MP3 supported if soundfile
            can read it — requires libsndfile with MP3 support).
        format:
            Audio container format hint (``"wav"``, ``"mp3"``).
        sample_rate:
            Fallback sample rate used only when the header is absent.
        """
        try:
            import sounddevice as sd
            import soundfile as sf
        except ImportError as exc:
            raise ImportError(
                "sounddevice and soundfile are required for audio playback.\n"
                "Install with:  uv sync --extra voice"
            ) from exc

        buf = io.BytesIO(audio)
        try:
            data, sr = sf.read(buf, dtype="float32", always_2d=False)
        except Exception:
            # soundfile couldn't decode (e.g. raw mp3 without proper header).
            # Fall back: assume raw float32 PCM at the given sample_rate.
            import numpy as np

            data = np.frombuffer(audio, dtype="float32")
            sr = sample_rate

        sd.play(data, sr, device=self.device)
        sd.wait()
        logger.debug("Playback complete (%.2f s)", len(data) / sr)
