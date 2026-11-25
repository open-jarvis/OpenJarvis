"""Tests for the read-only file_list tool."""

from __future__ import annotations

from openjarvis.tools.file_list import FileListTool


def test_lists_directory_entries_without_sensitive_names(tmp_path):
    (tmp_path / "folder").mkdir()
    (tmp_path / "notes.txt").write_text("private content")
    (tmp_path / ".env").write_text("SECRET=value")

    result = FileListTool().execute(path=str(tmp_path))

    assert result.success
    assert "[directory] folder" in result.content
    assert "[file] notes.txt" in result.content
    assert ".env" not in result.content
    assert "private content" not in result.content
    assert result.metadata["total"] == 2


def test_allowed_dirs_and_relative_paths(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "notes.txt").write_text("notes")
    outside = tmp_path / "outside"
    outside.mkdir()

    tool = FileListTool(allowed_dirs=[str(allowed)])

    assert "notes.txt" in tool.execute(path=".").content
    denied = tool.execute(path=str(outside))
    assert not denied.success
    assert "outside allowed directories" in denied.content


def test_entry_limit_is_bounded_and_reports_truncation(tmp_path):
    for index in range(4):
        (tmp_path / f"{index}.txt").write_text("")

    result = FileListTool().execute(path=str(tmp_path), max_entries=2)

    assert result.success
    assert result.metadata["count"] == 2
    assert result.metadata["total"] == 4
    assert result.metadata["truncated"]
    assert "... and 2 more entries." in result.content


def test_rejects_file_and_invalid_entry_limit(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("notes")
    tool = FileListTool()

    assert not tool.execute(path=str(file_path)).success
    assert not tool.execute(path=str(tmp_path), max_entries=True).success
