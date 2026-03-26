"""Tests for context injection integration in ``jarvis ask``."""

from __future__ import annotations

import importlib

from click.testing import CliRunner

from openjarvis.cli import cli


def test_ask_no_context_flag():
    """The --no-context flag is accepted."""
    result = CliRunner().invoke(cli, ["ask", "--no-context", "--help"])
    # --help should succeed regardless
    assert result.exit_code == 0


def test_ask_has_no_context_option():
    """ask --help lists the --no-context flag."""
    result = CliRunner().invoke(cli, ["ask", "--help"])
    assert result.exit_code == 0
    assert "--no-context" in result.output


def test_get_memory_backend_returns_none_when_empty(
    tmp_path,
    monkeypatch,
):
    """_get_memory_backend returns None when no docs indexed."""
    from openjarvis.core.config import JarvisConfig, MemoryConfig
    from openjarvis.core.registry import MemoryRegistry
    from openjarvis.tools.storage.sqlite import SQLiteMemory

    if not MemoryRegistry.contains("sqlite"):
        MemoryRegistry.register_value("sqlite", SQLiteMemory)

    config = JarvisConfig()
    config.memory = MemoryConfig(
        db_path=str(tmp_path / "empty.db"),
    )

    mod = importlib.import_module("openjarvis.cli.ask")
    result = mod._get_memory_backend(config)
    assert result is None


def test_get_memory_backend_returns_backend_with_docs(
    tmp_path,
    monkeypatch,
):
    """_get_memory_backend returns a backend when docs exist."""
    from openjarvis.core.config import JarvisConfig, MemoryConfig
    from openjarvis.core.registry import MemoryRegistry
    from openjarvis.tools.storage.sqlite import SQLiteMemory

    if not MemoryRegistry.contains("sqlite"):
        MemoryRegistry.register_value("sqlite", SQLiteMemory)

    db_path = str(tmp_path / "test.db")
    config = JarvisConfig()
    config.memory = MemoryConfig(db_path=db_path)

    # Pre-populate with a document
    backend = SQLiteMemory(db_path=db_path)
    backend.store("test document content")
    backend.close()

    mod = importlib.import_module("openjarvis.cli.ask")
    result = mod._get_memory_backend(config)
    assert result is not None
    if hasattr(result, "close"):
        result.close()
