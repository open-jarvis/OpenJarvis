"""Tests for CLI error hint functions."""

from __future__ import annotations

from openjarvis.cli.hints import (
    hint_no_config,
    hint_no_engine,
    hint_no_model,
    mining_not_running_hint,
)


class TestHintFunctions:
    def test_hint_no_config_returns_string(self):
        msg = hint_no_config()
        assert isinstance(msg, str)
        assert len(msg) > 0
        assert "init" in msg.lower() or "config" in msg.lower()

    def test_hint_no_engine_returns_string(self):
        msg = hint_no_engine()
        assert isinstance(msg, str)
        assert len(msg) > 0
        assert "engine" in msg.lower() or "ollama" in msg.lower()

    def test_hint_no_engine_with_name(self):
        msg = hint_no_engine("vllm")
        assert "vllm" in msg.lower()

    def test_hint_no_model_returns_string(self):
        msg = hint_no_model()
        assert isinstance(msg, str)
        assert len(msg) > 0
        assert "model" in msg.lower() or "pull" in msg.lower()

    def test_hint_no_model_with_name(self):
        msg = hint_no_model("qwen3:8b")
        assert "qwen3:8b" in msg

    def test_hint_no_engine_includes_remote_tip(self):
        msg = hint_no_engine()
        assert "config set" in msg
        assert "OLLAMA_HOST" in msg

    def test_hint_no_engine_with_name_includes_remote_tip(self):
        msg = hint_no_engine("vllm")
        assert "config set" in msg
        assert "engine.vllm.host" in msg

    def test_mining_not_running_hint_when_configured_no_sidecar(self):
        msg = mining_not_running_hint(object(), sidecar_present=False)
        assert msg is not None
        assert "jarvis mine start" in msg

    def test_mining_not_running_hint_silent_when_running(self):
        assert mining_not_running_hint(object(), sidecar_present=True) is None

    def test_mining_not_running_hint_silent_when_unconfigured(self):
        assert mining_not_running_hint(None, sidecar_present=False) is None
