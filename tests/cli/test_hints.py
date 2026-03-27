"""Tests for CLI error hint functions."""

from __future__ import annotations

from openjarvis.cli.hints import (
    hint_no_config,
    hint_no_engine,
    hint_no_model,
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
