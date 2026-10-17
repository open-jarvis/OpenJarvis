"""Tests for TTS backend infrastructure."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSResult

# ---------------------------------------------------------------------------
# TTSResult tests
# ---------------------------------------------------------------------------


def test_tts_result_dataclass():
    result = TTSResult(
        audio=b"fake-audio-bytes",
        format="mp3",
        duration_seconds=3.5,
        voice_id="jarvis-v1",
    )
    assert result.audio == b"fake-audio-bytes"
    assert result.format == "mp3"
    assert result.duration_seconds == 3.5


def test_tts_result_save(tmp_path):
    result = TTSResult(audio=b"fake-mp3-data", format="mp3")
    out = result.save(tmp_path / "test.mp3")
    assert out.exists()
    assert out.read_bytes() == b"fake-mp3-data"


# ---------------------------------------------------------------------------
# Cartesia backend tests
# ---------------------------------------------------------------------------


def test_cartesia_registered():
    from openjarvis.speech.cartesia_tts import CartesiaTTSBackend

    TTSRegistry.register_value("cartesia", CartesiaTTSBackend)
    assert TTSRegistry.contains("cartesia")


def test_cartesia_synthesize():
    from openjarvis.speech.cartesia_tts import CartesiaTTSBackend

    backend = CartesiaTTSBackend(api_key="fake-key")

    with patch(
        "openjarvis.speech.cartesia_tts._cartesia_synthesize",
        return_value=b"fake-audio-mp3-bytes",
    ):
        result = backend.synthesize("Hello world", voice_id="test-voice")

    assert result.audio == b"fake-audio-mp3-bytes"
    assert result.format == "mp3"
    assert result.voice_id == "test-voice"


# ---------------------------------------------------------------------------
# Kokoro backend tests
# ---------------------------------------------------------------------------


def test_kokoro_registered():
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    TTSRegistry.register_value("kokoro", KokoroTTSBackend)
    assert TTSRegistry.contains("kokoro")


def test_kokoro_health_false_without_package():
    import importlib.util

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    # The assertion only holds when kokoro is genuinely absent. With the
    # optional `voice` extra installed, health() legitimately returns True
    # (and loading the model would hit the HF Hub), so skip instead. Check
    # for the package without importing it: an installed kokoro whose spaCy
    # cannot load still counts as installed.
    if importlib.util.find_spec("kokoro") is not None:
        pytest.skip("kokoro installed (openjarvis[voice]); health() is True")

    backend = KokoroTTSBackend()
    # Without kokoro installed, health returns False
    assert backend.health() is False


def test_kokoro_lang_for_voice_mandarin():
    """Mandarin voice IDs (zf_*, zm_*) map to lang_code='z'."""
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    assert KokoroTTSBackend._lang_for_voice("zf_xiaoxiao") == "z"
    assert KokoroTTSBackend._lang_for_voice("zm_yunxi") == "z"


def test_kokoro_lang_for_voice_english_and_other_languages():
    """Voice prefix detection covers English variants and other languages."""
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    assert KokoroTTSBackend._lang_for_voice("af_heart") == "a"
    assert KokoroTTSBackend._lang_for_voice("am_adam") == "a"
    assert KokoroTTSBackend._lang_for_voice("bf_emma") == "b"
    assert KokoroTTSBackend._lang_for_voice("jf_alpha") == "j"
    # Kokoro 0.9.x has no Korean KPipeline language code. Do not route a
    # catalog-style Korean voice ID to an unsupported ``lang_code='k'``.
    assert KokoroTTSBackend._lang_for_voice("kf_example") == "a"


def test_kokoro_lang_for_voice_unknown_falls_back_to_english():
    """Unknown prefixes fall back to American English (Kokoro's most-stocked
    language) rather than crashing — keeps backward-compat for any
    user-supplied voice ID we haven't catalogued."""
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    assert KokoroTTSBackend._lang_for_voice("") == "a"
    assert KokoroTTSBackend._lang_for_voice("xx_unknown") == "a"


