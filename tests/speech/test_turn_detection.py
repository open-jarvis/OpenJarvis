"""End-of-turn detection: state machine, Smart Turn features, models, mic loop.

Everything runs without a microphone or network: the VAD and Smart Turn are
scripted fakes, and sounddevice is replaced by a stream that feeds int16
blocks from a thread. The tests that use the real Silero asset or the real
Smart Turn model skip when they are not installed or cached.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import logging
import socket
import subprocess
import sys
import threading
import time
import types
import wave
from typing import Callable

import numpy as np
import pytest

from openjarvis.speech import turn_detection as td
from openjarvis.speech.turn_detection import (
    FRAME,
    SAMPLE_RATE,
    TYPED,
    TurnDetector,
    TurnParams,
    listen_for_turn,
    load_turn_models,
    smart_turn_features,
)

# Frame counts for the default TurnParams (one frame = 32 ms).
START = 7  # start_secs 0.2
VAD_STOP = 7  # vad_stop_secs 0.2
TURN_STOP = 94  # turn_stop_secs 3.0
FALLBACK = 32  # fallback_silence_secs 1.0
TRAILING = 10  # keep_trailing_secs 0.3
RING = 22  # pre_roll_secs 0.5 + start_secs 0.2


class _ScriptedVad:
    """Returns the scripted speech probabilities in order, then 0.0."""

    def __init__(self, probs) -> None:
        self.probs = list(probs)
        self.calls = 0
        self.resets = 0

    def reset(self) -> None:
        self.resets += 1

    def __call__(self, frame) -> float:
        prob = self.probs[self.calls] if self.calls < len(self.probs) else 0.0
        self.calls += 1
        return prob


class _FakeSmartTurn:
    """Returns the scripted answers in order (the last one repeats)."""

    def __init__(self, *answers: float) -> None:
        self.answers = answers
        self.calls: list[np.ndarray] = []

    def __call__(self, audio: np.ndarray) -> float:
        self.calls.append(audio)
        return self.answers[min(len(self.calls), len(self.answers)) - 1]


def _run(detector: TurnDetector, n_frames: int) -> dict[int, str]:
    """Feed frames whose samples all equal the frame index; map index -> verdict."""
    verdicts = {}
    for i in range(n_frames):
        verdict = detector.feed(np.full(FRAME, i, np.float32))
        if verdict is not None:
            verdicts[i] = verdict
            if verdict in ("end", "timeout"):
                break
    return verdicts


def _frame_ids(audio: np.ndarray) -> list[int]:
    return [int(v) for v in audio.reshape(-1, FRAME)[:, 0]]


def _warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


@pytest.fixture
def fresh_warnings(monkeypatch, caplog):
    """Forget the warnings already given once, and capture new ones."""
    monkeypatch.setattr(td, "_warned", set(), raising=False)
    with caplog.at_level(logging.WARNING, logger=td.__name__):
        yield caplog


# --------------------------------------------------------------- TurnDetector


def test_speech_start_keeps_pre_roll_and_reports_started_once() -> None:
    # A 3-frame blip is too short to start a turn.
    vad = _ScriptedVad([0.0] * 10 + [0.9] * 3 + [0.0] * 17 + [0.9] * 20)
    detector = TurnDetector(vad)

    verdicts = _run(detector, 50)

    assert verdicts == {30 + START - 1: "started"}
    ids = _frame_ids(detector.audio())
    assert ids == list(range(30 + START - RING, 50))


def test_smart_turn_ends_turn_after_vad_stop() -> None:
    vad = _ScriptedVad([0.9] * 20 + [0.0] * 50)
    smart_turn = _FakeSmartTurn(0.9)
    detector = TurnDetector(vad, smart_turn)

    verdicts = _run(detector, 70)

    end = 20 + VAD_STOP - 1
    assert verdicts == {START - 1: "started", end: "end"}
    assert len(smart_turn.calls) == 1
    assert _frame_ids(smart_turn.calls[0]) == list(range(end + 1))


def test_first_pause_after_the_shortest_start_counts_only_silence() -> None:
    # Exactly START speech frames: the start run is not silence.
    vad = _ScriptedVad([0.9] * START + [0.0] * 50)
    smart_turn = _FakeSmartTurn(0.9)
    detector = TurnDetector(vad, smart_turn)

    verdicts = _run(detector, 57)

    assert verdicts == {START - 1: "started", START + VAD_STOP - 1: "end"}
    assert len(smart_turn.calls) == 1
    fallback = TurnDetector(_ScriptedVad([0.9] * START + [0.0] * 50))
    assert _run(fallback, 57) == {START - 1: "started", START + FALLBACK - 1: "end"}


def test_incomplete_turn_waits_for_silence_cap_without_asking_again() -> None:
    vad = _ScriptedVad([0.9] * 20 + [0.0] * 200)
    smart_turn = _FakeSmartTurn(0.1)
    detector = TurnDetector(vad, smart_turn)

    verdicts = _run(detector, 220)

    assert verdicts == {START - 1: "started", 20 + TURN_STOP - 1: "end"}
    assert len(smart_turn.calls) == 1
    assert _frame_ids(detector.audio()) == list(range(20 + TRAILING))


def test_speech_resuming_after_a_pause_queries_smart_turn_again() -> None:
    vad = _ScriptedVad([0.9] * 20 + [0.0] * 10 + [0.9] * 5 + [0.0] * 20)
    smart_turn = _FakeSmartTurn(0.1, 0.9)
    detector = TurnDetector(vad, smart_turn)

    verdicts = _run(detector, 55)

    second_query = 35 + VAD_STOP - 1
    assert verdicts == {START - 1: "started", second_query: "end"}
    assert [len(a) // FRAME for a in smart_turn.calls] == [
        20 + VAD_STOP,
        second_query + 1,
    ]


def test_vad_hysteresis_while_speaking_and_paused() -> None:
    # 0.4 keeps a speaker talking (>= 0.35) but does not resume a pause (< 0.5).
    vad = _ScriptedVad([0.9] * 10 + [0.4] * 50 + [0.0] * 5 + [0.4] * 40)
    detector = TurnDetector(vad)

    verdicts = _run(detector, 105)

    assert verdicts == {START - 1: "started", 60 + FALLBACK - 1: "end"}
    assert _frame_ids(detector.audio())[-TRAILING - 1] == 59


def test_fixed_silence_fallback_without_smart_turn() -> None:
    vad = _ScriptedVad([0.9] * 20 + [0.0] * 20 + [0.9] * 10 + [0.0] * 50)
    detector = TurnDetector(vad)

    verdicts = _run(detector, 100)

    assert verdicts == {START - 1: "started", 50 + FALLBACK - 1: "end"}
    assert _frame_ids(detector.audio()) == list(range(50 + TRAILING))


def test_smart_turn_failure_falls_back_to_fixed_silence(fresh_warnings) -> None:
    calls = []

    def broken(audio: np.ndarray) -> float:
        calls.append(audio)
        raise RuntimeError("onnxruntime: bad allocation")

    script = [0.9] * 20 + [0.0] * 10 + [0.9] * 5 + [0.0] * 50
    detector = TurnDetector(_ScriptedVad(script), broken)

    verdicts = _run(detector, 85)

    assert verdicts == {START - 1: "started", 35 + FALLBACK - 1: "end"}
    assert len(calls) == 1  # not asked again at the second pause
    next_turn = TurnDetector(_ScriptedVad(script), broken)
    assert _run(next_turn, 85) == verdicts
    (message,) = _warnings(fresh_warnings)
    assert "bad allocation" in message


def test_start_timeout_only_while_waiting_for_speech() -> None:
    params = TurnParams(start_timeout_secs=1.0)  # 32 frames

    assert _run(TurnDetector(_ScriptedVad([]), params=params), 100) == {31: "timeout"}
    speaking = TurnDetector(_ScriptedVad([0.0] * 20 + [0.9] * 80), params=params)
    assert _run(speaking, 100) == {20 + START - 1: "started"}


def test_start_timeout_waits_for_speech_that_is_starting() -> None:
    params = TurnParams(start_timeout_secs=1.0)  # 32 frames
    late = TurnDetector(_ScriptedVad([0.0] * 28 + [0.9] * 40), params=params)
    blip = TurnDetector(_ScriptedVad([0.0] * 30 + [0.9] * 3), params=params)

    assert _run(late, 68) == {28 + START - 1: "started"}
    assert _run(blip, 100) == {33: "timeout"}  # once the blip is over


def test_max_turn_length_ends_a_turn_that_never_pauses() -> None:
    params = TurnParams(max_turn_secs=2.0)  # 63 frames
    detector = TurnDetector(_ScriptedVad([0.9] * 200), _FakeSmartTurn(0.9), params)

    verdicts = _run(detector, 200)

    assert verdicts == {START - 1: "started", 62: "end"}
    assert len(detector.audio()) == 63 * FRAME


def test_audio_is_empty_before_speech() -> None:
    detector = TurnDetector(_ScriptedVad([]))
    _run(detector, 5)

    audio = detector.audio()

    assert audio.dtype == np.float32
    assert audio.size == 0


def test_vad_state_is_reset_after_a_long_quiet_wait() -> None:
    params = TurnParams(quiet_reset_secs=1.0)  # 32 frames
    quiet = _ScriptedVad([0.0] * 100)
    _run(TurnDetector(quiet, params=params), 100)
    murmur = _ScriptedVad([0.2] * 100)  # not quiet enough (< 0.1) to reset
    _run(TurnDetector(murmur, params=params), 100)

    assert quiet.resets == 1 + 3  # on construction, then every 32 quiet frames
    assert murmur.resets == 1


def test_turn_params_are_frozen() -> None:
    params = TurnParams()

    with pytest.raises(dataclasses.FrozenInstanceError):
        params.vad_threshold = 0.9  # type: ignore[misc]
    assert params.start_timeout_secs is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.0, -1.0])
def test_invalid_vad_stop_falls_back_to_the_default(value, fresh_warnings) -> None:
    params = TurnParams(vad_stop_secs=value)
    TurnParams(vad_stop_secs=value)  # a new TurnParams every turn: warned once
    detector = TurnDetector(
        _ScriptedVad([0.9] * 20 + [0.0] * 50), _FakeSmartTurn(0.9), params
    )

    verdicts = _run(detector, 70)

    assert params.vad_stop_secs == 0.2
    assert verdicts == {START - 1: "started", 20 + VAD_STOP - 1: "end"}
    assert len(_warnings(fresh_warnings)) == 1


@pytest.mark.parametrize("value", [3.0, 3.5])
def test_vad_stop_at_the_silence_cap_still_asks_smart_turn(
    value, fresh_warnings
) -> None:
    params = TurnParams(vad_stop_secs=value)
    TurnParams(vad_stop_secs=value)
    smart_turn = _FakeSmartTurn(0.9)
    detector = TurnDetector(_ScriptedVad([0.9] * 20 + [0.0] * 200), smart_turn, params)

    verdicts = _run(detector, 220)

    assert params.vad_stop_secs == pytest.approx(3.0 - FRAME / SAMPLE_RATE)
    assert verdicts == {START - 1: "started", 20 + TURN_STOP - 2: "end"}
    assert len(smart_turn.calls) == 1
    assert TurnParams(vad_stop_secs=2.9).vad_stop_secs == 2.9
    assert len(_warnings(fresh_warnings)) == 1


# --------------------------------------------------------- smart_turn_features

_WINDOW = 8 * SAMPLE_RATE


def _noise(secs: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(secs * SAMPLE_RATE)) * 0.1).astype(np.float32)


def test_features_shape_and_dtype() -> None:
    features = smart_turn_features(_noise(2.0))

    assert features.shape == (1, 80, 800)
    assert features.dtype == np.float32
    assert np.isfinite(features).all()


def test_short_audio_is_zero_padded_at_the_start() -> None:
    audio = _noise(1.0)
    left = np.concatenate([np.zeros(_WINDOW - len(audio), np.float32), audio])
    right = np.concatenate([audio, np.zeros(_WINDOW - len(audio), np.float32)])

    features = smart_turn_features(audio)

    np.testing.assert_array_equal(features, smart_turn_features(left))
    assert not np.allclose(features, smart_turn_features(right))
    # The padded 7 s give constant columns; the audio is in the last 100.
    assert np.ptp(features[0, :, :690], axis=1).max() < 1e-6
    assert np.ptp(features[0, :, 700:], axis=1).max() > 0.1


def test_long_audio_keeps_the_last_eight_seconds() -> None:
    audio = _noise(10.0)

    np.testing.assert_array_equal(
        smart_turn_features(audio), smart_turn_features(audio[-_WINDOW:])
    )


def test_features_match_transformers_whisper_extractor() -> None:
    transformers = pytest.importorskip("transformers")
    extractor = transformers.WhisperFeatureExtractor(chunk_length=8)
    t = np.arange(10 * SAMPLE_RATE) / SAMPLE_RATE
    tones = 0.2 * np.sin(2 * np.pi * 220 * t) * np.sin(2 * np.pi * 3 * t)
    signal = (tones + _noise(10.0, seed=1)).astype(np.float32)

    for audio in (signal[: 3 * SAMPLE_RATE], signal):
        padded = audio[-_WINDOW:]
        padded = np.pad(padded, (_WINDOW - len(padded), 0))
        expected = extractor(
            padded,
            sampling_rate=SAMPLE_RATE,
            return_tensors="np",
            padding="max_length",
            max_length=_WINDOW,
            truncation=True,
            do_normalize=True,
        ).input_features

        np.testing.assert_allclose(smart_turn_features(audio), expected, atol=1e-4)


# ---------------------------------------------------------------- real models


def _silero_asset() -> str:
    pytest.importorskip("onnxruntime")
    try:
        return td._silero_path()
    except FileNotFoundError:
        pytest.skip("faster-whisper's silero_vad_v6.onnx is not installed")


# (centre Hz, bandwidth Hz) of the first three formants of /a i e o u/.
_VOWELS = (
    ((700, 80), (1220, 90), (2600, 120)),
    ((280, 60), (2250, 100), (2900, 120)),
    ((400, 70), (1900, 100), (2550, 120)),
    ((450, 70), (800, 80), (2830, 120)),
    ((310, 60), (870, 80), (2250, 120)),
)


def _voiced(secs: float) -> np.ndarray:
    """Speech-like signal: 0.2 s syllables cycling through five vowels.

    A single steady vowel is not enough: Silero stops calling it speech
    after about a second.
    """
    n = int(secs * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    pitch = 120.0 * (1 + 0.08 * np.sin(2 * np.pi * 1.3 * t))
    phase = 2 * np.pi * np.cumsum(pitch) / SAMPLE_RATE
    syllable, gap = int(0.2 * SAMPLE_RATE), int(0.03 * SAMPLE_RATE)
    signal = np.zeros(n)
    for i, start in enumerate(range(0, n, syllable)):
        part = slice(start, min(n, start + syllable))
        for k in range(1, 60):
            gain = sum(
                1.0 / (1.0 + ((k * 120.0 - centre) / width) ** 2)
                for centre, width in _VOWELS[i % len(_VOWELS)]
            )
            signal[part] += gain * np.sin(k * phase[part])
        size = part.stop - part.start
        envelope = np.sin(np.pi * np.arange(size) / size) ** 0.5
        envelope[-gap:] = 0.0
        signal[part] *= envelope
    return (0.3 * signal / np.abs(signal).max()).astype(np.float32)


def test_silero_stream_matches_faster_whisper_batched_vad() -> None:
    path = _silero_asset()
    vad_module = pytest.importorskip("faster_whisper.vad")
    quiet = _noise(1.0, seed=2) * 0.03
    signal = np.concatenate([quiet, _voiced(2.0) + _noise(2.0, seed=3) * 0.03, quiet])
    signal = signal[: len(signal) // FRAME * FRAME]
    vad = td.SileroStream(path)

    streamed = np.array([vad(f) for f in signal.reshape(-1, FRAME)])
    batched = np.asarray(vad_module.SileroVADModel(path)(signal.copy())).reshape(-1)
    vad.reset()
    replayed = np.array([vad(f) for f in signal.reshape(-1, FRAME)])

    # faster-whisper zeroes the end of the last frame in place; skip that one.
    np.testing.assert_allclose(streamed[:-1], batched[:-1], atol=1e-5)
    np.testing.assert_array_equal(streamed, replayed)
    assert ((streamed >= 0) & (streamed <= 1)).all()
    second = SAMPLE_RATE // FRAME
    assert streamed[:second].max() < 0.1
    assert (streamed[second + 5 : 3 * second] >= 0.5).mean() > 0.9


def test_silero_stream_rejects_unexpected_inputs(monkeypatch) -> None:
    class _Input:
        def __init__(self, name, shape) -> None:
            self.name, self.shape = name, shape

    class _Session:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_inputs(self):
            return [_Input("input", [None, 512]), _Input("state", [2, 1, 128])]

    fake_ort = types.SimpleNamespace(
        SessionOptions=types.SimpleNamespace, InferenceSession=_Session
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)

    with pytest.raises(ValueError, match="unexpected Silero VAD inputs"):
        td.SileroStream("silero_vad.onnx")


def test_real_smart_turn_model_if_cached(monkeypatch) -> None:
    pytest.importorskip("onnxruntime")
    pytest.importorskip("huggingface_hub")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    try:
        path = td._smart_turn_path()  # the pinned revision, checksum-verified
    except OSError:
        pytest.skip("smart-turn-v3.2-cpu.onnx is not in the Hugging Face cache")
    smart_turn = td.SmartTurn(path)

    for audio in (np.zeros(SAMPLE_RATE, np.float32), _voiced(3.0)):
        prob = smart_turn(audio)
        assert isinstance(prob, float)
        assert 0.0 <= prob <= 1.0


# ------------------------------------------------------------ load_turn_models


class _FakeModel:
    instances: list[_FakeModel] = []

    def __init__(self, path: str) -> None:
        self.path = path
        type(self).instances.append(self)

    def reset(self) -> None:
        pass


_REVISION = "f766f81d3cfdf7737ac64aad813d91bbfd56bf93"


class _FakeSocket:
    def close(self) -> None:
        pass


@pytest.fixture
def fake_backends(monkeypatch, tmp_path):
    """Fresh cache, importable onnxruntime, fake models, Hub and network.

    The network is down unless a test sets ``net.up``; nothing real is
    ever contacted.
    """

    class FakeVad(_FakeModel):
        instances = []

    class FakeSmartTurn(_FakeModel):
        instances = []

    model = tmp_path / "smart-turn.onnx"
    model.write_bytes(b"not really a model")
    hub = types.ModuleType("huggingface_hub")
    hub.calls = []
    hub.constants = types.SimpleNamespace(
        HF_HUB_OFFLINE=False, ENDPOINT="https://huggingface.co"
    )

    def hf_hub_download(repo_id, filename, **kwargs):
        hub.calls.append((repo_id, filename, kwargs))
        return str(model)

    net = types.SimpleNamespace(up=False, probes=[])

    def create_connection(address, timeout=None, *args, **kwargs):
        net.probes.append((address, timeout))
        if not net.up:
            raise TimeoutError("timed out")
        return _FakeSocket()

    hub.hf_hub_download = hf_hub_download
    monkeypatch.setattr(td, "_models", {})
    monkeypatch.setitem(sys.modules, "onnxruntime", types.ModuleType("onnxruntime"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setattr(td, "SileroStream", FakeVad)
    monkeypatch.setattr(td, "SmartTurn", FakeSmartTurn)
    monkeypatch.setattr(td, "_silero_path", lambda: "silero_vad_v6.onnx")
    return types.SimpleNamespace(
        vad=FakeVad, smart_turn=FakeSmartTurn, hub=hub, model=model, net=net
    )


def _not_cached(fake_backends) -> None:
    """Make the fake Hub miss its cache and serve downloads from the network."""

    def hf_hub_download(repo_id, filename, **kwargs):
        fake_backends.hub.calls.append((repo_id, filename, kwargs))
        if kwargs.get("local_files_only"):
            raise FileNotFoundError("not in the cache")
        return str(fake_backends.model)

    fake_backends.hub.hf_hub_download = hf_hub_download


def _downloads(fake_backends) -> list[dict]:
    """The kwargs of the Hub calls that were allowed to use the network."""
    calls = fake_backends.hub.calls
    return [kw for _, _, kw in calls if not kw.get("local_files_only")]


def test_no_models_without_onnxruntime(monkeypatch, caplog) -> None:
    monkeypatch.setattr(td, "_models", {})
    monkeypatch.setitem(sys.modules, "onnxruntime", None)

    with caplog.at_level(logging.WARNING, logger=td.__name__):
        assert load_turn_models() == (None, None)
    assert len(_warnings(caplog)) == 1


def test_no_models_without_silero_asset(fake_backends, monkeypatch) -> None:
    def missing():
        raise FileNotFoundError("silero_vad_v6.onnx")

    monkeypatch.setattr(td, "_silero_path", missing)

    assert load_turn_models() == (None, None)
    assert fake_backends.smart_turn.instances == []


def test_downloaded_smart_turn_is_checksum_verified(fake_backends, monkeypatch):
    digest = hashlib.sha256(fake_backends.model.read_bytes()).hexdigest()
    monkeypatch.setattr(td, "_SMART_TURN_SHA256", digest)

    vad, smart_turn = load_turn_models()

    assert vad.path == "silero_vad_v6.onnx"
    assert smart_turn.path == str(fake_backends.model)
    ((repo, filename, kwargs),) = fake_backends.hub.calls
    assert (repo, filename) == ("pipecat-ai/smart-turn-v3", "smart-turn-v3.2-cpu.onnx")
    assert kwargs == {"revision": _REVISION, "local_files_only": True}
    assert fake_backends.net.probes == []


def test_missing_model_is_downloaded_at_the_pinned_revision(
    fake_backends, monkeypatch
) -> None:
    digest = hashlib.sha256(fake_backends.model.read_bytes()).hexdigest()
    monkeypatch.setattr(td, "_SMART_TURN_SHA256", digest)
    _not_cached(fake_backends)
    fake_backends.net.up = True

    vad, smart_turn = load_turn_models()

    assert smart_turn.path == str(fake_backends.model)
    assert fake_backends.net.probes == [(("huggingface.co", 443), 2)]
    assert [kw["revision"] for _, _, kw in fake_backends.hub.calls] == [_REVISION] * 2
    assert len(_downloads(fake_backends)) == 1


def test_unreachable_hub_fails_fast_without_downloading(fake_backends, caplog):
    _not_cached(fake_backends)

    t0 = time.monotonic()
    with caplog.at_level(logging.WARNING, logger=td.__name__):
        vad, smart_turn = load_turn_models()

    assert time.monotonic() - t0 < 3
    assert isinstance(vad, fake_backends.vad)
    assert smart_turn is None
    ((address, timeout),) = fake_backends.net.probes
    assert address == ("huggingface.co", 443)
    assert timeout <= 2
    assert _downloads(fake_backends) == []
    (message,) = _warnings(caplog)
    assert "huggingface.co" in message


@pytest.mark.parametrize("switch", ["environment", "constant"])
def test_hub_offline_mode_never_touches_the_network(
    fake_backends, monkeypatch, caplog, switch
) -> None:
    if switch == "environment":
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    else:
        fake_backends.hub.constants.HF_HUB_OFFLINE = True
    _not_cached(fake_backends)
    fake_backends.net.up = True

    with caplog.at_level(logging.WARNING, logger=td.__name__):
        vad, smart_turn = load_turn_models()

    assert isinstance(vad, fake_backends.vad)
    assert smart_turn is None
    assert fake_backends.net.probes == []
    assert _downloads(fake_backends) == []
    (message,) = _warnings(caplog)
    assert "HF_HUB_OFFLINE" in message


def test_smart_turn_with_wrong_checksum_is_refused(fake_backends, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=td.__name__):
        vad, smart_turn = load_turn_models()

    assert isinstance(vad, fake_backends.vad)
    assert smart_turn is None
    assert fake_backends.smart_turn.instances == []
    (message,) = _warnings(caplog)
    assert "sha256" in message


def test_failed_download_warns_once_and_keeps_the_vad(fake_backends, caplog):
    def offline(repo_id, filename, **kwargs):
        fake_backends.hub.calls.append(kwargs)
        raise OSError("no network")

    fake_backends.hub.hf_hub_download = offline
    fake_backends.net.up = True

    with caplog.at_level(logging.WARNING, logger=td.__name__):
        first = load_turn_models()
        second = load_turn_models()

    assert first is second
    assert isinstance(first[0], fake_backends.vad)
    assert first[1] is None
    assert len(_warnings(caplog)) == 1
    calls = len(fake_backends.hub.calls)
    load_turn_models()
    assert len(fake_backends.hub.calls) == calls


def test_user_model_path_skips_download_and_checksum(fake_backends) -> None:
    path = str(fake_backends.model)

    vad, smart_turn = load_turn_models(path)

    assert smart_turn.path == path
    assert fake_backends.hub.calls == []


def test_concurrent_loads_build_the_models_once(fake_backends, monkeypatch):
    built = []

    class SlowVad(_FakeModel):
        def __init__(self, path: str) -> None:
            time.sleep(0.05)
            built.append(path)
            self.path = path

    monkeypatch.setattr(td, "SileroStream", SlowVad)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(load_turn_models("m.onnx")))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(built) == 1
    assert len(results) == 8
    assert all(r is results[0] for r in results)


def test_module_import_loads_neither_onnxruntime_nor_sounddevice() -> None:
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('td', {td.__file__!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules['td'] = module\n"
        "spec.loader.exec_module(module)\n"
        "print(sorted({'onnxruntime', 'sounddevice'} & set(sys.modules)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


# ------------------------------------------------------------- listen_for_turn

_SPEECH = np.full(FRAME, 10000, "<i2").tobytes()
_SILENCE = bytes(2 * FRAME)


class _FakeMic:
    """sounddevice.RawInputStream stand-in: a thread calls the callback.

    It delivers ``blocks``, then (if ``then_silence``) silence until closed.
    """

    def __init__(self, blocks: list[bytes], *, then_silence: bool = True) -> None:
        self.blocks = blocks
        self.then_silence = then_silence
        self.kwargs: dict = {}
        self.opened = False
        self.closed = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    def __enter__(self):
        self.opened = True
        self._thread = threading.Thread(target=self._feed, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.closed = True

    def _feed(self) -> None:
        callback = self.kwargs["callback"]
        for block in self.blocks:
            if self._stop.is_set():
                return
            callback(block, len(block) // 2, None, None)
        while self.then_silence and not self._stop.wait(0.001):
            callback(_SILENCE, FRAME, None, None)


class _EnergyVad:
    def reset(self) -> None:
        pass

    def __call__(self, frame: np.ndarray) -> float:
        return 1.0 if np.abs(frame).max() > 0.1 else 0.0


def _install(monkeypatch, mic: _FakeMic, models=None) -> list[str]:
    paths: list[str] = []

    def fake_load(turn_model_path: str = ""):
        paths.append(turn_model_path)
        return models if models is not None else (_EnergyVad(), _FakeSmartTurn(0.9))

    monkeypatch.setattr(td, "load_turn_models", fake_load)
    monkeypatch.setitem(
        sys.modules, "sounddevice", types.SimpleNamespace(RawInputStream=mic)
    )
    return paths


def test_listen_returns_the_turn_as_wav(monkeypatch) -> None:
    script = b"".join([_SILENCE] * 10 + [_SPEECH] * 20)
    # Blocks that do not line up with frames must be re-framed.
    mic = _FakeMic([script[i : i + 768] for i in range(0, len(script), 768)])
    paths = _install(monkeypatch, mic)
    started = []

    wav = listen_for_turn(
        turn_model_path="model.onnx", on_speech_start=lambda: started.append(1)
    )

    assert paths == ["model.onnx"]
    assert started == [1]
    assert mic.closed
    assert mic.kwargs["samplerate"] == SAMPLE_RATE
    assert mic.kwargs["channels"] == 1
    assert mic.kwargs["dtype"] == "int16"
    assert mic.kwargs["blocksize"] == FRAME
    with wave.open(io.BytesIO(wav), "rb") as wf:
        assert (wf.getframerate(), wf.getnchannels(), wf.getsampwidth()) == (
            SAMPLE_RATE,
            1,
            2,
        )
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), "<i2")
    # 10 silent + 20 speech frames, then the 7 silent frames before Smart Turn.
    expected = np.concatenate(
        [np.zeros(10 * FRAME), np.full(20 * FRAME, 10000), np.zeros(VAD_STOP * FRAME)]
    )
    np.testing.assert_array_equal(pcm, expected)


def test_listen_returns_none_on_start_timeout(monkeypatch) -> None:
    mic = _FakeMic([])
    _install(monkeypatch, mic)
    started = []

    result = listen_for_turn(
        params=TurnParams(start_timeout_secs=0.3),
        on_speech_start=lambda: started.append(1),
    )

    assert result is None
    assert started == []
    assert mic.closed


def test_listen_polls_should_stop_without_audio(monkeypatch) -> None:
    mic = _FakeMic([], then_silence=False)
    _install(monkeypatch, mic)
    polls = []
    deadline = time.monotonic() + 0.3

    def should_stop() -> bool:
        polls.append(1)
        return time.monotonic() >= deadline

    t0 = time.monotonic()
    result = listen_for_turn(should_stop=should_stop)

    assert result is TYPED
    assert time.monotonic() - t0 < 1.5
    assert len(polls) >= 3
    assert mic.closed


def test_listen_stops_mid_turn_when_typing(monkeypatch) -> None:
    mic = _FakeMic([_SPEECH] * 200)
    _install(monkeypatch, mic)
    started = threading.Event()

    result = listen_for_turn(should_stop=started.is_set, on_speech_start=started.set)

    assert result is TYPED
    assert mic.closed


def test_listen_raises_when_vad_is_unavailable(monkeypatch) -> None:
    mic = _FakeMic([])
    _install(monkeypatch, mic, models=(None, None))

    with pytest.raises(RuntimeError, match="voice activity detection unavailable"):
        listen_for_turn()
    assert not mic.opened


def test_listen_lets_keyboard_interrupt_through_and_closes_the_mic(monkeypatch):
    mic = _FakeMic([_SPEECH] * 20)
    _install(monkeypatch, mic)

    def interrupt() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        listen_for_turn(on_speech_start=interrupt)
    assert mic.closed


def _give_up_after(secs: float) -> Callable[[], bool]:
    """should_stop that ends a listen that would otherwise never return."""
    deadline = time.monotonic() + secs
    return lambda: time.monotonic() >= deadline


@pytest.mark.parametrize(
    "blocks",
    [[], [_SILENCE] * 3, [_SILENCE] * 3 + [_SPEECH] * 10],
    ids=["never-starts", "before-speech", "mid-turn"],
)
def test_listen_raises_when_the_microphone_stops_delivering(monkeypatch, blocks):
    monkeypatch.setattr(td, "_MIC_STALL_SECS", 0.3, raising=False)
    monkeypatch.setattr(td, "_MIC_FIRST_BLOCK_SECS", 0.6, raising=False)
    mic = _FakeMic(blocks, then_silence=False)
    _install(monkeypatch, mic)

    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="microphone stopped delivering audio"):
        listen_for_turn(should_stop=_give_up_after(5.0))

    assert time.monotonic() - t0 < 2.0
    assert mic.closed


def test_slow_opening_microphone_gets_a_longer_grace(monkeypatch) -> None:
    # A stream whose first block takes longer than the between-block stall
    # limit (e.g. a Bluetooth headset switching profile) is not an error.
    monkeypatch.setattr(td, "_MIC_STALL_SECS", 0.3, raising=False)
    monkeypatch.setattr(td, "_MIC_FIRST_BLOCK_SECS", 2.0, raising=False)
    mic = _FakeMic([], then_silence=False)
    _install(monkeypatch, mic)

    assert listen_for_turn(should_stop=_give_up_after(0.8)) is TYPED
    assert mic.closed


def test_listen_start_timeout_also_runs_on_the_clock(monkeypatch) -> None:
    mic = _FakeMic([], then_silence=False)
    _install(monkeypatch, mic)

    t0 = time.monotonic()
    result = listen_for_turn(
        params=TurnParams(start_timeout_secs=0.3), should_stop=_give_up_after(5.0)
    )

    assert result is None
    assert time.monotonic() - t0 < 1.5
    assert mic.closed
