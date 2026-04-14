"""
Gemeinsame Whisper-Transkription fuer Telegram und Web.

Beide Oberflaechen verwenden dieselbe STT-Pipeline, damit die
Erkennungsqualitaet konsistent bleibt.
"""

from __future__ import annotations

import ctypes
import logging
import os

logger = logging.getLogger(__name__)

_whisper_model = None
_whisper_device = None


def _load_whisper_cpu():
    """Whisper auf CPU laden - bevorzugt medium, sonst small als Fallback."""
    from faster_whisper import WhisperModel

    try:
        model = WhisperModel("medium", device="cpu", compute_type="int8")
        logger.info("Whisper medium auf CPU geladen (int8) - schneller Modus")
        return model, "cpu"
    except Exception:
        model = WhisperModel("small", device="cpu", compute_type="int8")
        logger.info("Whisper small auf CPU geladen (Fallback)")
        return model, "cpu"


def get_whisper_model():
    """Whisper bevorzugt auf GPU, sonst auf CPU laden."""
    global _whisper_model, _whisper_device

    if _whisper_model is not None:
        return _whisper_model

    from faster_whisper import WhisperModel

    if _whisper_device != "cpu":
        try:
            if os.name == "nt":
                ctypes.WinDLL("cublas64_12.dll")
            model = WhisperModel("medium", device="cuda", compute_type="int8")
            _whisper_model = model
            _whisper_device = "cuda"
            logger.info("Whisper medium auf GPU (CUDA int8)")
            return _whisper_model
        except Exception as cuda_err:
            logger.warning(f"GPU nicht verfuegbar ({cuda_err}), nutze CPU")
            _whisper_device = "cpu"

    _whisper_model, _whisper_device = _load_whisper_cpu()
    return _whisper_model


def transcribe_audio(file_path: str, preferred_language: str | None = "de") -> dict:
    """Audio mit derselben Whisper-Konfiguration wie im Telegram-Bot transkribieren."""
    global _whisper_model, _whisper_device

    try:
        model = get_whisper_model()
        segments, info = model.transcribe(
            file_path,
            beam_size=3,
            language=preferred_language,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400),
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text for segment in segments).strip()
        detected = getattr(info, "language", preferred_language or "?")
        logger.info(f"Transkription ({detected}, {_whisper_device}): {text[:80]}")
        return {
            "text": text,
            "language": detected,
            "device": _whisper_device or "cpu",
        }

    except Exception as exc:
        err = str(exc)
        if any(token in err.lower() for token in ["cublas", "cudnn", "cuda", "dll", "cublaslt"]):
            logger.warning(f"CUDA-Fehler beim Transkribieren, wechsle zu CPU: {exc}")
            _whisper_model = None
            _whisper_device = "cpu"
            try:
                _whisper_model, _ = _load_whisper_cpu()
                segments, info = _whisper_model.transcribe(
                    file_path,
                    beam_size=5,
                    language=None,
                    vad_filter=True,
                    condition_on_previous_text=True,
                )
                text = " ".join(segment.text for segment in segments).strip()
                detected = getattr(info, "language", "?")
                logger.info(f"Transkription (cpu-retry, {detected}): {text[:80]}")
                return {
                    "text": text,
                    "language": detected,
                    "device": "cpu",
                }
            except Exception as retry_exc:
                logger.error(f"CPU-Retry fehlgeschlagen: {retry_exc}")
                return {"text": "", "language": preferred_language or "?", "device": "cpu"}

        if "ImportError" in err or "No module" in err:
            logger.warning("faster-whisper nicht installiert")
            return {"text": "", "language": preferred_language or "?", "device": "missing"}

        logger.error(f"Transkription fehlgeschlagen: {exc}")
        return {"text": "", "language": preferred_language or "?", "device": _whisper_device or "unknown"}
