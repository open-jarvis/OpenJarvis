"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import os
import tempfile
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
        *,
        default_language: str = "en",
        task: str = "transcribe",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._default_language = default_language or "en"
        self._task = task if task in ("transcribe", "translate") else "transcribe"
        self._model: Optional[WhisperModel] = None

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use."""
        if self._model is None:
            if WhisperModel is None:
                raise ImportError(
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra speech"
                )
            self._model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=self._compute_type,
            )
        return self._model

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        model = self._ensure_model()

        # Write audio to a temp file (faster-whisper needs a file path).
        # delete=False: on Windows the open handle blocks transcribe reads.
        suffix = f".{format}" if not format.startswith(".") else format
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            with open(tmp_path, "wb") as fh:
                fh.write(audio)

            lang = language or self._default_language
            kwargs: dict = {
                "language": lang,
                "task": self._task,
                # Browser mic clips are short/quiet — VAD often drops real speech.
                "vad_filter": False,
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.5,
                "log_prob_threshold": -1.0,
                "compression_ratio_threshold": 2.4,
            }

            segments_iter, info = model.transcribe(tmp_path, **kwargs)
            segments_list = list(segments_iter)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        # Build result
        text = "".join(seg.text for seg in segments_list).strip()
        segments = [
            Segment(
                text=seg.text.strip(),
                start=seg.start,
                end=seg.end,
                confidence=None,
            )
            for seg in segments_list
        ]

        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        if self._model is not None:
            return True
        return WhisperModel is not None

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
