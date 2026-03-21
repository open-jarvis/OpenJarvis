"""Tests for ``jarvis memory`` CLI commands."""

from __future__ import annotations

import importlib
from pathlib import Path

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage.sqlite import SQLiteMemory


def _register_sqlite():
    """Re-register sqlite backend (conftest clears registries)."""
    if not MemoryRegistry.contains("sqlite"):
        MemoryRegistry.register_value("sqlite", SQLiteMemory)


def test_memory_index_file(tmp_path: Path, monkeypatch):
    """Index a single text file and check success message."""
    _register_sqlite()
    db_path = str(tmp_path / "mem.db")

    # Create a text file with enough content
    doc = tmp_path / "doc.txt"
    doc.write_text(" ".join(f"word{i}" for i in range(100)))

    mod = importlib.import_module("openjarvis.cli.memory_cmd")
    monkeypatch.setattr(
        mod,
        "_get_backend",
        lambda b=None: SQLiteMemory(db_path=db_path),
    )

    result = CliRunner().invoke(cli, ["memory", "index", str(doc)])
    assert result.exit_code == 0
    assert "Indexed" in result.output or "chunk" in result.output


def test_memory_index_nonexistent(tmp_path: Path):
    """Indexing a nonexistent path should fail."""
    _register_sqlite()
    result = CliRunner().invoke(cli, ["memory", "index", str(tmp_path / "nope")])
    assert result.exit_code != 0


def test_memory_search_returns_results(tmp_path: Path, monkeypatch):
    """Search returns results from pre-populated backend."""
    _register_sqlite()
    db_path = str(tmp_path / "mem.db")
    backend = SQLiteMemory(db_path=db_path)
    backend.store(
        "Python programming language guide",
        source="guide.md",
    )

    mod = importlib.import_module("openjarvis.cli.memory_cmd")
    monkeypatch.setattr(
        mod,
        "_get_backend",
        lambda b=None: SQLiteMemory(db_path=db_path),
    )

    result = CliRunner().invoke(cli, ["memory", "search", "Python"])
    assert result.exit_code == 0
    assert "Python" in result.output
    backend.close()


def test_memory_search_no_results(tmp_path: Path, monkeypatch):
    """Search with no matches shows appropriate message."""
    _register_sqlite()
    db_path = str(tmp_path / "mem.db")
    backend = SQLiteMemory(db_path=db_path)
    backend.store("some unrelated content about cats")

    mod = importlib.import_module("openjarvis.cli.memory_cmd")
    monkeypatch.setattr(
        mod,
        "_get_backend",
        lambda b=None: SQLiteMemory(db_path=db_path),
    )

    result = CliRunner().invoke(cli, ["memory", "search", "quantum supercollider"])
    assert result.exit_code == 0
    assert "No results" in result.output
    backend.close()


def test_memory_stats_shows_count(tmp_path: Path, monkeypatch):
    """Stats command shows document count."""
    _register_sqlite()
    db_path = str(tmp_path / "mem.db")
    backend = SQLiteMemory(db_path=db_path)
    backend.store("doc one")
    backend.store("doc two")

    mod = importlib.import_module("openjarvis.cli.memory_cmd")
    monkeypatch.setattr(
        mod,
        "_get_backend",
        lambda b=None: SQLiteMemory(db_path=db_path),
    )

    result = CliRunner().invoke(cli, ["memory", "stats"])
    assert result.exit_code == 0
    assert "2" in result.output
    backend.close()
