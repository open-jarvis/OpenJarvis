"""Tests for the Silero VAD wrapper."""

from __future__ import annotations

from openjarvis.speech.vad import SileroVAD, build_vad, _find_model_path


class _FakeSession:
    def __init__(self, probability: float) -> None:
        self._probability = probability
        self.last_inputs = None

    def run(self, _outputs, feed):
        self.last_inputs = feed
        import numpy as np

        return (
            [[self._probability]],
            np.zeros((2, 1, 64), dtype=np.float32),
            np.zeros((2, 1, 64), dtype=np.float32),
        )


def test_find_model_path_locates_openwakeword_model() -> None:
    # The silero_vad.onnx weights ship with the openwakeword package
    # (installed in this environment).
    path = _find_model_path()
    assert path is not None
    assert path.name == "silero_vad.onnx"
    assert path.exists()


def test_build_vad_returns_detector() -> None:
    vad = build_vad()
    assert vad is not None
    # Silence scores below the speech threshold.
    assert vad.is_speech(b"\x00" * 1024) is False


def test_probability_uses_session_state() -> None:
    fake = _FakeSession(0.9)
    vad = SileroVAD(model_path="unused.onnx", session_factory=lambda p: fake)

    assert vad.probability(b"\x00" * 1024) == 0.9
    assert vad.is_speech(b"\x00" * 1024) is True
    # The ONNX feed must carry the 512-sample float window + state tensors.
    assert fake.last_inputs["input"].shape == (1, 512)
    assert fake.last_inputs["h"].shape == (2, 1, 64)


def test_reset_clears_lstm_state() -> None:
    fake = _FakeSession(0.9)
    vad = SileroVAD(model_path="unused.onnx", session_factory=lambda p: fake)
    vad.probability(b"\x00" * 1024)
    vad.reset()
    assert float(vad._h.reshape(-1)[0]) == 0.0
    assert float(vad._c.reshape(-1)[0]) == 0.0


def test_build_vad_returns_none_when_model_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.speech.vad._find_model_path",
        lambda: None,
    )
    assert build_vad() is None
