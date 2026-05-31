"""Tests for Ollama runtime option wiring (num_ctx / num_gpu)."""

from __future__ import annotations

from openjarvis.engine.ollama import _ollama_request_options


def test_with_explicit_runtime_kwargs() -> None:
    opts = _ollama_request_options(
        temperature=0.5,
        max_tokens=512,
        kwargs={"num_ctx": 64000, "num_gpu": 12},
    )
    assert opts["num_ctx"] == 64000
    assert opts["num_gpu"] == 12


def test_default_num_ctx_when_omitted() -> None:
    opts = _ollama_request_options(
        temperature=0.7,
        max_tokens=1024,
        kwargs={},
    )
    assert opts["num_ctx"] == 8192
    assert "num_gpu" not in opts