def test_kokoro_available_voices_includes_mandarin_and_english():
    """Voice catalog must list at least one Mandarin voice and preserve
    the original English voices for backward compatibility."""
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    voices = KokoroTTSBackend().available_voices()
    # New Mandarin coverage (the focus of this change)
    for v in ("zf_xiaoxiao", "zf_xiaoyi", "zm_yunxi", "zm_yunjian"):
        assert v in voices, f"Mandarin voice {v} missing from catalog"
    # Backward compat — voices the previous implementation listed
    for v in ("af_heart", "af_bella", "am_adam", "am_michael"):
        assert v in voices, f"Existing voice {v} dropped from catalog"


def test_kokoro_missing_chinese_deps_gives_actionable_error(monkeypatch):
    """When Mandarin G2P deps are missing, the user must see an install hint
    pointing at ``misaki[zh]`` rather than a raw ``ordered_set`` ImportError."""
    import sys
    import types

    import pytest

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    class FakeKPipeline:
        def __init__(self, lang_code, model):
            # Mimic what happens inside Kokoro when misaki.zh can't import.
            raise ImportError("No module named 'ordered_set'")

    class FakeKModel:
        def to(self, _device):
            return self

        def eval(self):
            return self

    fake_kokoro = types.SimpleNamespace(KModel=FakeKModel, KPipeline=FakeKPipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)

    backend = KokoroTTSBackend()
    with pytest.raises(RuntimeError) as exc_info:
        backend._ensure_pipeline("z")
    msg = str(exc_info.value)
    assert "misaki[zh]" in msg
    assert "lang_code='z'" in msg or 'lang_code="z"' in msg


def test_kokoro_pipeline_cached_per_language(monkeypatch):
    """Each lang_code instantiates one pipeline; same lang reuses the cache."""
    import sys
    import types

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    init_calls = []

    class FakeKModel:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def to(self, _device):
            return self

        def eval(self):
            return self

    class FakeKPipeline:
        def __init__(self, lang_code, model):
            init_calls.append(lang_code)
            self.model = model

    fake_kokoro = types.SimpleNamespace(KModel=FakeKModel, KPipeline=FakeKPipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)

    backend = KokoroTTSBackend()
    backend._ensure_pipeline("a")
    backend._ensure_pipeline("z")
    backend._ensure_pipeline("a")  # cache hit — must NOT re-instantiate
    backend._ensure_pipeline("z")  # cache hit

    assert init_calls == ["a", "z"]


