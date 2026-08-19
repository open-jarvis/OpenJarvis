"""Tests for the local wake-word detector wrapper.

Tests inject a fake openWakeWord model directly (bypassing the lazy
`openwakeword` import) so they run without the optional `speech-wakeword`
extra installed.
"""

from __future__ import annotations

from openjarvis.speech.wakeword import WakeWordDetector


class _FakeModel:
    def __init__(self, predictions: dict) -> None:
        self._predictions = predictions
        self.reset_called = False

    def predict(self, chunk):
        return self._predictions

    def reset(self):
        self.reset_called = True


class TestWakeWordDetector:
    def test_detects_above_threshold(self):
        detector = WakeWordDetector(wake_word="hey_jarvis", threshold=0.5)
        detector._model = _FakeModel({"hey_jarvis": 0.8})
        result = detector.process_chunk([0] * 1280)
        assert result == "hey_jarvis"

    def test_no_detection_below_threshold(self):
        detector = WakeWordDetector(wake_word="hey_jarvis", threshold=0.5)
        detector._model = _FakeModel({"hey_jarvis": 0.2})
        result = detector.process_chunk([0] * 1280)
        assert result is None

    def test_detects_at_exact_threshold(self):
        detector = WakeWordDetector(wake_word="hey_jarvis", threshold=0.5)
        detector._model = _FakeModel({"hey_jarvis": 0.5})
        result = detector.process_chunk([0] * 1280)
        assert result == "hey_jarvis"

    def test_reset_delegates_to_model(self):
        detector = WakeWordDetector()
        fake = _FakeModel({})
        detector._model = fake
        detector.reset()
        assert fake.reset_called is True

    def test_reset_without_model_is_noop(self):
        detector = WakeWordDetector()
        detector.reset()  # should not raise
