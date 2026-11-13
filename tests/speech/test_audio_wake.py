"""Tests for audio-level wake word detection (openWakeWord)."""

from __future__ import annotations

from openjarvis.speech.audio_wake import (
    AudioWakeWordDetector,
    _max_score,
    build_detector,
    unavailable_reason,
    wait_for_wake_word,
)


def test_max_score_reads_prediction_dict() -> None:
    assert _max_score({"hey_jarvis_v0.1": 0.9, "alexa_v0.1": 0.1}) == 0.9
    assert _max_score({"hey_jarvis_v0.1": 0.0}) == 0.0
    assert _max_score(None) == 0.0
    assert _max_score("not-a-dict") == 0.0


def test_build_detector_never_raises_without_openwakeword() -> None:
    # openwakeword is not installed in the test environment: build_detector
    # must return None (fallback to transcript-based wake) rather than raise.
    detector = build_detector(timeout=1.0)
    if detector is None:
        assert unavailable_reason() is not None
    else:
        detector.close()


class _FakeModel:
    def __init__(self, scores: list[dict]) -> None:
        self._scores = iter(scores)
        self.resets = 0

    def predict(self, frame: bytes) -> dict:
        try:
            return next(self._scores)
        except StopIteration:
            return {"hey_jarvis_v0.1": 0.0}

    def reset(self) -> None:
        self.resets += 1


class _FakeStream:
    def __init__(self, frames: int) -> None:
        self._frames = frames

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n: int):
        if self._frames <= 0:
            raise RuntimeError("no more frames")
        self._frames -= 1
        return b"\x00" * (n * 2), True


def test_listen_detects_when_score_exceeds_threshold() -> None:
    model = _FakeModel(
        [{"hey_jarvis_v0.1": 0.3}, {"hey_jarvis_v0.1": 0.95}]
    )
    detector = AudioWakeWordDetector(
        threshold=0.5,
        timeout=2.0,
        model_factory=lambda: model,
        stream_factory=lambda: _FakeStream(frames=4),
    )
    assert detector.listen() is True
    assert model.resets == 1


def test_listen_times_out_below_threshold() -> None:
    model = _FakeModel([{"hey_jarvis_v0.1": 0.1}])
    detector = AudioWakeWordDetector(
        threshold=0.5,
        timeout=0.3,
        model_factory=lambda: model,
        stream_factory=lambda: _FakeStream(frames=20),
    )
    assert detector.listen() is False


def test_listen_returns_false_when_mic_fails() -> None:
    class _BrokenStream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n: int):
            raise OSError("mic busy")

    detector = AudioWakeWordDetector(
        threshold=0.5,
        timeout=2.0,
        model_factory=lambda: _FakeModel([]),
        stream_factory=lambda: _BrokenStream(),
    )
    assert detector.listen() is False


def test_wait_for_wake_word_returns_none_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.speech.audio_wake.build_detector", lambda **kwargs: None
    )
    assert wait_for_wake_word(timeout=0.1) is None
