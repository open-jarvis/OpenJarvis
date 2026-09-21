"""Tests for the in-process Apple Foundation Models engine.

The real ``apple-fm-sdk`` builds Swift bindings and only runs on macOS 26+
with Apple Intelligence, and there is no macOS CI runner, so these tests
inject a stub SDK into ``sys.modules`` before importing the engine. The stub
mirrors the shapes the engine actually depends on:

* ``stream_response`` yields **cumulative** snapshots, not deltas
* ``token_count`` is async and takes either a value or a transcript
* ``is_available`` is an *instance* method returning ``(bool, reason)``

The pure helpers in ``_apple_fm_support`` need no stub at all and are tested
directly.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from typing import Any

import pytest

from openjarvis.core.types import Message, Role

# ---------------------------------------------------------------------------
# Pure helpers — no SDK needed
# ---------------------------------------------------------------------------


class TestSnapshotAccumulator:
    def test_cumulative_snapshots_become_deltas(self):
        from openjarvis.engine._apple_fm_support import snapshot_deltas

        # The SDK re-sends everything generated so far on each iteration.
        snapshots = ["The", "The capital", "The capital is Paris."]
        assert snapshot_deltas(snapshots) == [
            "The",
            " capital",
            " is Paris.",
        ]

    def test_naive_concatenation_would_have_duplicated(self):
        from openjarvis.engine._apple_fm_support import SnapshotAccumulator

        acc = SnapshotAccumulator()
        for snap in ["a", "ab", "abc"]:
            acc.add(snap)
        # Appending each chunk (what every delta-based backend does) would
        # give "aababc"; the accumulator tracks the snapshot instead.
        assert acc.text == "abc"

    def test_repeated_snapshot_yields_nothing(self):
        from openjarvis.engine._apple_fm_support import snapshot_deltas

        assert snapshot_deltas(["ab", "ab", "abc"]) == ["ab", "c"]

    def test_revised_snapshot_is_reported_whole(self):
        """Guided generation can revise rather than extend."""
        from openjarvis.engine._apple_fm_support import snapshot_deltas

        assert snapshot_deltas(["hello wor", "goodbye"]) == ["hello wor", "goodbye"]


class TestModelLabels:
    def test_known_labels_normalize(self):
        from openjarvis.engine._apple_fm_support import validate_model_label

        assert validate_model_label("  AFM-3-Core  ") == "afm-3-core"

    def test_unknown_label_names_the_alternatives(self):
        from openjarvis.engine._apple_fm_support import validate_model_label

        with pytest.raises(ValueError, match="afm-3-core-advanced"):
            validate_model_label("afm-4")


class TestOptionsAndSampling:
    def test_max_tokens_maps_to_sdk_name(self):
        from openjarvis.engine._apple_fm_support import build_options_kwargs

        kwargs = build_options_kwargs({"max_tokens": "128", "temperature": "0.5"})
        assert kwargs == {"maximum_response_tokens": 128, "temperature": 0.5}

    def test_unset_values_defer_to_the_sdk(self):
        from openjarvis.engine._apple_fm_support import build_options_kwargs

        assert build_options_kwargs({}) == {}

    def test_sampling_defaults_to_greedy_for_reproducibility(self):
        from openjarvis.engine._apple_fm_support import parse_sampling_spec

        assert parse_sampling_spec({}) == ("greedy", {})

    def test_random_sampling_carries_its_fields(self):
        from openjarvis.engine._apple_fm_support import parse_sampling_spec

        mode, kwargs = parse_sampling_spec(
            {"sampling": "random", "seed": "7", "top": 3}
        )
        assert mode == "random"
        assert kwargs == {"seed": 7, "top": 3}

    def test_unknown_sampling_mode_rejected(self):
        from openjarvis.engine._apple_fm_support import parse_sampling_spec

        with pytest.raises(ValueError, match="greedy"):
            parse_sampling_spec({"sampling": "beam"})


# ---------------------------------------------------------------------------
# Stub SDK
# ---------------------------------------------------------------------------


class _Recorder(dict):
    pass


def _install_stub_sdk(
    *,
    available: tuple[bool, Any] = (True, None),
    snapshots: list[str] | None = None,
    token_counts: list[int] | None = None,
    raise_on_stream: str | None = None,
) -> _Recorder:
    """Inject a fake ``apple_fm_sdk`` and return a call recorder."""
    rec = _Recorder(
        options=[],
        sessions=[],
        stream_calls=[],
        token_count_calls=[],
        models=[],
    )
    sdk = types.ModuleType("apple_fm_sdk")

    class SystemLanguageModelUseCase:
        GENERAL = "general"
        CONTENT_TAGGING = "content_tagging"

    class SystemLanguageModelGuardrails:
        DEFAULT = "default"
        PERMISSIVE_CONTENT_TRANSFORMATIONS = "permissive"

    class SamplingMode:
        @staticmethod
        def greedy(**kw):
            return ("greedy", kw)

        @staticmethod
        def random(**kw):
            return ("random", kw)

    class GenerationOptions:
        def __init__(
            self, temperature=None, maximum_response_tokens=None, sampling=None
        ):
            self.temperature = temperature
            self.maximum_response_tokens = maximum_response_tokens
            self.sampling = sampling
            rec["options"].append(self)

    class ExceededContextWindowSizeError(Exception):
        pass

    class GuardrailViolationError(Exception):
        pass

    class RefusalError(Exception):
        pass

    class UnsupportedLanguageOrLocaleError(Exception):
        pass

    class SystemLanguageModel:
        context_size = 4096

        def __init__(self, use_case=None, guardrails=None):
            self.use_case = use_case
            self.guardrails = guardrails
            rec["models"].append(self)

        def is_available(self):
            return available

        async def token_count(self, value=None, *, instructions=None):
            rec["token_count_calls"].append(
                {
                    "value": value,
                    "instructions": instructions,
                }
            )
            counts = token_counts or []
            idx = len(rec["token_count_calls"]) - 1
            return counts[idx] if idx < len(counts) else 0

    class _Transcript:
        pass

    class LanguageModelSession:
        def __init__(self, instructions=None, model=None, tools=None):
            self.instructions = instructions
            self.model = model
            self.transcript = _Transcript()
            rec["sessions"].append(self)

        async def stream_response(self, prompt, options=None):
            rec["stream_calls"].append({"prompt": prompt, "options": options})
            if raise_on_stream is not None:
                # Named rather than passed as an instance so callers don't
                # need a stub SDK in hand before installing one.
                raise getattr(sdk, raise_on_stream)("stub failure")
            for snap in snapshots or []:
                yield snap

    sdk.SystemLanguageModelUseCase = SystemLanguageModelUseCase
    sdk.SystemLanguageModelGuardrails = SystemLanguageModelGuardrails
    sdk.SamplingMode = SamplingMode
    sdk.GenerationOptions = GenerationOptions
    sdk.SystemLanguageModel = SystemLanguageModel
    sdk.LanguageModelSession = LanguageModelSession
    sdk.ExceededContextWindowSizeError = ExceededContextWindowSizeError
    sdk.GuardrailViolationError = GuardrailViolationError
    sdk.RefusalError = RefusalError
    sdk.UnsupportedLanguageOrLocaleError = UnsupportedLanguageOrLocaleError

    sys.modules["apple_fm_sdk"] = sdk
    return rec


def _load_engine_module():
    """Import a fresh engine module against whatever stub is installed.

    ``tests/conftest.py`` wipes ``EngineRegistry`` between tests, so the
    module must be re-imported (not just fetched from the registry) for the
    ``@EngineRegistry.register`` decorator to run again.
    """
    sys.modules.pop("openjarvis.engine.apple_fm", None)
    return importlib.import_module("openjarvis.engine.apple_fm")


@pytest.fixture
def engine_mod():
    created = []

    def _make(**stub_kwargs):
        rec = _install_stub_sdk(**stub_kwargs)
        mod = _load_engine_module()
        created.append(mod)
        return mod, rec

    yield _make
    sys.modules.pop("openjarvis.engine.apple_fm", None)
    sys.modules.pop("apple_fm_sdk", None)


def _engine(mod, **kwargs):
    eng = mod.AppleFMEngine(**kwargs)
    eng._prepared = True
    eng._context_size = 4096
    return eng


# ---------------------------------------------------------------------------
# Engine behaviour
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_under_afm(self, engine_mod):
        from openjarvis.core.registry import EngineRegistry

        mod, _ = engine_mod()
        assert EngineRegistry.get("afm") is mod.AppleFMEngine
        assert mod.AppleFMEngine.engine_id == "afm"

    def test_rejects_unknown_use_case(self, engine_mod):
        mod, _ = engine_mod()
        with pytest.raises(ValueError, match="content_tagging"):
            mod.AppleFMEngine(use_case="nonsense")

    def test_rejects_unknown_sampling_at_construction(self, engine_mod):
        """A typo must fail now, not midway through a long run."""
        mod, _ = engine_mod()
        with pytest.raises(ValueError, match="greedy"):
            mod.AppleFMEngine(sampling="beam")


class TestServeability:
    def test_only_serves_afm_labels(self, engine_mod):
        """Unlike other local engines, this one must not accept any model id.

        There is exactly one on-device model, so accepting arbitrary ids would
        let engine selection route a Llama request here and answer with a
        different model entirely.
        """
        mod, _ = engine_mod()
        eng = _engine(mod)
        assert eng.can_serve("afm-3-core") is True
        assert eng.can_serve("llama3.2:3b") is False


class TestHealth:
    def test_reports_unavailable_reason(self, engine_mod, caplog):
        mod, _ = engine_mod(available=(False, types.SimpleNamespace(name="ASSETS")))
        eng = mod.AppleFMEngine()
        with caplog.at_level("WARNING"):
            assert eng.health() is False
        assert "ASSETS" in caplog.text


class TestGenerate:
    def test_returns_content_and_real_token_counts(self, engine_mod):
        # token_count call order: transcript-before, prompt, transcript-after
        mod, rec = engine_mod(
            snapshots=["Paris", "Paris is", "Paris is the capital."],
            token_counts=[12, 8, 27],
        )
        eng = _engine(mod)

        result = eng.generate(
            [Message(role=Role.USER, content="Capital of France?")],
            model="afm-3-core",
            max_tokens=64,
        )
        eng.close()

        assert result["content"] == "Paris is the capital."
        # prompt = transcript-before (12) + prompt alone (8)
        assert result["usage"]["prompt_tokens"] == 20
        # completion = transcript-after (27) - prompt (20)
        assert result["usage"]["completion_tokens"] == 7
        assert result["usage"]["total_tokens"] == 27
        assert result["finish_reason"] == "stop"

    def test_system_message_becomes_session_instructions(self, engine_mod):
        """Not folded into the prompt text.

        The shim historically prefixed system content onto the prompt, which
        both loses the distinction the SDK draws and inflates prompt tokens.
        """
        mod, rec = engine_mod(snapshots=["ok"], token_counts=[1, 1, 2])
        eng = _engine(mod)
        eng.generate(
            [
                Message(role=Role.SYSTEM, content="Be terse."),
                Message(role=Role.USER, content="Hi"),
            ],
            model="afm-3",
        )
        eng.close()

        assert rec["sessions"][-1].instructions == "Be terse."
        assert rec["stream_calls"][-1]["prompt"] == "Hi"

    def test_configured_instructions_precede_request_system_message(self, engine_mod):
        mod, rec = engine_mod(snapshots=["ok"], token_counts=[1, 1, 2])
        eng = _engine(mod, instructions="Always answer in English.")
        eng.generate(
            [
                Message(role=Role.SYSTEM, content="Be terse."),
                Message(role=Role.USER, content="Hi"),
            ],
            model="afm-3",
        )
        eng.close()
        assert (
            rec["sessions"][-1].instructions == "Always answer in English.\nBe terse."
        )

    def test_generation_options_carry_sampling_and_limits(self, engine_mod):
        mod, rec = engine_mod(snapshots=["x"], token_counts=[0, 0, 1])
        eng = _engine(mod, sampling="random")
        eng.generate(
            [Message(role=Role.USER, content="Hi")],
            model="afm-3",
            temperature=0.25,
            max_tokens=99,
        )
        eng.close()

        opts = rec["stream_calls"][-1]["options"]
        assert opts.temperature == 0.25
        assert opts.maximum_response_tokens == 99
        assert opts.sampling == ("random", {})

    def test_each_request_gets_a_fresh_session(self, engine_mod):
        """Reused sessions accumulate a transcript that overflows the 4096-token
        context after a handful of requests, and would make per-request energy
        depend on the requests before it."""
        mod, rec = engine_mod(snapshots=["x"], token_counts=[0, 0, 1] * 3)
        eng = _engine(mod)
        msgs = [Message(role=Role.USER, content="Hi")]
        for _ in range(3):
            eng.generate(msgs, model="afm-3")
        eng.close()

        assert len(rec["sessions"]) == 3
        assert len({id(s) for s in rec["sessions"]}) == 3

    def test_token_count_failure_degrades_to_zero_not_an_error(self, engine_mod):
        mod, _ = engine_mod(snapshots=["hi"])
        eng = _engine(mod)

        async def _boom(*a, **k):
            raise RuntimeError("counter unavailable")

        eng._ensure_model().token_count = _boom

        result = eng.generate([Message(role=Role.USER, content="Hi")], model="afm-3")
        eng.close()
        assert result["content"] == "hi"
        assert result["usage"]["completion_tokens"] == 0


class TestErrorMapping:
    def test_context_overflow_becomes_a_context_length_error(self, engine_mod):
        from openjarvis.engine._base import (
            EngineContextLengthError,
            looks_like_context_length_error,
        )

        mod, _ = engine_mod(raise_on_stream="ExceededContextWindowSizeError")
        eng = _engine(mod)
        with pytest.raises(EngineContextLengthError) as exc:
            eng.generate([Message(role=Role.USER, content="x" * 100)], model="afm-3")
        eng.close()
        # The shared heuristic must recognise the phrasing too, so callers
        # branching on text rather than type still get "conversation too long".
        assert looks_like_context_length_error(str(exc.value))
        # The SDK formats its messages as "<reason>: <detail>" and passes
        # None as the detail, so the raw text ends in ": None". That must not
        # reach the user -- it reads as a broken error path rather than a
        # plain overflow, and it lands in every affected eval row.
        assert not str(exc.value).rstrip().endswith("None")
        assert "4096" in str(exc.value)

    def test_context_error_does_not_repeat_the_sdk_reason(self, engine_mod):
        from openjarvis.engine._base import EngineContextLengthError

        mod, _ = engine_mod(raise_on_stream="ExceededContextWindowSizeError")
        eng = _engine(mod)
        with pytest.raises(EngineContextLengthError) as exc:
            eng.generate([Message(role=Role.USER, content="x")], model="afm-3")
        eng.close()
        # "context window" should appear once, from our own sentence.
        assert str(exc.value).lower().count("context window") == 1

    def test_refusal_returns_empty_instead_of_killing_the_run(self, engine_mod):
        """A declined prompt is a per-query outcome, not an engine fault.

        A long eval run must not die because one prompt tripped a guardrail.
        """
        mod, _ = engine_mod(
            raise_on_stream="GuardrailViolationError",
            token_counts=[3, 5],
        )
        eng = _engine(mod)
        result = eng.generate([Message(role=Role.USER, content="...")], model="afm-3")

        assert result["content"] == ""
        assert result["finish_reason"] == "content_filter"
        assert eng._skipped == {"GuardrailViolationError": 1}
        eng.close()


class TestStreaming:
    def test_stream_yields_deltas_that_reassemble(self, engine_mod):
        mod, _ = engine_mod(
            snapshots=["The", "The cap", "The capital is Paris."],
            token_counts=[4, 6, 20],
        )
        eng = _engine(mod)

        async def _collect():
            return [
                c
                async for c in eng.stream(
                    [Message(role=Role.USER, content="Hi")], model="afm-3"
                )
            ]

        chunks = asyncio.run(_collect())
        eng.close()
        assert "".join(chunks) == "The capital is Paris."

    def test_stream_full_reports_usage_at_end(self, engine_mod):
        mod, _ = engine_mod(snapshots=["ab", "abc"], token_counts=[4, 6, 15])
        eng = _engine(mod)

        async def _collect():
            return [
                c
                async for c in eng.stream_full(
                    [Message(role=Role.USER, content="Hi")], model="afm-3"
                )
            ]

        chunks = asyncio.run(_collect())
        eng.close()
        final = chunks[-1]
        assert final.finish_reason == "stop"
        assert final.usage["prompt_tokens"] == 10
        assert final.usage["completion_tokens"] == 5


class TestPrepare:
    def test_warms_up_and_records_context_size(self, engine_mod):
        """Warmup runs inside prepare() so the ~10s cold start lands outside
        the first request's energy window."""
        mod, rec = engine_mod(snapshots=["w"])
        eng = mod.AppleFMEngine()
        eng.prepare("afm-3-core")
        eng.close()

        assert eng._context_size == 4096
        assert rec["stream_calls"][0]["prompt"] == "warmup"
        assert rec["stream_calls"][0]["options"].maximum_response_tokens == 4

    def test_unavailable_model_raises_connection_error(self, engine_mod):
        from openjarvis.engine._base import EngineConnectionError

        mod, _ = engine_mod(
            available=(False, types.SimpleNamespace(name="APPLE_INTELLIGENCE_OFF"))
        )
        eng = mod.AppleFMEngine()
        with pytest.raises(EngineConnectionError, match="APPLE_INTELLIGENCE_OFF"):
            eng.prepare("afm-3-core")

    def test_bad_label_rejected_before_touching_the_model(self, engine_mod):
        mod, _ = engine_mod()
        eng = mod.AppleFMEngine()
        with pytest.raises(ValueError, match="afm-3-core-advanced"):
            eng.prepare("gpt-4")


