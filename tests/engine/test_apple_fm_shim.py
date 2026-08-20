"""Tests for the Apple FM shim.

The real ``apple-fm-sdk`` is not on PyPI and only runs on macOS 26+ with
Apple Intelligence, so these tests inject a stub SDK into ``sys.modules``
before importing the shim. They verify the shim's OpenAI-compat wiring
against the stub's recorded calls — they do NOT exercise Apple's real SDK.
"""

from __future__ import annotations

import importlib
import platform
import sys
import types
from typing import Any

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


def _install_stub_sdk(
    *,
    available: tuple[bool, Any] = (True, None),
    stream_tokens: list[str] | None = None,
    respond_text: str = "Hello from Apple FM.",
) -> dict[str, Any]:
    """Inject a fake ``apple_fm_sdk`` module and return a recorder dict.

    The recorder captures the GenerationOptions the shim builds and the
    args passed to ``stream_response`` / ``respond`` so tests can assert
    the shim wires ``options=`` through (PR #377) rather than the old
    ``max_tokens=`` positional kwarg.
    """
    rec: dict[str, Any] = {"options": [], "stream_calls": [], "respond_calls": []}
    sdk = types.ModuleType("apple_fm_sdk")

    class GenerationOptions:
        def __init__(self, temperature: float = 1.0, maximum_response_tokens: int = 0):
            self.temperature = temperature
            self.maximum_response_tokens = maximum_response_tokens
            rec["options"].append(self)

    class SystemLanguageModel:
        def is_available(self):  # instance method returning (bool, reason)
            return available

    class LanguageModelSession:
        async def stream_response(self, prompt: str, *, options: Any = None):
            rec["stream_calls"].append({"prompt": prompt, "options": options})
            for tok in stream_tokens or []:
                yield tok

        async def respond(self, prompt: str, *, options: Any = None) -> str:
            rec["respond_calls"].append({"prompt": prompt, "options": options})
            return respond_text

    sdk.GenerationOptions = GenerationOptions  # type: ignore[attr-defined]
    sdk.SystemLanguageModel = SystemLanguageModel  # type: ignore[attr-defined]
    sdk.LanguageModelSession = LanguageModelSession  # type: ignore[attr-defined]

    sys.modules["apple_fm_sdk"] = sdk
    return rec


@pytest.fixture
def shim(monkeypatch):
    """Import a fresh copy of the shim against the stub SDK on any platform."""
    # The module bails with sys.exit unless it sees Darwin + the SDK import.
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    rec = _install_stub_sdk(stream_tokens=["Sure! ", "Sure! The ", "Sure! The answer."])
    sys.modules.pop("openjarvis.engine.apple_fm_shim", None)
    mod = importlib.import_module("openjarvis.engine.apple_fm_shim")
    mod = importlib.reload(mod)
    yield mod, rec
    sys.modules.pop("openjarvis.engine.apple_fm_shim", None)
    sys.modules.pop("apple_fm_sdk", None)


class TestAppleFmShimSdkMigration:
    def test_options_carry_temperature_and_max_tokens(self, shim):
        mod, rec = shim
        client = TestClient(mod.app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 0.3,
                "max_tokens": 42,
                "stream": False,
            },
        )
        assert resp.status_code == 200
        # The shim must build a GenerationOptions and pass it as options=.
        assert rec["options"], "shim never constructed GenerationOptions"
        opt = rec["options"][-1]
        assert opt.temperature == 0.3
        assert opt.maximum_response_tokens == 42
        assert rec["respond_calls"][-1]["options"] is opt
        assert resp.json()["choices"][0]["message"]["content"] == "Hello from Apple FM."

    def test_stream_passes_options_not_max_tokens(self, shim):
        mod, rec = shim
        client = TestClient(mod.app)
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "stream": True,
            },
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        assert rec["stream_calls"], "stream_response was never called"
        # options object passed through; not the legacy max_tokens kwarg.
        assert rec["stream_calls"][-1]["options"] is rec["options"][-1]
        assert "data: [DONE]" in body

    def test_stream_emits_incremental_deltas_from_cumulative_snapshots(self, shim):
        """Regression for #378.

        Apple FM's stream_response yields CUMULATIVE text snapshots, but
        OpenAI clients concatenate delta.content. The shim must emit the
        incremental suffix per chunk, so concatenating the deltas
        reconstructs the final snapshot exactly — with no duplicated or
        dropped characters.
        """
        import json as _json

        mod, rec = shim  # fixture streams ["Sure! ", "Sure! The ", "Sure! The answer."]
        client = TestClient(mod.app)
        with client.stream(
            "POST",
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "hi"}], "stream": True},
        ) as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())

        # Collect content deltas from the SSE chunks.
        deltas: list[str] = []
        for line in body.splitlines():
            if not line.startswith("data:") or "[DONE]" in line:
                continue
            payload = _json.loads(line[len("data:") :].strip())
            content = payload["choices"][0]["delta"].get("content")
            if content:
                deltas.append(content)

        # Incremental, not cumulative: concatenation equals the final
        # snapshot, and no single delta repeats the whole prefix.
        assert "".join(deltas) == "Sure! The answer."
        assert deltas == ["Sure! ", "The ", "answer."]

    def test_health_unpacks_is_available_tuple(self, monkeypatch):
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        rec = _install_stub_sdk(available=(False, "Apple Intelligence disabled"))
        sys.modules.pop("openjarvis.engine.apple_fm_shim", None)
        mod = importlib.import_module("openjarvis.engine.apple_fm_shim")
        mod = importlib.reload(mod)
        try:
            client = TestClient(mod.app)
            resp = client.get("/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "unavailable"
            assert data["reason"] == "Apple Intelligence disabled"
        finally:
            sys.modules.pop("openjarvis.engine.apple_fm_shim", None)
            sys.modules.pop("apple_fm_sdk", None)
        _ = rec