def test_kokoro_pipeline_cache_is_thread_safe(monkeypatch):
    """Concurrent requests for one language construct exactly one pipeline."""
    import sys
    import threading
    import time
    import types

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    init_calls = []

    class FakeKModel:
        def to(self, _device):
            return self

        def eval(self):
            return self

    class FakeKPipeline:
        def __init__(self, lang_code, model):
            init_calls.append(lang_code)
            time.sleep(0.02)

    monkeypatch.setitem(
        sys.modules,
        "kokoro",
        types.SimpleNamespace(KModel=FakeKModel, KPipeline=FakeKPipeline),
    )
    backend = KokoroTTSBackend()
    pipelines = []

    def load_pipeline():
        pipelines.append(backend._ensure_pipeline("z"))

    threads = [threading.Thread(target=load_pipeline) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()

    assert init_calls == ["z"]
    assert len({id(pipeline) for pipeline in pipelines}) == 1


def test_kokoro_pipeline_cache_evicts_lru_and_cleans_up(monkeypatch):
    """The cache is bounded and closes evicted and explicitly released entries."""
    import sys
    import types

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    instances = {}

    class FakeKModel:
        def to(self, _device):
            return self

        def eval(self):
            return self

    class FakeKPipeline:
        def __init__(self, lang_code, model):
            self.closed = False
            instances[lang_code] = self

        def close(self):
            self.closed = True

    monkeypatch.setitem(
        sys.modules,
        "kokoro",
        types.SimpleNamespace(KModel=FakeKModel, KPipeline=FakeKPipeline),
    )
    backend = KokoroTTSBackend(max_cached_pipelines=2)

    backend._ensure_pipeline("a")
    backend._ensure_pipeline("z")
    backend._ensure_pipeline("a")  # make American English most recently used
    backend._ensure_pipeline("j")

    assert list(backend._pipelines) == ["a", "j"]
    assert instances["z"].closed is True
    assert instances["a"].closed is False
    assert instances["j"].closed is False

    backend.close()
    assert not backend._pipelines
    assert instances["a"].closed is True
    assert instances["j"].closed is True


def test_kokoro_pipeline_cache_size_must_be_positive():
    import pytest

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    with pytest.raises(ValueError, match="at least 1"):
        KokoroTTSBackend(max_cached_pipelines=0)


def test_kokoro_synthesize_routes_voice_to_correct_language(monkeypatch):
    """synthesize() with a Mandarin voice initializes a Mandarin pipeline
    and tags the result metadata with the resolved lang_code."""
    import sys
    import types

    import numpy as np

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    init_args = []
    call_args = []

    class FakeKModel:
        def to(self, device):
            self.device = device
            return self

        def eval(self):
            return self

    class FakeKPipeline:
        def __init__(self, lang_code, model):
            init_args.append(lang_code)
            self.model = model

        def __call__(self, text, voice, speed):
            call_args.append({"text": text, "voice": voice, "speed": speed})
            yield (None, None, np.zeros(2400, dtype=np.float32))

    fake_kokoro = types.SimpleNamespace(KModel=FakeKModel, KPipeline=FakeKPipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_kokoro)

    # ``soundfile`` is a kokoro-runtime dep; stub it so we can test the
    # routing logic without requiring it in the OpenJarvis test env.
    def _fake_sf_write(buf, _samples, _sr, format=None):  # noqa: A002
        buf.write(b"FAKE_AUDIO_BYTES")

    fake_soundfile = types.SimpleNamespace(write=_fake_sf_write)
    monkeypatch.setitem(sys.modules, "soundfile", fake_soundfile)

    backend = KokoroTTSBackend()
    result = backend.synthesize("你好世界", voice_id="zf_xiaoxiao")

    assert init_args == ["z"]
    assert call_args[0]["voice"] == "zf_xiaoxiao"
    assert call_args[0]["text"] == "你好世界"
    assert result.voice_id == "zf_xiaoxiao"
    assert result.metadata["lang_code"] == "z"
    assert result.metadata["backend"] == "kokoro"
    assert result.format == "wav"
    assert len(result.audio) > 0


def test_kokoro_reuses_model_and_honors_path_and_device(monkeypatch):
    """All language pipelines share the configured model instance."""
    import sys
    import types

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    model_inits = []
    model_devices = []
    pipeline_models = []

    class FakeKModel:
        def __init__(self, **kwargs):
            model_inits.append(kwargs)

        def to(self, device):
            model_devices.append(device)
            return self

        def eval(self):
            return self

    class FakeKPipeline:
        def __init__(self, lang_code, model):
            pipeline_models.append((lang_code, model))

    monkeypatch.setitem(
        sys.modules,
        "kokoro",
        types.SimpleNamespace(KModel=FakeKModel, KPipeline=FakeKPipeline),
    )

    backend = KokoroTTSBackend(model_path="/models/kokoro.pth", device="cpu")
    backend._ensure_pipeline("a")
    backend._ensure_pipeline("z")

    assert model_inits == [{"model": "/models/kokoro.pth"}]
    assert model_devices == ["cpu"]
    assert pipeline_models[0][1] is pipeline_models[1][1]


class _FakeKModel:
    def to(self, _device):
        return self

    def eval(self):
        return self


def _serve_kokoro_importing_spacy(
    monkeypatch,
    kpipeline,
    *,
    missing_dep=None,
    import_error=None,
    block_spacy=False,
    after_spacy=None,
):
    """Serve a fake ``kokoro`` that imports spaCy on load, like the real one
    (``kokoro.pipeline`` -> ``misaki.en`` -> ``spacy``)."""
    import importlib.abc
    import importlib.util
    import sys

    class Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, name, path=None, target=None):
            if name != "kokoro" and not (block_spacy and name == "spacy"):
                return None
            return importlib.util.spec_from_loader(name, self)

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            if module.__name__ == "spacy":
                raise ImportError("spaCy native dependency blocked", name="spacy")
            import spacy  # noqa: F401

            if after_spacy:
                after_spacy(spacy)
            if import_error:
                raise import_error
            if missing_dep:
                raise ModuleNotFoundError(
                    f"No module named {missing_dep!r}", name=missing_dep
                )
            module.KModel = _FakeKModel
            module.KPipeline = kpipeline

    monkeypatch.setattr(sys, "meta_path", [Finder(), *sys.meta_path])
    # setitem records the original entry so it is restored after the test;
    # delitem then makes ``import kokoro`` go through the finder above.
    monkeypatch.setitem(sys.modules, "kokoro", None)
    monkeypatch.delitem(sys.modules, "kokoro")