class TestDescribe:
    def test_records_what_the_variant_cannot_tell_us(self, engine_mod):
        mod, _ = engine_mod()
        eng = _engine(mod, use_case="content_tagging")
        info = eng.describe()
        eng.close()

        assert info["engine_id"] == "afm"
        assert info["afm_use_case"] == "content_tagging"
        assert info["afm_context_size"] == 4096
        # The executing variant is not observable, so the host chip is how a
        # run gets attributed after the fact.
        assert info["host_chip"]
        assert "dynamic profile" in info["variant_selection"]


# ---------------------------------------------------------------------------
# On-hardware smoke test
# ---------------------------------------------------------------------------


@pytest.mark.apple
@pytest.mark.macos15
class TestOnRealHardware:
    def test_generates_with_real_token_counts(self):
        sys.modules.pop("apple_fm_sdk", None)
        sys.modules.pop("openjarvis.engine.apple_fm", None)
        pytest.importorskip("apple_fm_sdk")
        mod = importlib.import_module("openjarvis.engine.apple_fm")

        eng = mod.AppleFMEngine(instructions="Answer in one word.")
        if not eng.health():
            pytest.skip("Apple Intelligence unavailable on this host")

        result = eng.generate(
            [Message(role=Role.USER, content="Name one planet.")],
            model="afm-3-core",
            max_tokens=16,
        )
        eng.close()

        assert result["content"].strip()
        # The whole point of the 0.2.1 SDK floor: the shim reported 0 here,
        # which zeroed throughput and every per-token energy figure.
        assert result["usage"]["completion_tokens"] > 0
        assert result["usage"]["prompt_tokens"] > 0


class TestAfmIsTreatedAsLocal:
    """`afm` must be recognised as an on-device engine everywhere it matters.

    The Python SDK has no Private Cloud Compute path, so AFM inference never
    leaves the machine. An engine key missing from these sets produces a false
    "your data is leaving this machine" signal.
    """

    def test_data_boundary_audit_classifies_afm_as_local(self):
        from openjarvis.security.data_boundary_audit import (
            LOCAL_ENGINE_KEYS,
            _target_is_cloud,
        )

        assert "afm" in LOCAL_ENGINE_KEYS
        assert _target_is_cloud("afm", "afm-3-core") is False

    def test_image_privacy_guard_does_not_warn_for_afm(self):
        """`jarvis ask -i photo.png --engine afm` must not claim the image
        leaves the machine."""
        from openjarvis.cli.ask import LOCAL_ENGINES

        assert "afm" in LOCAL_ENGINES
        assert "openai" not in LOCAL_ENGINES
