"""Faster-Whisper speech-to-text backend (local, CTranslate2-based)."""

from __future__ import annotations

import ctypes
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

# CTranslate2 links these lazily: a GPU without them loads the model fine and
# then fails (or stalls) on the first transcription.
_CUBLAS_LIBRARY = "cublas64_12.dll" if sys.platform == "win32" else "libcublas.so.12"
_CUDA_ERROR_MARKERS = ("cublas", "cudnn", "cuda")


def _nvidia_package_roots() -> List[str]:
    """Folders of the ``nvidia`` pip namespace package (nvidia-cublas-cu12 etc.)."""
    import importlib.util

    try:
        spec = importlib.util.find_spec("nvidia")
    except (ImportError, ValueError):
        return []
    return list(spec.submodule_search_locations or []) if spec else []


def _add_nvidia_dll_dirs() -> List[str]:
    """Make DLLs from NVIDIA's pip wheels loadable (Windows).

    ``pip install nvidia-cublas-cu12`` puts cuBLAS in
    ``site-packages/nvidia/cublas/bin``, which is not on the DLL search path,
    so CTranslate2 cannot find it. Prepend each such ``bin`` folder to PATH
    (what CTranslate2's loader searches) and register it as a DLL directory.
    """
    found: List[str] = []
    for root in _nvidia_package_roots():
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            bin_dir = os.path.join(root, name, "bin")
            if os.path.isdir(bin_dir):
                found.append(bin_dir)
    current = os.environ.get("PATH", "").split(os.pathsep)
    for bin_dir in found:
        if bin_dir in current:
            continue
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        current.insert(0, bin_dir)
        add_dll_directory = getattr(os, "add_dll_directory", None)
        if add_dll_directory is not None:
            try:
                add_dll_directory(bin_dir)
            except OSError:
                pass
    return found


def _cuda_runtime_usable() -> bool:
    """True when a CUDA device exists and the cuBLAS runtime can be loaded."""
    if ctranslate2 is None:
        return False
    if sys.platform == "win32":
        _add_nvidia_dll_dirs()
    try:
        if ctranslate2.get_cuda_device_count() < 1:
            return False
    except Exception:
        return False
    try:
        ctypes.CDLL(_CUBLAS_LIBRARY)
    except OSError:
        logger.info(
            "CUDA device found but %s is not loadable; Whisper will use the CPU",
            _CUBLAS_LIBRARY,
        )
        return False
    return True


def _is_cuda_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _CUDA_ERROR_MARKERS)


@SpeechRegistry.register("faster-whisper")
class FasterWhisperBackend(SpeechBackend):
    """Local speech-to-text using Faster-Whisper (CTranslate2)."""

    backend_id = "faster-whisper"

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "float16",
        language: str = "",
    ) -> None:
        self._model_size = model_size
        # Default spoken language; empty means detect it per request (slower).
        self._language = language
        self._device = device
        self._compute_type = compute_type
        self._model: Optional[WhisperModel] = None
        self._model_device: Optional[str] = None
        self._last_error: Optional[str] = None

    def _resolve_device(self) -> str:
        """Turn ``auto`` into a device that can actually run the model."""
        if self._device != "auto":
            return self._device
        return "cuda" if _cuda_runtime_usable() else "cpu"

    def _resolve_compute_type(self, device: str) -> str:
        """Pick a CTranslate2 compute type supported by *device*."""
        if ctranslate2 is None:
            return self._compute_type

        try:
            supported = set(ctranslate2.get_supported_compute_types(device))
        except Exception as exc:
            logger.debug(
                "Could not inspect CTranslate2 compute types for %s: %s",
                device,
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
            device,
            fallback,
        )
        return fallback

    def _ensure_model(self, device: Optional[str] = None) -> WhisperModel:
        """Lazy-load the Whisper model on first use (or on *device*)."""
        if self._model is None or (device and device != self._model_device):
            if WhisperModel is None:
                self._last_error = (
                    "faster-whisper is not installed. "
                    "Install with: uv sync --extra desktop"
                )
                raise ImportError(self._last_error)
            target = device or self._resolve_device()
            self._model = WhisperModel(
                self._model_size,
                device=target,
                compute_type=self._resolve_compute_type(target),
            )
            self._model_device = target
        self._last_error = None
        return self._model

    def _run(self, model: WhisperModel, path: str, kwargs: dict):
        segments_iter, info = model.transcribe(path, **kwargs)
        return list(segments_iter), info

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
                if language or self._language:
                    kwargs["language"] = language or self._language

                try:
                    segments_list, info = self._run(model, tmp.name, kwargs)
                except RuntimeError as exc:
                    if self._model_device != "cuda" or not _is_cuda_error(exc):
                        raise
                    logger.warning(
                        "Whisper failed on the GPU (%s); switching to the CPU", exc
                    )
                    cpu_model = self._ensure_model(device="cpu")
                    segments_list, info = self._run(cpu_model, tmp.name, kwargs)
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