def test_kokoro_tolerates_unloadable_spacy_for_non_english_voices(monkeypatch):
    """A spaCy that cannot load (e.g. DLLs blocked by Windows Smart App
    Control) must not take down voices whose G2P never uses it."""
    import sys

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    pipelines = []

    class FakeKPipeline:
        def __init__(self, lang_code, model):
            pipelines.append(lang_code)

    _serve_kokoro_importing_spacy(monkeypatch, FakeKPipeline)
    monkeypatch.setitem(sys.modules, "spacy", None)  # import spacy -> ImportError

    KokoroTTSBackend(device="cpu")._ensure_pipeline("p")

    assert pipelines == ["p"]
    assert sys.modules["spacy"] is None  # No fake global module after success.
    with pytest.raises(ModuleNotFoundError):
        __import__("spacy")


def test_kokoro_degraded_import_gives_actionable_english_error(monkeypatch):
    import sys

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    _serve_kokoro_importing_spacy(monkeypatch, object)
    monkeypatch.setitem(sys.modules, "spacy", None)
    backend = KokoroTTSBackend(device="cpu")
    assert backend.health() is True
    with pytest.raises(RuntimeError, match="English Kokoro voices require.*spaCy"):
        backend._ensure_pipeline("b")


def test_kokoro_restores_spacy_after_non_import_error(monkeypatch):
    import builtins
    import sys

    from openjarvis.speech.kokoro_tts import _import_kokoro

    _serve_kokoro_importing_spacy(
        monkeypatch, object, import_error=ValueError("bad model config")
    )
    monkeypatch.setitem(sys.modules, "spacy", None)
    original_import = builtins.__import__
    with pytest.raises(ValueError, match="bad model config"):
        _import_kokoro()
    assert sys.modules["spacy"] is None
    assert builtins.__import__ is original_import


def test_kokoro_fallback_does_not_publish_spacy_to_other_threads(monkeypatch):
    """A plain import outside the fallback must see the real failed import."""
    import builtins
    import sys
    import threading

    from openjarvis.speech.kokoro_tts import _import_kokoro

    entered = threading.Event()
    release = threading.Event()
    loaded_shims = []
    retained_importers = []
    retained_import_errors = []
    errors = []

    def pause_fallback(spacy):
        loaded_shims.append(spacy)
        retained_importers.append(builtins.__import__)
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release Kokoro import")

    _serve_kokoro_importing_spacy(
        monkeypatch, object, block_spacy=True, after_spacy=pause_fallback
    )
    monkeypatch.setitem(sys.modules, "spacy", None)
    monkeypatch.delitem(sys.modules, "spacy")
    original_import = builtins.__import__

    def load():
        try:
            _import_kokoro()
            # Even a hook captured by third-party code must stop substituting
            # once the fallback ends, including on the original owner thread.
            try:
                retained_importers[0]("spacy")
            except ImportError as exc:
                retained_import_errors.append(exc)
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=load)
    worker.start()
    try:
        assert entered.wait(5)
        # This thread does not acquire our Kokoro-only import lock.
        with pytest.raises(ImportError, match="spaCy native dependency blocked"):
            __import__("spacy")
        assert "spacy" not in sys.modules
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    assert not errors
    assert len(loaded_shims) == 1
    assert len(retained_import_errors) == 1
    assert builtins.__import__ is original_import


