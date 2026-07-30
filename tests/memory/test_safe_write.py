"""Atomic and Windows-safe Markdown write tests in a temporary vault."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openjarvis.memory.safe_write import (
    AtomicMarkdownWriter,
    ConcurrentMemoryWrite,
    UnsafeMemoryPath,
    safe_target,
    sha256_bytes,
)


@pytest.fixture()
def writer(tmp_path: Path) -> tuple[Path, AtomicMarkdownWriter]:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault, AtomicMarkdownWriter(vault, tmp_path / "restore")


def test_atomic_create_has_verified_hash_diff_and_restore(writer) -> None:
    vault, atomic = writer
    content = "# New memory\n\nSynthetic fact.\n"

    result = atomic.write(
        "captures/new.md",
        content,
        expected_hash=None,
        operation_id="create-operation",
    )

    target = vault / "captures" / "new.md"
    assert target.read_text(encoding="utf-8") == content
    assert result.after_hash == sha256_bytes(content.encode("utf-8"))
    assert result.created_file is True
    assert "--- a/captures/new.md" in result.diff
    assert Path(result.restore_path).is_file()
    assert not list(target.parent.glob("*.tmp"))

    restored_hash = atomic.restore(result)
    assert restored_hash is None
    assert not target.exists()


def test_atomic_update_restores_exact_prior_bytes(writer) -> None:
    vault, atomic = writer
    target = vault / "facts.md"
    before = "# Facts\r\n\r\nBefore\r\n".encode()
    target.write_bytes(before)
    before_hash = sha256_bytes(before)

    result = atomic.write(
        "facts.md",
        "# Facts\n\nAfter\n",
        expected_hash=before_hash,
        operation_id="update-operation",
    )
    restored_hash = atomic.restore(result)

    assert restored_hash == before_hash
    assert target.read_bytes() == before


def test_concurrent_external_change_stops_without_overwrite(writer) -> None:
    vault, atomic = writer
    target = vault / "fact.md"
    target.write_text("before\n", encoding="utf-8")
    _target, _before, expected_hash = atomic.inspect("fact.md")
    target.write_text("external change\n", encoding="utf-8")

    with pytest.raises(ConcurrentMemoryWrite, match="changed"):
        atomic.write("fact.md", "jarvis change\n", expected_hash=expected_hash)

    assert target.read_text(encoding="utf-8") == "external change\n"


def test_file_created_after_candidate_stops_without_overwrite(writer) -> None:
    vault, atomic = writer
    target = vault / "new.md"
    _target, before, expected_hash = atomic.inspect("new.md")
    assert before is None
    assert expected_hash is None
    target.write_text("external create\n", encoding="utf-8")

    with pytest.raises(ConcurrentMemoryWrite, match="created"):
        atomic.write("new.md", "candidate\n", expected_hash=None)

    assert target.read_text(encoding="utf-8") == "external create\n"


@pytest.mark.parametrize(
    "path",
    [
        "../escape.md",
        "folder/../../escape.md",
        "C:\\Windows\\escape.md",
        "\\\\server\\share\\escape.md",
        "/absolute/escape.md",
        "not-markdown.txt",
    ],
)
def test_path_escape_and_non_markdown_are_blocked(
    writer,
    path: str,
) -> None:
    vault, _atomic = writer

    with pytest.raises(UnsafeMemoryPath):
        safe_target(vault, path)


def test_restore_root_cannot_live_inside_vault(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ValueError, match="outside"):
        AtomicMarkdownWriter(vault, vault / ".restore")


def test_restore_stops_if_written_file_changed_again(writer) -> None:
    vault, atomic = writer
    target = vault / "fact.md"
    target.write_text("before\n", encoding="utf-8")
    expected = sha256_bytes(target.read_bytes())
    result = atomic.write("fact.md", "after\n", expected_hash=expected)
    target.write_text("changed after write\n", encoding="utf-8")

    with pytest.raises(ConcurrentMemoryWrite, match="changed"):
        atomic.restore(result)

    assert target.read_text(encoding="utf-8") == "changed after write\n"


def test_symlink_or_junction_path_is_blocked(writer, tmp_path: Path) -> None:
    vault, atomic = writer
    outside = tmp_path / "outside"
    outside.mkdir()
    link = vault / "linked"
    try:
        if os.name == "nt":
            os.symlink(outside, link, target_is_directory=True)
        else:
            link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable for this test account")

    with pytest.raises(UnsafeMemoryPath, match="symlink|junction"):
        atomic.write("linked/note.md", "blocked\n", expected_hash=None)
    assert not (outside / "note.md").exists()
