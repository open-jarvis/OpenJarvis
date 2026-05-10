"""Tests for direct cloud/local server routing helpers."""

from __future__ import annotations

from openjarvis.server.cloud_router import _ollama_host


def test_ollama_host_defaults_when_env_is_empty(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "")
    assert _ollama_host() == "http://localhost:11434"


def test_ollama_host_adds_scheme_for_bare_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "localhost:11434")
    assert _ollama_host() == "http://localhost:11434"


def test_ollama_host_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434/")
    assert _ollama_host() == "http://127.0.0.1:11434"
