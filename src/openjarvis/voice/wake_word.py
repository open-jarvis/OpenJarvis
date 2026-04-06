"""Wake-word detection for the Jarvis voice loop.

Two modes are supported:

``keyword`` (default, no extra dependencies)
    Transcribes a short audio buffer with the active STT backend and
    checks whether the transcript contains the configured wake keyword
    (e.g. ``"jarvis"``).  The command is the text *after* the keyword.

``openwakeword`` (optional)
    Runs `OpenWakeWord <https://github.com/dscripka/openWakeWord>`_ on
    the raw audio stream for real-time, low-latency detection with no
    full STT needed in the hot path.  Requires ``openwakeword>=0.6``.
    Install via ``uv sync --extra voice-wakeword``.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class WakeWordResult:
    """Outcome of a wake-word check."""

    __slots__ = ("detected", "command", "full_text", "confidence")

    def __init__(
        self,
        detected: bool,
        command: str = "",
        full_text: str = "",
        confidence: float = 1.0,
    ) -> None:
        self.detected = detected
        self.command = command          # Text after the wake word
        self.full_text = full_text      # Full transcribed text
        self.confidence = confidence


class WakeWordDetector:
    """Detects the wake word in transcribed text or a raw audio stream.

    Parameters
    ----------
    keyword:
        The wake-word string to listen for (case-insensitive).
        Defaults to ``"jarvis"``.
    engine:
        ``"keyword"`` or ``"openwakeword"``.
    """

    def __init__(
        self,
        keyword: str = "jarvis",
        engine: str = "keyword",
    ) -> None:
        self.keyword = keyword.lower().strip()
        self.engine = engine
        self._oww_model: Optional[object] = None

        if engine == "openwakeword":
            self._init_oww()

    # ------------------------------------------------------------------
    # openwakeword initialisation
    # ------------------------------------------------------------------

    def _init_oww(self) -> None:
        try:
            import openwakeword  # type: ignore[import]
            from openwakeword.model import Model  # type: ignore[import]

            self._oww_model = Model(inference_framework="onnx")
            logger.debug("openwakeword model loaded.")
        except ImportError:
            logger.warning(
                "openwakeword not installed — falling back to keyword mode. "
                "Install with: pip install openwakeword"
            )
            self.engine = "keyword"

    # ------------------------------------------------------------------
    # Keyword mode
    # ------------------------------------------------------------------

    def check_transcript(self, text: str) -> WakeWordResult:
        """Check a transcription string for the wake keyword.

        Returns a ``WakeWordResult`` with:
        - ``detected``: True if the keyword appears in the text.
        - ``command``: The portion of text *after* the keyword.
        - ``full_text``: The complete transcription.
        """
        lower = text.lower()
        idx = lower.find(self.keyword)
        if idx == -1:
            return WakeWordResult(detected=False, full_text=text)

        after = text[idx + len(self.keyword):].strip()
        # Strip leading punctuation that sometimes follows the keyword
        for ch in (",", ".", "!", "?", ":"):
            after = after.lstrip(ch).strip()

        return WakeWordResult(
            detected=True,
            command=after,
            full_text=text,
            confidence=1.0,
        )

    # ------------------------------------------------------------------
    # openwakeword streaming
    # ------------------------------------------------------------------

    def predict_chunk(self, audio_chunk_int16: bytes) -> Tuple[bool, float]:
        """Run an OWW prediction on a raw PCM chunk.

        Returns ``(triggered, confidence)`` — confidence in [0, 1].
        Only valid when ``engine == "openwakeword"`` and the model is loaded.
        """
        if self._oww_model is None:
            return False, 0.0

        import numpy as np

        audio_np = np.frombuffer(audio_chunk_int16, dtype=np.int16)
        # OWW expects int16 numpy arrays at 16 kHz
        prediction = self._oww_model.predict(audio_np)  # type: ignore[union-attr]

        # prediction is a dict of {model_name: score}
        if not prediction:
            return False, 0.0

        best_score = max(prediction.values())
        triggered = best_score >= 0.5
        return triggered, float(best_score)
