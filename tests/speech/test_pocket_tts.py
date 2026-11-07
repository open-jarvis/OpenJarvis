"""Kyutai Pocket TTS backend: device placement, quantization, and loading.

pocket-tts, torch and soundfile are stubbed so these run without the
optional speech stack installed.
"""

from __future__ import annotations

import sys
import threading
import time
import types

import numpy as np
import pytest

from openjarvis.speech.pocket_tts import PocketTTSBackend


class _Audio:
    def __init__(self, samples: np.ndarray) -> None:
        self._samples = samples

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self._samples


@pytest.fixture
def fake_pocket(monkeypatch):
    """Install a fake ``pocket_tts`` and ``soundfile``; return a call log."""
    log: dict = {
        "loads": [],
        "moves": [],
        "prompts": [],
        "generations": [],
        "streams": [],
    }

    class FakeModel:
        sample_rate = 24000

        @classmethod
        def load_model(cls, **kwargs):
            time.sleep(0.02)  # widen the race window for the locking test
            log["loads"].append(kwargs)
            return cls()

        def to(self, device):
            log["moves"].append(device)
            return self

        def get_state_for_audio_prompt(self, voice):
            log["prompts"].append(voice)
            return {"voice": voice}

        def generate_audio(self, state, text, max_tokens=50):
            log["generations"].append((state["voice"], text, max_tokens))
            return _Audio(np.zeros(2400, dtype=np.float32))

        def generate_audio_stream(self, state, text, max_tokens=50):
            log["streams"].append((state["voice"], text, max_tokens))
            for i in range(3):
                yield _Audio(np.full(1920, i, dtype=np.float64))

    monkeypatch.setitem(
        sys.modules, "pocket_tts", types.SimpleNamespace(TTSModel=FakeModel)
    )

    def _fake_sf_write(buf, _samples, _sr, format=None):  # noqa: A002
        buf.write(b"RIFF-FAKE")

    monkeypatch.setitem(
        sys.modules, "soundfile", types.SimpleNamespace(write=_fake_sf_write)
    )
    return log


def test_cpu_loads_quantized_and_stays_on_cpu(fake_pocket):
    PocketTTSBackend(device="cpu").synthesize("Salut.", voice_id="estelle")
    assert fake_pocket["loads"] == [{"language": "french_24l", "quantize": True}]
    assert fake_pocket["moves"] == []


def test_gpu_loads_full_precision_and_moves_model(fake_pocket):
    PocketTTSBackend(device="cuda").synthesize("Salut.", voice_id="estelle")
    assert fake_pocket["loads"] == [{"language": "french_24l", "quantize": False}]
    assert fake_pocket["moves"] == ["cuda"]


@pytest.mark.parametrize("cuda_available, device", [(True, "cuda"), (False, "cpu")])
def test_auto_device_follows_cuda_availability(
    monkeypatch, fake_pocket, cuda_available, device
):
    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: cuda_available)
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    PocketTTSBackend().synthesize("Salut.", voice_id="estelle")
    assert fake_pocket["loads"][0]["quantize"] is (device == "cpu")
    assert fake_pocket["moves"] == ([device] if device != "cpu" else [])


def test_voice_selects_its_language_and_long_text_is_not_truncated(fake_pocket):
    result = PocketTTSBackend(device="cpu").synthesize("Hello.", voice_id="alba")
    assert fake_pocket["loads"][0]["language"] == "english"
    assert fake_pocket["generations"][0][2] > 50
    assert result.metadata == {"backend": "pocket", "language": "english"}
    assert result.sample_rate == 24000
    assert result.duration_seconds == pytest.approx(0.1)


def test_preload_warms_model_and_voice_once(fake_pocket):
    backend = PocketTTSBackend(device="cuda")
    backend.preload("estelle")
    backend.synthesize("Bonjour Denis.", voice_id="estelle")
    assert len(fake_pocket["loads"]) == 1
    assert fake_pocket["prompts"] == ["estelle"]
    assert [g[1] for g in fake_pocket["generations"]] == ["Bonjour.", "Bonjour Denis."]


def test_synthesize_stream_yields_float32_frames_in_order(fake_pocket):
    backend = PocketTTSBackend(device="cuda")
    frames = list(backend.synthesize_stream("Bonjour Denis.", voice_id="estelle"))
    assert [rate for _, rate in frames] == [24000, 24000, 24000]
    assert [s.dtype for s, _ in frames] == [np.float32] * 3
    assert [int(s[0]) for s, _ in frames] == [0, 1, 2]
    assert fake_pocket["streams"][0][1] == "Bonjour Denis."
    assert fake_pocket["streams"][0][2] > 50
    assert len(fake_pocket["loads"]) == 1


def test_concurrent_preload_and_synthesis_load_the_model_once(fake_pocket):
    backend = PocketTTSBackend(device="cuda")
    threads = [
        threading.Thread(target=backend.preload, args=("estelle",)),
        threading.Thread(
            target=backend.synthesize, args=("Salut.",), kwargs={"voice_id": "estelle"}
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(fake_pocket["loads"]) == 1
    assert fake_pocket["moves"] == ["cuda"]
