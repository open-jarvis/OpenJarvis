"""Silero VAD — neural voice-activity detection for endpointing and barge-in.

Replaces plain RMS-energy heuristics with Silero's VAD (ONNX, via the
onnxruntime already pulled in by openWakeWord): a small LSTM model scores
each 32 ms frame (512 samples @ 16 kHz) as speech probability. The ONNX
weights ship with the ``openwakeword`` package (``silero_vad.onnx``); when
either onnxruntime or the model file is missing, callers fall back to the
RMS-energy heuristic unchanged.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_CHUNK_SAMPLES = 512  # 32 ms at 16 kHz — Silero's native window
_HIDDEN_SIZE = 64
_SPEECH_THRESHOLD = 0.5

# ONNX input/output names used by Silero VAD v5.
_INPUT_NAME = "input"
_SR_NAME = "sr"
_H_NAME = "h"
_C_NAME = "c"
_OUTPUT_NAME = "output"
_HN_NAME = "hn"
_CN_NAME = "cn"


def _find_model_path() -> Optional[pathlib.Path]:
    """Locate ``silero_vad.onnx`` inside the installed openwakeword package."""
    try:
        import openwakeword  # noqa: F401 — only to resolve the package dir

        import importlib.util

        spec = importlib.util.find_spec("openwakeword")
        if spec is None or spec.origin is None:
            return None
        package_dir = pathlib.Path(spec.origin).parent
        candidates = list(
            (package_dir / "resources" / "models").glob("silero_vad*.onnx")
        )
        return candidates[0] if candidates else None
    except Exception:  # noqa: BLE001 — probing is best-effort
        return None


def build_vad(
    *,
    threshold: float = _SPEECH_THRESHOLD,
    chunk_samples: int = _CHUNK_SAMPLES,
    sample_rate: int = _SAMPLE_RATE,
) -> Optional["SileroVAD"]:
    """Return a ready-to-use VAD, or ``None`` when unavailable. Never raises."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        logger.debug("Silero VAD unavailable: onnxruntime missing")
        return None
    model_path = _find_model_path()
    if model_path is None:
        logger.debug("Silero VAD unavailable: silero_vad.onnx not found")
        return None
    try:
        return SileroVAD(
            model_path=model_path,
            threshold=threshold,
            chunk_samples=chunk_samples,
            sample_rate=sample_rate,
        )
    except Exception as exc:  # noqa: BLE001 — VAD is an optional layer
        logger.debug("Silero VAD failed to build: %s", exc)
        return None


class SileroVAD:
    """Streaming Silero VAD wrapper around the raw ONNX model.

    Call :meth:`probability` with consecutive float32 frames of
    ``chunk_samples`` samples; the internal LSTM state carries context across
    frames. :meth:`reset` clears that state (e.g. between utterances).
    """

    def __init__(
        self,
        *,
        model_path: pathlib.Path | str,
        threshold: float = _SPEECH_THRESHOLD,
        chunk_samples: int = _CHUNK_SAMPLES,
        sample_rate: int = _SAMPLE_RATE,
        session_factory: Optional[Any] = None,
    ) -> None:
        import numpy as np
        import onnxruntime as ort

        self._np = np
        self._threshold = threshold
        self._chunk_samples = chunk_samples
        self._sample_rate = sample_rate
        self._session = (
            session_factory(model_path)
            if session_factory is not None
            else ort.InferenceSession(str(model_path))
        )
        self.reset()

    def reset(self) -> None:
        """Clear the LSTM state (between utterances)."""
        np = self._np
        self._h = np.zeros((2, 1, _HIDDEN_SIZE), dtype=np.float32)
        self._c = np.zeros((2, 1, _HIDDEN_SIZE), dtype=np.float32)

    def probability(self, samples: Any) -> float:
        """Score a frame of int16 PCM bytes or a float32 array.

        Returns the speech probability in [0, 1]. Frames shorter than the
        model window are zero-padded; longer frames are truncated.
        """
        np = self._np
        if isinstance(samples, (bytes, bytearray)):
            frame = (
                np.frombuffer(bytes(samples), dtype=np.int16)
                .astype(np.float32)
                / 32768.0
            )
        else:
            frame = np.asarray(samples, dtype=np.float32)
        window = self._chunk_samples
        if frame.shape[0] < window:
            frame = np.concatenate([frame, np.zeros(window - frame.shape[0])])
        else:
            frame = frame[:window]
        x = frame.reshape(1, -1)
        output, hn, cn = self._session.run(
            None,
            {
                _INPUT_NAME: x,
                _SR_NAME: np.array(self._sample_rate, dtype=np.int64),
                _H_NAME: self._h,
                _C_NAME: self._c,
            },
        )
        self._h, self._c = hn, cn
        return float(np.asarray(output).reshape(-1)[0])

    def is_speech(self, samples: Any) -> bool:
        """True when the frame's speech probability crosses the threshold."""
        return self.probability(samples) >= self._threshold


__all__ = ["SileroVAD", "build_vad"]
