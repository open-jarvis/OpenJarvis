"""Voice Activity Detection for the Jarvis voice loop.

Two engines are supported, selected at runtime:

``energy`` (default, zero extra dependencies)
    Simple RMS-threshold detector.  Fast and works on all platforms.

``webrtcvad`` (optional upgrade)
    Google's WebRTC VAD — much more accurate, especially in noisy
    environments.  Requires ``webrtcvad`` (Linux/macOS) or
    ``webrtcvad-wheels`` (Windows).  Install via ``uv sync --extra voice-vad``.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Iterator, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rms(frame_bytes: bytes) -> float:
    """RMS amplitude of a 16-bit PCM frame, normalised to [0, 1]."""
    import struct

    n = len(frame_bytes) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", frame_bytes)
    mean_sq = sum(s * s for s in samples) / n
    return (mean_sq ** 0.5) / 32768.0


# ---------------------------------------------------------------------------
# VoiceActivityDetector
# ---------------------------------------------------------------------------


class VoiceActivityDetector:
    """Detects whether an audio frame contains speech.

    Parameters
    ----------
    engine:
        ``"energy"`` or ``"webrtcvad"``.
    aggressiveness:
        WebRTC VAD aggressiveness 0–3 (higher = more aggressive in
        filtering non-speech).  Ignored for energy mode.
    energy_threshold:
        RMS threshold in [0, 1] for the energy engine (default 0.015).
    sample_rate:
        Audio sample rate in Hz (must be 8000/16000/32000/48000 for webrtcvad).
    silence_timeout_ms:
        How many milliseconds of consecutive silence mark end-of-utterance.
    min_speech_ms:
        Minimum voiced duration (ms) before an utterance is accepted.
    frame_ms:
        Duration of each audio frame in milliseconds.
    pre_roll_ms:
        How many milliseconds of audio to keep *before* speech onset (ring
        buffer), so the first syllable isn't clipped.
    """

    def __init__(
        self,
        engine: str = "energy",
        aggressiveness: int = 2,
        energy_threshold: float = 0.015,
        sample_rate: int = 16_000,
        silence_timeout_ms: int = 1_500,
        min_speech_ms: int = 300,
        frame_ms: int = 30,
        pre_roll_ms: int = 300,
    ) -> None:
        self.sample_rate = sample_rate
        self.silence_timeout_ms = silence_timeout_ms
        self.min_speech_ms = min_speech_ms
        self.frame_ms = frame_ms
        self.pre_roll_ms = pre_roll_ms

        # Derived frame counts
        self._silence_frames = max(1, silence_timeout_ms // frame_ms)
        self._min_voiced_frames = max(1, min_speech_ms // frame_ms)
        self._pre_roll_frames = max(1, pre_roll_ms // frame_ms)

        self._engine = engine
        self._energy_threshold = energy_threshold
        self._webrtc_vad: Optional[object] = None

        if engine == "webrtcvad":
            self._init_webrtcvad(aggressiveness)

    # ------------------------------------------------------------------
    # Engine initialisation
    # ------------------------------------------------------------------

    def _init_webrtcvad(self, aggressiveness: int) -> None:
        try:
            import webrtcvad  # type: ignore[import]

            self._webrtc_vad = webrtcvad.Vad(aggressiveness)
            logger.debug("Using webrtcvad (aggressiveness=%d)", aggressiveness)
        except ImportError:
            logger.warning(
                "webrtcvad not installed — falling back to energy VAD. "
                "Install with: pip install webrtcvad-wheels (Windows) "
                "or webrtcvad (Linux/macOS)."
            )
            self._engine = "energy"

    # ------------------------------------------------------------------
    # Frame-level speech detection
    # ------------------------------------------------------------------

    def is_speech(self, frame_bytes: bytes) -> bool:
        """Return True if ``frame_bytes`` contains speech."""
        if self._engine == "webrtcvad" and self._webrtc_vad is not None:
            try:
                return self._webrtc_vad.is_speech(frame_bytes, self.sample_rate)  # type: ignore[union-attr]
            except Exception:
                pass
        # Energy fallback
        return _rms(frame_bytes) > self._energy_threshold

    # ------------------------------------------------------------------
    # Utterance collection
    # ------------------------------------------------------------------

    def collect_utterance(
        self, frame_stream: Iterator[bytes]
    ) -> Optional[bytes]:
        """Consume frames from *frame_stream* and return a complete utterance.

        Returns the raw PCM bytes of the utterance (speech + brief trailing
        silence), or ``None`` if the stream ended before any speech was found.

        The algorithm:
        1. Maintain a short ring buffer (pre-roll) of recent frames.
        2. When consecutive voiced frames exceed ``_min_voiced_frames``,
           mark onset — prepend the ring buffer so we don't clip the start.
        3. Continue collecting until ``_silence_frames`` consecutive
           non-speech frames are seen after onset.
        """
        ring: deque[bytes] = deque(maxlen=self._pre_roll_frames)
        speech_frames: list[bytes] = []
        in_speech = False
        voiced_streak = 0
        silence_streak = 0

        for frame in frame_stream:
            is_voiced = self.is_speech(frame)

            if not in_speech:
                ring.append(frame)
                if is_voiced:
                    voiced_streak += 1
                    if voiced_streak >= self._min_voiced_frames:
                        # Speech onset confirmed
                        in_speech = True
                        speech_frames.extend(ring)  # include pre-roll
                        ring.clear()
                else:
                    voiced_streak = 0
            else:
                speech_frames.append(frame)
                if not is_voiced:
                    silence_streak += 1
                    if silence_streak >= self._silence_frames:
                        break  # End of utterance
                else:
                    silence_streak = 0

        if not in_speech or not speech_frames:
            return None

        return b"".join(speech_frames)
