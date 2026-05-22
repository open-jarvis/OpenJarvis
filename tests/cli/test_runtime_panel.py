"""Tests for CLI runtime panel (context / GPU offload)."""

from __future__ import annotations

from openjarvis.cli._runtime_panel import (
    MAX_NUM_CTX,
    ChatRuntimeOptions,
    _parse_int,
)


def test_parse_int_underscores() -> None:
    assert _parse_int("32_768", default=None) == 32768


def test_chat_runtime_options_engine_kwargs() -> None:
    opts = ChatRuntimeOptions(num_ctx=65536, num_gpu=-1)
    kw = opts.to_engine_kwargs()
    assert kw["num_ctx"] == 65536
    assert kw["num_gpu"] == 999


def test_runtime_summary_ollama() -> None:
    opts = ChatRuntimeOptions(num_ctx=150_000, num_gpu=0)
    s = opts.summary(engine_name="ollama")
    assert "ctx=150,000" in s
    assert "gpu=0 (CPU)" in s


def test_max_num_ctx_constant() -> None:
    assert MAX_NUM_CTX == 200_000