def test_concurrent_kokoro_imports_do_not_leave_a_fake_spacy_module(monkeypatch):
    import sys
    import threading

    from openjarvis.speech.kokoro_tts import _import_kokoro

    _serve_kokoro_importing_spacy(monkeypatch, object, block_spacy=True)
    monkeypatch.setitem(sys.modules, "spacy", None)
    monkeypatch.delitem(sys.modules, "spacy")
    results = []
    errors = []

    def load():
        try:
            results.append(_import_kokoro())
        except Exception as exc:
            errors.append(exc)

    workers = [threading.Thread(target=load) for _ in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert not errors
    assert len(results) == 8
    assert len({id(result) for result in results}) == 1
    assert "spacy" not in sys.modules
    with pytest.raises(ImportError, match="spaCy native dependency blocked"):
        __import__("spacy")


def test_kokoro_preserves_healthy_spacy_when_another_dependency_is_missing(
    monkeypatch,
):
    import sys
    import types

    from openjarvis.speech.kokoro_tts import _import_kokoro

    real_spacy = types.ModuleType("spacy")
    monkeypatch.setitem(sys.modules, "spacy", real_spacy)
    _serve_kokoro_importing_spacy(monkeypatch, object, missing_dep="torch")
    with pytest.raises(ModuleNotFoundError, match="torch"):
        _import_kokoro()
    assert sys.modules["spacy"] is real_spacy


def test_kokoro_health_and_pipeline_share_one_model(monkeypatch):
    import sys
    import threading
    import time
    import types

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    models = []
    errors = []

    class SlowModel(_FakeKModel):
        def __init__(self):
            models.append(self)
            time.sleep(0.02)

    monkeypatch.setitem(
        sys.modules,
        "kokoro",
        types.SimpleNamespace(
            KModel=SlowModel,
            KPipeline=lambda **kwargs: kwargs["model"],
        ),
    )
    backend = KokoroTTSBackend(device="cpu")

    def load(index):
        try:
            if index % 2:
                assert backend.health()
            else:
                backend._ensure_pipeline("p")
        except Exception as exc:
            errors.append(exc)

    workers = [threading.Thread(target=load, args=(i,)) for i in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=2)
        assert not worker.is_alive()
    assert not errors
    assert len(models) == 1
    assert backend._pipelines["p"] is models[0]


def test_kokoro_unloadable_spacy_stub_is_removed_if_kokoro_still_fails(
    monkeypatch,
):
    """When something besides spaCy breaks the import, the stub must not
    linger in ``sys.modules`` and the backend stays unhealthy."""
    import sys

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    _serve_kokoro_importing_spacy(monkeypatch, object, missing_dep="torch")
    monkeypatch.setitem(sys.modules, "spacy", None)

    assert KokoroTTSBackend(device="cpu").health() is False
    assert sys.modules.get("spacy") is None


def test_kokoro_missing_package_leaves_spacy_alone(monkeypatch):
    """No kokoro at all is a plain 'not installed' -- spaCy is not touched."""
    import sys

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    monkeypatch.setitem(sys.modules, "kokoro", None)
    monkeypatch.setitem(sys.modules, "spacy", None)

    assert KokoroTTSBackend().health() is False
    assert sys.modules["spacy"] is None


def test_kokoro_health_does_not_build_english_pipeline(monkeypatch):
    """health() checks the shared model only: a broken English G2P (spaCy +
    en_core_web_sm) must not mark every other language unhealthy."""
    import sys
    import types

    from openjarvis.speech.kokoro_tts import KokoroTTSBackend

    pipelines = []

    class FakeKPipeline:
        def __init__(self, lang_code, model):
            pipelines.append(lang_code)

    monkeypatch.setitem(
        sys.modules,
        "kokoro",
        types.SimpleNamespace(KModel=_FakeKModel, KPipeline=FakeKPipeline),
    )

    assert KokoroTTSBackend(device="cpu").health() is True
    assert pipelines == []


# ---------------------------------------------------------------------------
# OpenAI TTS backend tests
# ---------------------------------------------------------------------------


def test_openai_tts_registered():
    from openjarvis.speech.openai_tts import OpenAITTSBackend

    TTSRegistry.register_value("openai_tts", OpenAITTSBackend)
    assert TTSRegistry.contains("openai_tts")


def test_openai_tts_synthesize():
    from openjarvis.speech.openai_tts import OpenAITTSBackend

    backend = OpenAITTSBackend(api_key="fake-key")

    with patch(
        "openjarvis.speech.openai_tts._openai_tts_request",
        return_value=b"fake-openai-audio",
    ):
        result = backend.synthesize("Hello", voice_id="nova")

    assert result.audio == b"fake-openai-audio"
    assert result.voice_id == "nova"


# ---------------------------------------------------------------------------
# ElevenLabs backend tests
# ---------------------------------------------------------------------------


def test_elevenlabs_registered():
    from openjarvis.speech.elevenlabs_tts import ElevenLabsTTSBackend

    TTSRegistry.register_value("elevenlabs", ElevenLabsTTSBackend)
    assert TTSRegistry.contains("elevenlabs")


def test_elevenlabs_health_requires_key(monkeypatch):
    from openjarvis.speech.elevenlabs_tts import ElevenLabsTTSBackend

    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert ElevenLabsTTSBackend().health() is False
    assert ElevenLabsTTSBackend(api_key="fake-key").health() is True


def test_elevenlabs_synthesize_mp3():
    from openjarvis.speech.elevenlabs_tts import ElevenLabsTTSBackend

    backend = ElevenLabsTTSBackend(api_key="fake-key")
    with patch(
        "openjarvis.speech.elevenlabs_tts._elevenlabs_synthesize",
        return_value=b"fake-mp3",
    ) as synth:
        result = backend.synthesize("Hello", voice_id="abc123XYZ")

    assert result.audio == b"fake-mp3"
    assert result.format == "mp3"
    assert result.voice_id == "abc123XYZ"
    assert synth.call_args.kwargs["voice_id"] == "abc123XYZ"


def test_elevenlabs_synthesize_wav_wraps_pcm():
    import io
    import wave

    from openjarvis.speech.elevenlabs_tts import ElevenLabsTTSBackend

    pcm = b"\x00\x01" * 100
    backend = ElevenLabsTTSBackend(api_key="fake-key")
    with patch(
        "openjarvis.speech.elevenlabs_tts._elevenlabs_synthesize",
        return_value=pcm,
    ) as synth:
        result = backend.synthesize("Hello", output_format="wav")

    assert synth.call_args.kwargs["output_format"] == "wav"
    assert result.format == "wav"
    assert result.sample_rate == 24000
    with wave.open(io.BytesIO(result.audio)) as wf:
        assert wf.getframerate() == 24000
        assert wf.getnchannels() == 1
        assert wf.readframes(wf.getnframes()) == pcm


@pytest.mark.parametrize("kokoro_voice", ["bm_george", "pf_dora", "af_heart"])
def test_elevenlabs_ignores_kokoro_voice_ids(monkeypatch, kokoro_voice):
    # SpeechConfig.voice_id defaults to a Kokoro voice; it must not be sent
    # to ElevenLabs, which would return 404.
    from openjarvis.speech.elevenlabs_tts import (
        _DEFAULT_VOICE_ID,
        ElevenLabsTTSBackend,
    )

    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    backend = ElevenLabsTTSBackend(api_key="fake-key")
    with patch(
        "openjarvis.speech.elevenlabs_tts._elevenlabs_synthesize",
        return_value=b"fake-mp3",
    ) as synth:
        result = backend.synthesize("Olá", voice_id=kokoro_voice)

    assert synth.call_args.kwargs["voice_id"] == _DEFAULT_VOICE_ID
    assert result.voice_id == _DEFAULT_VOICE_ID


def test_elevenlabs_env_voice_used_when_none_given(monkeypatch):
    from openjarvis.speech.elevenlabs_tts import ElevenLabsTTSBackend

    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "envVoice123")
    backend = ElevenLabsTTSBackend(api_key="fake-key")
    with patch(
        "openjarvis.speech.elevenlabs_tts._elevenlabs_synthesize",
        return_value=b"fake-mp3",
    ) as synth:
        backend.synthesize("Hello", voice_id="bm_george")

    assert synth.call_args.kwargs["voice_id"] == "envVoice123"


def test_elevenlabs_speed_is_clamped():
    from openjarvis.speech.elevenlabs_tts import _elevenlabs_synthesize

    with patch("openjarvis.speech.elevenlabs_tts.httpx.post") as post:
        post.return_value.content = b"audio"
        _elevenlabs_synthesize("key", "Hello", voice_id="v", speed=2.0)
        _elevenlabs_synthesize("key", "Hello", voice_id="v", speed=1.0)

    fast, normal = post.call_args_list
    assert fast.kwargs["json"]["voice_settings"] == {"speed": 1.2}
    assert "voice_settings" not in normal.kwargs["json"]


def test_elevenlabs_missing_key_raises(monkeypatch):
    from openjarvis.speech.elevenlabs_tts import ElevenLabsTTSBackend

    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        ElevenLabsTTSBackend().synthesize("Hello")
