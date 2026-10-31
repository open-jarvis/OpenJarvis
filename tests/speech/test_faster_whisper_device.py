"""Device handling of the Faster-Whisper backend: warm-up and CPU fallback."""

from __future__ import annotations

import builtins
import logging
import sys
import types
from unittest.mock import MagicMock

import pytest

from openjarvis.speech import faster_whisper as fw
from openjarvis.speech.faster_whisper import FasterWhisperBackend

_CUBLAS_ERROR = "Library cublas64_12.dll is not found or cannot be loaded"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Keep tests hermetic: no real torch import, no compute-type probing."""
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
    monkeypatch.setattr(fw, "ctranslate2", None)


def _info():
    return MagicMock(language="fr", language_probability=0.9, duration=1.0)


def _segment(text):
    return MagicMock(text=text, start=0.0, end=1.0)


def _model(device="cuda", warmup_error=None, warmup_failures=None):
    """Mock WhisperModel; a transcribe() call on an array is a warm-up.

    Warm-ups raise ``warmup_error`` (all of them, or only the first
    ``warmup_failures``). Like the real backend, a missing cuBLAS only
    surfaces while the lazy segment generator is consumed, not when
    transcribe() returns.
    """
    model = MagicMock()
    model.model.device = device
    state = {"consumed": 0, "failures": 0}

    def segments(items, warm_up):
        state["consumed"] += 1
        if (
            warm_up
            and warmup_error is not None
            and (warmup_failures is None or state["failures"] < warmup_failures)
        ):
            state["failures"] += 1
            raise warmup_error
        yield from items

    def transcribe(audio, **kwargs):
        if isinstance(audio, str):
            return segments([_segment(" Bonjour")], False), _info()
        return segments([], True), _info()

    model.transcribe.side_effect = transcribe
    model.state = state
    return model


def _warmup_calls(model):
    return [c for c in model.transcribe.call_args_list if not isinstance(c[0][0], str)]


def test_cpu_device_skips_warmup(monkeypatch):
    model = _model(device="cpu")
    factory = MagicMock(return_value=model)
    monkeypatch.setattr(fw, "WhisperModel", factory)

    backend = FasterWhisperBackend(model_size="base", device="cpu")

    assert backend.health() is True
    model.transcribe.assert_not_called()
    factory.assert_called_once_with("base", device="cpu", compute_type="float16")
    assert backend.effective_device == "cpu"
    assert backend.fallback_reason is None


def test_cuda_warmup_success_keeps_gpu_model(monkeypatch):
    import numpy as np

    model = _model(device="cuda")
    factory = MagicMock(return_value=model)
    monkeypatch.setattr(fw, "WhisperModel", factory)

    backend = FasterWhisperBackend(
        model_size="base", device="cuda", compute_type="float16"
    )

    assert backend.health() is True
    assert backend._ensure_model() is model
    factory.assert_called_once_with("base", device="cuda", compute_type="float16")
    model.transcribe.assert_called_once()
    (audio,), kwargs = model.transcribe.call_args
    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert audio.shape == (16000,)
    assert not audio.any()
    assert kwargs == {"language": "en", "beam_size": 1}
    assert backend.effective_device == "cuda"
    assert backend.fallback_reason is None
    assert backend.last_error() is None


def test_warmup_consumes_segment_generator(monkeypatch):
    model = _model(device="cuda")
    monkeypatch.setattr(fw, "WhisperModel", MagicMock(return_value=model))

    FasterWhisperBackend(device="cuda")._ensure_model()

    assert model.state["consumed"] == 1


def test_auto_device_reports_device_chosen_by_ctranslate2(monkeypatch):
    model = _model(device="cuda")
    monkeypatch.setattr(fw, "WhisperModel", MagicMock(return_value=model))

    backend = FasterWhisperBackend(device="auto")
    backend._ensure_model()

    assert len(_warmup_calls(model)) == 1
    assert backend.effective_device == "cuda"


def test_auto_device_resolved_to_cpu_skips_warmup(monkeypatch):
    model = _model(device="cpu")
    factory = MagicMock(return_value=model)
    monkeypatch.setattr(fw, "WhisperModel", factory)

    backend = FasterWhisperBackend(model_size="base", device="auto")

    assert backend.health() is True
    assert backend._ensure_model() is model
    factory.assert_called_once_with("base", device="auto", compute_type="float16")
    model.transcribe.assert_not_called()
    assert backend.effective_device == "cpu"
    assert backend.fallback_reason is None


def test_effective_device_and_fallback_reason_are_read_only():
    backend = FasterWhisperBackend()

    assert backend.effective_device is None
    assert backend.fallback_reason is None
    with pytest.raises(AttributeError):
        backend.effective_device = "cuda"
    with pytest.raises(AttributeError):
        backend.fallback_reason = "x"


def test_transient_warmup_failure_is_retried_once(monkeypatch, caplog):
    model = _model(
        device="cuda",
        warmup_error=RuntimeError("CUDA failed with error out of memory"),
        warmup_failures=1,
    )
    factory = MagicMock(return_value=model)
    monkeypatch.setattr(fw, "WhisperModel", factory)
    warmups_before_gc = []
    monkeypatch.setattr(
        fw.gc, "collect", lambda: warmups_before_gc.append(len(_warmup_calls(model)))
    )

    backend = FasterWhisperBackend(device="cuda")
    with caplog.at_level(logging.WARNING, logger=fw.__name__):
        assert backend.health() is True

    assert backend._ensure_model() is model
    factory.assert_called_once()
    assert len(_warmup_calls(model)) == 2
    assert warmups_before_gc == [1]
    assert backend.effective_device == "cuda"
    assert backend.fallback_reason is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_cuda_load_failure_falls_back_to_cpu_int8(monkeypatch, caplog):
    cpu_model = _model(device="cpu")
    factory = MagicMock(
        side_effect=[RuntimeError("CUDA failed with error out of memory"), cpu_model]
    )
    monkeypatch.setattr(fw, "WhisperModel", factory)

    backend = FasterWhisperBackend(
        model_size="base", device="cuda", compute_type="float16"
    )
    with caplog.at_level(logging.WARNING, logger=fw.__name__):
        assert backend.health() is True

    assert backend._ensure_model() is cpu_model
    assert [c.kwargs for c in factory.call_args_list] == [
        {"device": "cuda", "compute_type": "float16"},
        {"device": "cpu", "compute_type": "int8"},
    ]
    cpu_model.transcribe.assert_not_called()
    assert backend.effective_device == "cpu"
    assert backend.last_error() is None
    reason = backend.fallback_reason or ""
    assert "model load" in reason
    assert "'cuda'" in reason
    assert "out of memory" in reason

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "'cuda'" in message
    assert "out of memory" in message
    assert "'cpu'" in message


def test_cuda_and_cpu_load_failures_report_unhealthy_then_retry(monkeypatch):
    gpu_model = _model(device="cuda")
    factory = MagicMock(
        side_effect=[
            RuntimeError("CUDA driver version is insufficient"),
            OSError("model files missing"),
            gpu_model,
        ]
    )
    monkeypatch.setattr(fw, "WhisperModel", factory)

    backend = FasterWhisperBackend(device="cuda")

    assert backend.health() is False
    assert "model files missing" in (backend.last_error() or "")
    assert backend._model is None
    assert backend.effective_device is None
    assert "driver version is insufficient" in (backend.fallback_reason or "")

    assert backend.health() is True
    assert backend._ensure_model() is gpu_model
    assert backend.effective_device == "cuda"
    assert backend.fallback_reason is None
    assert backend.last_error() is None


def test_cuda_warmup_failure_falls_back_to_cpu_int8(monkeypatch, caplog):
    gpu_model = _model(device="cuda", warmup_error=RuntimeError(_CUBLAS_ERROR))
    cpu_model = _model(device="cpu")
    factory = MagicMock(side_effect=[gpu_model, cpu_model])
    monkeypatch.setattr(fw, "WhisperModel", factory)

    backend = FasterWhisperBackend(
        model_size="base", device="cuda", compute_type="float16"
    )
    with caplog.at_level(logging.WARNING, logger=fw.__name__):
        assert backend.health() is True

    assert factory.call_count == 2
    assert factory.call_args_list[0].kwargs == {
        "device": "cuda",
        "compute_type": "float16",
    }
    assert factory.call_args_list[1].args == ("base",)
    assert factory.call_args_list[1].kwargs == {
        "device": "cpu",
        "compute_type": "int8",
    }
    assert backend.effective_device == "cpu"
    assert backend.last_error() is None
    cpu_model.transcribe.assert_not_called()
    assert gpu_model.transcribe.call_count == 2
    reason = backend.fallback_reason or ""
    assert "warm-up" in reason
    assert "cublas64_12.dll" in reason

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "'cuda'" in message
    assert "cublas64_12.dll" in message
    assert "cpu" in message

    result = backend.transcribe(b"fake audio bytes", language="fr")

    assert result.text == "Bonjour"
    cpu_model.transcribe.assert_called_once()
    assert cpu_model.transcribe.call_args.kwargs == {"language": "fr"}
    assert gpu_model.transcribe.call_count == 2


def test_warmup_error_raised_by_transcribe_call_also_falls_back(monkeypatch):
    gpu_model = MagicMock()
    gpu_model.transcribe.side_effect = RuntimeError("CUDA failed with error 35")
    cpu_model = _model(device="cpu")
    factory = MagicMock(side_effect=[gpu_model, cpu_model])
    monkeypatch.setattr(fw, "WhisperModel", factory)

    backend = FasterWhisperBackend(device="cuda")

    assert backend._ensure_model() is cpu_model
    assert gpu_model.transcribe.call_count == 2
    assert backend.effective_device == "cpu"
    assert "CUDA failed with error 35" in (backend.fallback_reason or "")


def test_cpu_fallback_load_error_keeps_health_semantics(monkeypatch):
    gpu_model = _model(device="cuda", warmup_error=RuntimeError(_CUBLAS_ERROR))
    factory = MagicMock(side_effect=[gpu_model, OSError("model files missing")])
    monkeypatch.setattr(fw, "WhisperModel", factory)

    backend = FasterWhisperBackend(device="cuda")

    assert backend.health() is False
    assert "model files missing" in (backend.last_error() or "")
    assert backend._model is None


@pytest.fixture
def import_log(monkeypatch):
    """Record every module name passed to ``import``."""
    names = []
    real_import = builtins.__import__

    def recording_import(name, *args, **kwargs):
        names.append(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", recording_import)
    return names


@pytest.mark.parametrize(
    ("platform", "device", "expected"),
    [
        ("win32", "cuda", True),
        ("win32", "auto", True),
        ("win32", "cpu", False),
        ("linux", "cuda", False),
        ("linux", "auto", False),
    ],
)
def test_torch_preload_only_on_windows_non_cpu(
    monkeypatch, import_log, platform, device, expected
):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(
        fw, "WhisperModel", MagicMock(return_value=_model(device=device))
    )

    FasterWhisperBackend(device=device)._ensure_model()

    assert ("torch" in import_log) is expected


@pytest.mark.parametrize("error", [ImportError, OSError])
def test_torch_preload_failure_is_ignored(monkeypatch, error):
    monkeypatch.setattr(sys, "platform", "win32")
    real_import = builtins.__import__

    def failing_import(name, *args, **kwargs):
        if name == "torch":
            raise error("torch unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", failing_import)
    model = _model(device="cuda")
    monkeypatch.setattr(fw, "WhisperModel", MagicMock(return_value=model))

    backend = FasterWhisperBackend(device="cuda")

    assert backend._ensure_model() is model
    assert backend.effective_device == "cuda"
