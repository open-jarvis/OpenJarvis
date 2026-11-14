"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import gc
import logging
import os
import sys
import tempfile
from typing import List, Optional

from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import Segment, SpeechBackend, TranscriptionResult

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # type: ignore[assignment, misc]

try:
    import ctranslate2
except ImportError:
    ctranslate2 = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _describe(exc: BaseException) -> str:
    # Text only: the exception's traceback would keep the GPU model alive.
    return f"{type(exc).__name__}: {exc}"


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._last_error: Optional[str] = None
        self._effective_device: Optional[str] = None
        self._fallback_reason: Optional[str] = None

    def _resolve_compute_type(self) -> str:
        """Pick a CTranslate2 compute type supported by the configured device."""
        if ctranslate2 is None:
            return self._compute_type

        try:
            supported = set(ctranslate2.get_supported_compute_types(self._device))
        except Exception as exc:
            logger.debug(
                "Could not inspect CTranslate2 compute types for %s: %s",
                self._device,
                exc,
            )
            return self._compute_type

        if self._compute_type in supported:
            return self._compute_type

        preferences = (
            ("int8", "float32", "int8_float32", "int16")
            if self._compute_type == "float16"
            else ("float32", "int8", "int8_float32", "int16")
        )
        fallback = next((value for value in preferences if value in supported), None)
        if fallback is None:
            return self._compute_type

        logger.warning(
            "CTranslate2 compute_type=%r is not supported on device=%r; "
            "using %r instead",
            self._compute_type,
            self._device,
            fallback,
        )
        return fallback

    @property
    def effective_device(self) -> Optional[str]:
        """Device the loaded model runs on, or None before a successful load."""
        return self._effective_device

    @property
    def fallback_reason(self) -> Optional[str]:
        """Why the configured device was abandoned for CPU, or None."""
        return self._fallback_reason

    def _ensure_model(self) -> WhisperModel:
        """Lazy-load the Whisper model on first use.

        On a non-CPU device, a failed load or warm-up transcription makes
        the model reload on CPU (int8).
        """
        if self._model is None:
            if WhisperModel is None:
                self._last_error = (
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra desktop"
                )
                raise ImportError(self._last_error)
            self._fallback_reason = None
            compute_type = self._resolve_compute_type()
            if self._device == "cpu":
                model = WhisperModel(
                    self._model_size,
                    device="cpu",
                    compute_type=compute_type,
                )
                self._effective_device = "cpu"
            else:
                model = self._load_on_accelerator(compute_type)
            self._model = model
        self._last_error = None
        return self._model

    def _load_on_accelerator(self, compute_type: str) -> WhisperModel:
        """Load on the configured non-CPU device, or fall back to CPU.

        Loading can succeed while inference fails (e.g. cuBLAS missing), so
        a warm-up runs the full decode, segment generator included. It is
        retried once, since a CUDA out-of-memory error can be transient.
        """
        if sys.platform == "win32":
            # CTranslate2 loads cublas64_12.dll lazily by bare name (PATH
            # search, os.add_dll_directory is ignored); importing torch
            # preloads it from torch/lib.
            try:
                import torch  # noqa: F401
            except (ImportError, OSError):
                pass
        try:
            model = WhisperModel(
                self._model_size,
                device=self._device,
                compute_type=compute_type,
            )
        except Exception as exc:
            return self._load_cpu_fallback("model load", _describe(exc))

        device = getattr(getattr(model, "model", None), "device", None)
        if not isinstance(device, str):
            device = self._device
        if device == "cpu":
            self._effective_device = "cpu"
            return model

        error = self._warm_up(model)
        if error is not None:
            logger.debug(
                "Faster-Whisper warm-up failed on device=%r (%s); retrying once",
                device,
                error,
            )
            gc.collect()
            error = self._warm_up(model)
        if error is not None:
            return self._load_cpu_fallback("warm-up inference", error)
        self._effective_device = device
        return model

    def _warm_up(self, model: WhisperModel) -> Optional[str]:
        """Transcribe one second of silence; return the error text, if any."""
        import numpy as np

        try:
            segments, _info = model.transcribe(
                np.zeros(16000, dtype=np.float32),
                language="en",
                beam_size=1,
            )
            list(segments)
        except Exception as exc:
            return _describe(exc)
        return None

    def _load_cpu_fallback(self, stage: str, error: str) -> WhisperModel:
        """Load the model on CPU (int8) after ``stage`` failed on the device."""
        self._fallback_reason = f"{stage} on device={self._device!r} failed: {error}"
        logger.warning(
            "Faster-Whisper %s; falling back to device='cpu', compute_type='int8'",
            self._fallback_reason,
        )
        model = WhisperModel(
            self._model_size,
            device="cpu",
            compute_type="int8",
        )
        self._effective_device = "cpu"
        return model

    def transcribe(
        self,
        audio: bytes,
        *,
        format: str = "wav",
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio bytes using Faster-Whisper."""
        try:
            model = self._ensure_model()

            # Write audio to a temp file (faster-whisper needs a file path).
            # delete=False + manual unlink: on Windows an open
            # NamedTemporaryFile holds an exclusive handle, so PyAV's reopen
            # of tmp.name inside model.transcribe() fails with EACCES.
            suffix = f".{format}" if not format.startswith(".") else format
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            try:
                with tmp:
                    tmp.write(audio)

                kwargs = {}
                if language:
                    kwargs["language"] = language

                segments_iter, info = model.transcribe(tmp.name, **kwargs)
                segments_list = list(segments_iter)
            finally:
                try:
                    os.unlink(tmp.name)
                except OSError as unlink_exc:
                    logger.debug(
                        "Could not remove temp audio file %s: %s",
                        tmp.name,
                        unlink_exc,
                    )
        except Exception as exc:
            self._last_error = str(exc)
            raise

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

        self._last_error = None
        return TranscriptionResult(
            text=text,
            language=getattr(info, "language", None),
            confidence=getattr(info, "language_probability", None),
            duration_seconds=getattr(info, "duration", 0.0),
            segments=segments,
        )

    def health(self) -> bool:
        """Check if model is loaded or loadable."""
        try:
            self._ensure_model()
            return True
        except Exception as exc:
            self._last_error = str(exc)
            logger.debug("Faster-Whisper health check failed: %s", exc)
            return False

    def last_error(self) -> Optional[str]:
        """Return the last model load or transcription error, if any."""
        return self._last_error

    def supported_formats(self) -> List[str]:
        """Supported audio formats (same as ffmpeg/Whisper)."""
        return ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
