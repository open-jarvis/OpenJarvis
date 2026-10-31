"""End-of-turn detection for voice input: Silero VAD v6 + Smart Turn v3.

The microphone is read in 32 ms frames. Silero VAD (the ONNX model shipped
with faster-whisper) finds where speech starts and pauses; at each pause of
``vad_stop_secs`` the Smart Turn v3 classifier (pipecat-ai, BSD-2-Clause)
looks at the whole turn so far and decides whether the speaker is done. A
turn the model judges unfinished still ends after ``turn_stop_secs`` of
silence. Without Smart Turn, a fixed ``fallback_silence_secs`` of silence
ends the turn.

Only numpy is imported at module load: onnxruntime is slow to import and is
loaded by :func:`load_turn_models`, sounddevice by :func:`listen_for_turn`.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import logging
import math
import os
import queue
import socket
import threading
import time
import wave
from collections import deque
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

import numpy as np

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME = 512  # 32 ms, the Silero v6 window at 16 kHz
TYPED = object()  # returned by listen_for_turn when should_stop() becomes true

_FRAME_SECS = FRAME / SAMPLE_RATE
_DEFAULT_VAD_STOP_SECS = 0.2
_MIC_STALL_SECS = 2.0  # no audio block for this long: the microphone is gone
# Opening can be slower (a Bluetooth headset switching to its mic profile).
_MIC_FIRST_BLOCK_SECS = 5.0
_HUB_PROBE_SECS = 2.0

_SMART_TURN_REPO = "pipecat-ai/smart-turn-v3"
_SMART_TURN_FILE = "smart-turn-v3.2-cpu.onnx"
_SMART_TURN_REVISION = "f766f81d3cfdf7737ac64aad813d91bbfd56bf93"
_SMART_TURN_SHA256 = "2bb026316b14a660486a75b1733cd3fbab8c2fd0314dc9af7be49f8cca967e4f"

_warned: set[str] = set()


def _warn_once(message: str) -> None:
    if message not in _warned:
        _warned.add(message)
        logger.warning(message)


@dataclass(frozen=True)
class TurnParams:
    """Tuning of :class:`TurnDetector`; defaults follow Pipecat's Smart Turn setup.

    An unusable ``vad_stop_secs`` is corrected with a warning: not a positive
    number gives the default, and a value at or above ``turn_stop_secs`` is
    lowered so that Smart Turn is still asked before the silence cap.
    """

    vad_threshold: float = 0.5  # Silero default
    vad_neg_threshold: float = 0.35  # hysteresis while speaking, as faster-whisper
    start_secs: float = 0.2  # speech must last this long to start a turn
    pre_roll_secs: float = 0.5  # audio kept from before the speech start
    vad_stop_secs: float = _DEFAULT_VAD_STOP_SECS  # pause that asks Smart Turn
    turn_stop_secs: float = 3.0  # silence cap when Smart Turn says "incomplete"
    fallback_silence_secs: float = 1.0  # silence that ends a turn without Smart Turn
    turn_threshold: float = 0.5  # P(turn complete) above this ends the turn
    start_timeout_secs: float | None = None  # None: wait for speech forever
    max_turn_secs: float = 30.0  # safety ceiling on the turn length
    keep_trailing_secs: float = 0.3  # silence kept after the last speech frame
    quiet_reset_secs: float = 5.0  # reset the Silero state after this much quiet

    def __post_init__(self) -> None:
        stop = self.vad_stop_secs
        if not math.isfinite(stop) or stop <= 0:
            _warn_once(
                f"End-of-turn pause {stop!r} s is not a positive number, "
                f"using {_DEFAULT_VAD_STOP_SECS} s"
            )
            stop = _DEFAULT_VAD_STOP_SECS
        if stop >= self.turn_stop_secs:
            capped = self.turn_stop_secs - _FRAME_SECS
            _warn_once(
                f"End-of-turn pause {stop!r} s reaches the {self.turn_stop_secs} s "
                f"silence cap, so Smart Turn would never be asked; using {capped:g} s"
            )
            stop = capped
        object.__setattr__(self, "vad_stop_secs", stop)


def _frames(secs: float, minimum: int = 1) -> int:
    """Number of whole frames covering ``secs`` (tolerant of float error)."""
    return max(minimum, math.ceil(secs / _FRAME_SECS - 1e-9))


class SileroStream:
    """faster-whisper's ``silero_vad_v6.onnx``, run one frame at a time.

    This export differs from the upstream snakers4 model: it takes rows of
    64 context samples + 512 new samples and explicit LSTM ``h``/``c``
    states, and only works at 16 kHz.
    """

    _CONTEXT = 64

    def __init__(self, path: str) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        self._session = ort.InferenceSession(
            path, providers=["CPUExecutionProvider"], sess_options=options
        )
        inputs = {i.name: i.shape for i in self._session.get_inputs()}
        width = inputs.get("input", [None])[-1]
        if set(inputs) != {"input", "h", "c"} or width != FRAME + self._CONTEXT:
            raise ValueError(f"unexpected Silero VAD inputs in {path}: {inputs}")
        self.reset()

    def reset(self) -> None:
        """Forget the LSTM state and the context samples."""
        self._h = np.zeros((1, 1, 128), np.float32)
        self._c = np.zeros((1, 1, 128), np.float32)
        self._context = np.zeros((1, self._CONTEXT), np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        """Return the speech probability of one 512-sample float32 frame."""
        x = np.asarray(frame, dtype=np.float32).reshape(1, FRAME)
        prob, self._h, self._c = self._session.run(
            None,
            {
                "input": np.concatenate([self._context, x], axis=1),
                "h": self._h,
                "c": self._c,
            },
        )
        self._context = x[:, -self._CONTEXT :].copy()
        return float(np.asarray(prob).reshape(-1)[0])


_N_FFT = 400
_HOP = 160
_N_MELS = 80
_WINDOW_SAMPLES = 8 * SAMPLE_RATE


def _hz_to_mel(freq: np.ndarray) -> np.ndarray:
    freq = np.asarray(freq, dtype=np.float64)
    logstep = 27.0 / np.log(6.4)
    mels = 3.0 * freq / 200.0
    log_mels = 15.0 + np.log(np.maximum(freq, 1e-10) / 1000.0) * logstep
    return np.where(freq >= 1000.0, log_mels, mels)


def _mel_to_hz(mels: np.ndarray) -> np.ndarray:
    mels = np.asarray(mels, dtype=np.float64)
    logstep = np.log(6.4) / 27.0
    freq = 200.0 * mels / 3.0
    log_freq = 1000.0 * np.exp(logstep * (mels - 15.0))
    return np.where(mels >= 15.0, log_freq, freq)


def _mel_filters() -> np.ndarray:
    """Slaney-normalised triangular mel filters, shape (201, 80)."""
    fft_freqs = np.linspace(0, SAMPLE_RATE // 2, _N_FFT // 2 + 1)
    mel_freqs = np.linspace(_hz_to_mel(0.0), _hz_to_mel(SAMPLE_RATE / 2), _N_MELS + 2)
    filter_freqs = _mel_to_hz(mel_freqs)
    diff = np.diff(filter_freqs)
    slopes = filter_freqs[None, :] - fft_freqs[:, None]
    down = -slopes[:, :-2] / diff[:-1]
    up = slopes[:, 2:] / diff[1:]
    filters = np.maximum(0.0, np.minimum(down, up))
    enorm = 2.0 / (filter_freqs[2 : _N_MELS + 2] - filter_freqs[:_N_MELS])
    return filters * enorm[None, :]


_MEL_FILTERS = _mel_filters()
_HANN = np.hanning(_N_FFT + 1)[:-1]  # periodic Hann, as torch.hann_window


def smart_turn_features(audio: np.ndarray) -> np.ndarray:
    """Whisper log-mel features of the last 8 s of 16 kHz mono float audio.

    Shorter audio is zero-padded at the beginning. Returns a (1, 80, 800)
    float32 array, the ``input_features`` Smart Turn v3 expects.
    """
    # Numpy port of transformers' WhisperFeatureExtractor(chunk_length=8,
    # do_normalize=True): mel filters and STFT follow transformers'
    # audio_utils.py (Apache-2.0, Copyright 2022-2023 The HuggingFace Inc.
    # team). The 8 s window with zero padding at the start is the recipe of
    # pipecat-ai/smart-turn's inference.py (BSD-2-Clause, Copyright (c)
    # 2024-2025, Daily).
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(x) >= _WINDOW_SAMPLES:
        x = x[-_WINDOW_SAMPLES:]
    else:
        x = np.pad(x, (_WINDOW_SAMPLES - len(x), 0))
    x = x.astype(np.float64)
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
    padded = np.pad(x, (_N_FFT // 2, _N_FFT // 2), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, _N_FFT)[::_HOP]
    power = np.abs(np.fft.rfft(frames * _HANN, n=_N_FFT, axis=1)) ** 2
    mel = np.maximum(1e-10, power @ _MEL_FILTERS).T
    log_spec = np.log10(mel)[:, :-1]
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0
    return log_spec.astype(np.float32)[None]


class SmartTurn:
    """pipecat-ai Smart Turn v3 ONNX classifier; returns P(turn complete)."""

    def __init__(self, path: str) -> None:
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        # 4 threads: ~15 ms instead of ~40 ms per query on an 8-core laptop.
        options.intra_op_num_threads = min(4, os.cpu_count() or 1)
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.log_severity_level = 4
        self._session = ort.InferenceSession(
            path, providers=["CPUExecutionProvider"], sess_options=options
        )
        inputs = self._session.get_inputs()
        if len(inputs) != 1 or list(inputs[0].shape[1:]) != [_N_MELS, 800]:
            shapes = {i.name: i.shape for i in inputs}
            raise ValueError(f"unexpected Smart Turn inputs in {path}: {shapes}")
        self._input_name = inputs[0].name

    def __call__(self, audio: np.ndarray) -> float:
        """Probability that the turn in ``audio`` (16 kHz float32) is complete."""
        features = smart_turn_features(audio)
        output = self._session.run(None, {self._input_name: features})[0]
        return float(np.asarray(output).reshape(-1)[0])


class TurnDetector:
    """State machine turning a stream of 512-sample frames into one turn.

    States: QUIET -> STARTING -> SPEAKING <-> PAUSED. ``vad`` maps a frame
    to a speech probability (and has ``reset()``); ``smart_turn`` maps the
    turn audio to P(turn complete), or is None for the fixed-silence mode.
    """

    def __init__(self, vad, smart_turn=None, params: TurnParams | None = None) -> None:
        self._vad = vad
        self._smart_turn = smart_turn
        self._params = p = params or TurnParams()
        self._start_frames = _frames(p.start_secs)
        self._vad_stop_frames = _frames(p.vad_stop_secs)
        self._turn_stop_frames = _frames(p.turn_stop_secs)
        self._fallback_frames = _frames(p.fallback_silence_secs)
        self._max_frames = _frames(p.max_turn_secs)
        self._quiet_reset_frames = _frames(p.quiet_reset_secs)
        self._trailing_frames = _frames(p.keep_trailing_secs, minimum=0)
        self._timeout_frames = (
            None if p.start_timeout_secs is None else _frames(p.start_timeout_secs)
        )
        self._ring: deque[np.ndarray] = deque(
            maxlen=_frames(p.pre_roll_secs + p.start_secs)
        )
        self._turn: list[np.ndarray] = []
        self._state = "QUIET"
        self._run = 0  # consecutive speech (STARTING) or silence (PAUSED) frames
        self._n = 0
        self._quiet = 0
        self._last_speech = 0
        self._asked_this_pause = False
        self._vad.reset()

    def _secs(self) -> float:
        return self._n * _FRAME_SECS

    def feed(self, frame: np.ndarray) -> str | None:
        """Process one frame.

        Returns None to keep listening, ``"started"`` once when speech
        begins, ``"end"`` when the turn is over and ``"timeout"`` when no
        speech started within ``start_timeout_secs``.
        """
        p = self._params
        self._n += 1
        prob = self._vad(frame)
        if self._state in ("QUIET", "STARTING"):
            return self._feed_waiting(frame, prob)

        self._turn.append(frame)
        threshold = p.vad_threshold if self._state == "PAUSED" else p.vad_neg_threshold
        if prob >= threshold:
            if self._state == "PAUSED":
                logger.debug(
                    "%.2fs speech resumes after %.2fs",
                    self._secs(),
                    self._run * _FRAME_SECS,
                )
            self._state, self._run, self._asked_this_pause = "SPEAKING", 0, False
            self._last_speech = len(self._turn) - 1
        else:
            self._state = "PAUSED"
            self._run += 1
            if self._pause_ends_turn():
                return "end"
        if len(self._turn) >= self._max_frames:
            logger.debug("%.2fs maximum turn length reached", self._secs())
            return "end"
        return None

    def _feed_waiting(self, frame: np.ndarray, prob: float) -> str | None:
        p = self._params
        self._ring.append(frame)
        if prob >= p.vad_threshold:
            self._run = self._run + 1 if self._state == "STARTING" else 1
            self._state = "STARTING"
            if self._run >= self._start_frames:
                self._state, self._run, self._asked_this_pause = "SPEAKING", 0, False
                self._turn = list(self._ring)
                self._last_speech = len(self._turn) - 1
                logger.debug(
                    "%.2fs speech start (%.2fs with pre-roll)",
                    self._secs(),
                    len(self._turn) * _FRAME_SECS,
                )
                return "started"
        else:
            self._state, self._run = "QUIET", 0
            self._quiet += 1
            # Long waits let the LSTM state drift; Pipecat resets it likewise.
            if prob < 0.1 and self._quiet >= self._quiet_reset_frames:
                self._vad.reset()
                self._quiet = 0
        # Not while STARTING: that ends on its own within start_secs.
        if (
            self._timeout_frames is not None
            and self._state == "QUIET"
            and self._n >= self._timeout_frames
        ):
            logger.debug("%.2fs no speech, start timeout", self._secs())
            return "timeout"
        return None

    def _pause_ends_turn(self) -> bool:
        silence = self._run * _FRAME_SECS
        if self._smart_turn is None:
            if self._run >= self._fallback_frames:
                logger.debug("%.2fs %.2fs of silence", self._secs(), silence)
                return True
            return False
        if not self._asked_this_pause and self._run >= self._vad_stop_frames:
            self._asked_this_pause = True
            try:
                prob_end = self._smart_turn(np.concatenate(self._turn))
            except Exception as exc:
                _warn_once(f"Smart Turn failed, ending turns on silence only: {exc}")
                self._smart_turn = None
                return False
            logger.debug(
                "%.2fs pause %.2fs, Smart Turn P(end)=%.2f",
                self._secs(),
                silence,
                prob_end,
            )
            if prob_end > self._params.turn_threshold:
                return True
        if self._run >= self._turn_stop_frames:
            logger.debug("%.2fs silence cap reached", self._secs())
            return True
        return False

    def audio(self) -> np.ndarray:
        """The turn as float32, trimmed to ``keep_trailing_secs`` after speech."""
        if not self._turn:
            return np.zeros(0, np.float32)
        keep = self._last_speech + 1 + self._trailing_frames
        return np.concatenate(self._turn[:keep]).astype(np.float32, copy=False)


_models_lock = threading.Lock()
_models: dict[str, tuple[SileroStream | None, SmartTurn | None]] = {}


def load_turn_models(
    turn_model_path: str = "",
) -> tuple[SileroStream | None, SmartTurn | None]:
    """Load (once per path) the Silero VAD and the Smart Turn model.

    Never raises. Returns ``(None, None)`` when onnxruntime or faster-whisper's
    Silero asset is unavailable, ``(vad, None)`` when only Smart Turn cannot
    be loaded. ``turn_model_path`` overrides the Hugging Face download and is
    trusted as is (no checksum). Importing onnxruntime can take several
    seconds, so callers may want to run this in a background thread first.
    """
    # A plain acquire() would hide Ctrl-C on Windows while a preload runs.
    while not _models_lock.acquire(timeout=0.1):
        pass
    try:
        models = _models.get(turn_model_path)
        if models is None:
            models = _models[turn_model_path] = _load_models(turn_model_path)
        return models
    finally:
        _models_lock.release()


def _load_models(
    turn_model_path: str,
) -> tuple[SileroStream | None, SmartTurn | None]:
    try:
        import onnxruntime  # noqa: F401
    except Exception as exc:
        logger.warning("onnxruntime unavailable, no voice activity detection: %s", exc)
        return None, None
    try:
        vad = SileroStream(_silero_path())
    except Exception as exc:
        logger.warning("Silero VAD unavailable: %s", exc)
        return None, None
    try:
        path = os.path.expanduser(turn_model_path) or _smart_turn_path()
        smart_turn = SmartTurn(path)
    except Exception as exc:
        logger.warning(
            "Smart Turn model unavailable, ending turns on silence only: %s", exc
        )
        smart_turn = None
    return vad, smart_turn


def _silero_path() -> str:
    # find_spec locates the package without importing it (~5 s when cold).
    spec = importlib.util.find_spec("faster_whisper")
    if spec is None or not spec.submodule_search_locations:
        raise FileNotFoundError("faster-whisper is not installed")
    package_dir = list(spec.submodule_search_locations)[0]
    path = os.path.join(package_dir, "assets", "silero_vad_v6.onnx")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return path


def _smart_turn_path() -> str:
    """Cached or freshly downloaded Smart Turn model, checksum-verified.

    Downloads only when the Hub answers a quick probe: listening waits for
    this, and huggingface_hub's own retries can stall for minutes offline.
    """
    from huggingface_hub import hf_hub_download

    try:
        # Once cached, skip the Hub check (~0.7 s, up to a 10 s timeout offline).
        path = hf_hub_download(
            _SMART_TURN_REPO,
            _SMART_TURN_FILE,
            revision=_SMART_TURN_REVISION,
            local_files_only=True,
        )
    except Exception:
        _check_hub_reachable()
        path = hf_hub_download(
            _SMART_TURN_REPO, _SMART_TURN_FILE, revision=_SMART_TURN_REVISION
        )
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != _SMART_TURN_SHA256:
        raise ValueError(f"{path} has sha256 {digest}, expected {_SMART_TURN_SHA256}")
    return path


def _check_hub_reachable() -> None:
    """Raise OSError at once when the model cannot be downloaded right now."""
    from huggingface_hub import constants

    flag = os.environ.get("HF_HUB_OFFLINE", "").strip().upper()
    if constants.HF_HUB_OFFLINE or flag in {"1", "ON", "YES", "TRUE"}:
        raise OSError(
            f"{_SMART_TURN_FILE} is not in the Hugging Face cache and "
            "HF_HUB_OFFLINE is set"
        )
    endpoint = urlsplit(constants.ENDPOINT)
    host = endpoint.hostname or "huggingface.co"
    port = endpoint.port or (80 if endpoint.scheme == "http" else 443)
    try:
        socket.create_connection((host, port), timeout=_HUB_PROBE_SECS).close()
    except OSError as exc:
        raise OSError(
            f"{_SMART_TURN_FILE} is not in the Hugging Face cache and "
            f"{host}:{port} is unreachable ({exc})"
        ) from None


def _to_wav(audio: np.ndarray) -> bytes:
    pcm = np.clip(np.round(audio * 32768.0), -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def listen_for_turn(
    *,
    params: TurnParams | None = None,
    turn_model_path: str = "",
    should_stop: Callable[[], bool] | None = None,
    on_speech_start: Callable[[], None] | None = None,
) -> bytes | None | object:
    """Record one spoken turn from the default microphone.

    Returns the turn as WAV bytes (16 kHz mono 16-bit), None when no speech
    started within ``params.start_timeout_secs``, or :data:`TYPED` as soon
    as ``should_stop()`` returns true. ``on_speech_start`` is called once
    when speech begins. Raises RuntimeError when voice activity detection
    is unavailable, so the caller can fall back to plain recording, and
    when the microphone stops delivering audio.
    """
    vad, smart_turn = load_turn_models(turn_model_path)
    if vad is None:
        raise RuntimeError("voice activity detection unavailable")
    try:
        import sounddevice as sd
    except ImportError:
        raise RuntimeError(
            "sounddevice is required for voice input. "
            "Install with: pip install sounddevice"
        )

    params = params or TurnParams()
    detector = TurnDetector(vad, smart_turn, params)
    blocks: queue.SimpleQueue[bytes] = queue.SimpleQueue()

    def _on_audio(indata, frames, time_info, status) -> None:
        if status:
            logger.debug("microphone status: %s", status)
        blocks.put(bytes(indata))

    pending = np.zeros(0, np.float32)
    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=FRAME,
        callback=_on_audio,
    ):
        last_block = time.monotonic()
        stall_limit = _MIC_FIRST_BLOCK_SECS
        deadline = (
            None
            if params.start_timeout_secs is None
            else last_block + params.start_timeout_secs
        )
        while True:
            if should_stop is not None and should_stop():
                return TYPED
            # Counting frames alone never times out a microphone that delivers
            # too little; queued blocks may still hold speech begun in time.
            if (
                deadline is not None
                and time.monotonic() >= deadline
                and detector._state == "QUIET"
                and blocks.empty()
            ):
                return None
            try:
                # A blocking get() would keep Ctrl-C from being seen on Windows.
                raw = blocks.get(timeout=0.1)
            except queue.Empty:
                if time.monotonic() - last_block > stall_limit:
                    raise RuntimeError("microphone stopped delivering audio") from None
                continue
            last_block = time.monotonic()
            stall_limit = _MIC_STALL_SECS
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            pending = np.concatenate([pending, samples])
            while len(pending) >= FRAME:
                frame, pending = pending[:FRAME], pending[FRAME:]
                verdict = detector.feed(frame)
                if verdict == "started":
                    if on_speech_start is not None:
                        on_speech_start()
                elif verdict == "timeout":
                    return None
                elif verdict == "end":
                    return _to_wav(detector.audio())


__all__ = [
    "FRAME",
    "SAMPLE_RATE",
    "TYPED",
    "SileroStream",
    "SmartTurn",
    "TurnDetector",
    "TurnParams",
    "listen_for_turn",
    "load_turn_models",
    "smart_turn_features",
]
