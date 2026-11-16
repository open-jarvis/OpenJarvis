"""Optional import failures must be logged by actual package initialization."""

from __future__ import annotations

import importlib
import importlib.util
import logging

import pytest


@pytest.mark.parametrize(
    "package_name,target,message",
    [
        (
            "openjarvis.tools",
            "openjarvis.tools.calculator",
            "Optional tool calculator not loaded",
        ),
        (
            "openjarvis.tools.storage",
            "openjarvis.tools.storage.faiss_backend",
            "Optional storage backend faiss_backend not loaded",
        ),
        (
            "openjarvis.speech",
            "openjarvis.speech.faster_whisper",
            "Optional STT backend faster_whisper not loaded",
        ),
        (
            "openjarvis.speech",
            "openjarvis.speech.cartesia_tts",
            "Optional TTS backend cartesia_tts not loaded",
        ),
    ],
)
def test_package_initialization_logs_optional_import_failure(
    package_name, target, message, monkeypatch, caplog
):
    package = importlib.import_module(package_name)
    original_import = importlib.import_module
    attempted = []

    def controlled_import(name, package=None):
        resolved = (
            importlib.util.resolve_name(name, package) if name.startswith(".") else name
        )
        attempted.append(resolved)
        if resolved == target:
            raise ImportError("simulated optional dependency failure")
        return original_import(name, package)

    monkeypatch.setattr(importlib, "import_module", controlled_import)
    with caplog.at_level(logging.DEBUG, logger=package_name):
        importlib.reload(package)

    assert target in attempted
    assert any(
        message in record.getMessage()
        and "simulated optional dependency failure" in record.getMessage()
        for record in caplog.records
    )
    assert attempted.index(target) < len(attempted) - 1


def test_optional_loader_does_not_swallow_programming_errors(monkeypatch):
    import openjarvis.tools as package

    original_import = importlib.import_module

    def broken_import(name, package=None):
        if name == "openjarvis.tools.calculator":
            raise RuntimeError("programming error")
        return original_import(name, package)

    monkeypatch.setattr(importlib, "import_module", broken_import)
    with pytest.raises(RuntimeError, match="programming error"):
        importlib.reload(package)
