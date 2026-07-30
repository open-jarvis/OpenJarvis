"""Windows-safe Phase-5 filesystem tool tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from openjarvis.tools.safe_filesystem import (
    FilesystemPolicyError,
    SafeDirectoryCreateTool,
    SafeFileCopyTool,
    SafeFileDeleteTool,
    SafeFileListTool,
    SafeFileMoveTool,
    SafeFilePatchTool,
    SafeFileReadTool,
    SafeFileSearchTool,
    SafeFileStatTool,
    SafeFileWriteTool,
    SecurePathPolicy,
)


@pytest.fixture
def roots(tmp_path: Path):
    workspace = tmp_path / "workspace"
    restore = tmp_path / "restore"
    workspace.mkdir()
    return workspace, restore, SecurePathPolicy((workspace,), restore)


def test_root_escape_and_parent_traversal_blocked(roots) -> None:
    workspace, _, policy = roots
    with pytest.raises(FilesystemPolicyError, match="parent traversal"):
        policy.resolve("../outside.txt")
    with pytest.raises(FilesystemPolicyError, match="outside allowed roots"):
        policy.resolve(str(workspace.parent / "outside.txt"))


def test_windows_path_comparison_is_case_insensitive(roots) -> None:
    workspace, _, policy = roots
    child = workspace / "Case.txt"
    child.write_text("safe", encoding="utf-8")
    if os.name == "nt":
        alternate_case = str(child).swapcase()
        assert policy.resolve(alternate_case, must_exist=True) == child.resolve()


@pytest.mark.parametrize("name", ["note.txt:secret", "folder:stream/file.txt"])
def test_alternate_data_stream_blocked(roots, name: str) -> None:
    _, _, policy = roots
    with pytest.raises(FilesystemPolicyError, match="alternate data streams"):
        policy.resolve(name)


def test_symlink_or_junction_is_blocked(roots) -> None:
    workspace, _, policy = roots
    outside = workspace.parent / "outside"
    outside.mkdir()
    link = workspace / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Windows account cannot create symlinks")
    with pytest.raises(FilesystemPolicyError, match="reparse point blocked"):
        policy.resolve(str(link / "secret.txt"))


@pytest.mark.skipif(os.name != "nt", reason="Windows junction test")
def test_windows_junction_reparse_point_is_blocked(roots) -> None:
    workspace, _, policy = roots
    outside = workspace.parent / "junction-target"
    outside.mkdir()
    junction = workspace / "junction"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"junction creation unavailable: {result.stderr}")
    with pytest.raises(FilesystemPolicyError, match="reparse point blocked"):
        policy.resolve(str(junction / "secret.txt"))


def test_atomic_write_hash_diff_and_restore(roots) -> None:
    workspace, _, policy = roots
    path = workspace / "note.txt"
    path.write_text("before\n", encoding="utf-8")
    result = SafeFileWriteTool(policy).execute(path=str(path), content="after\n")
    assert result.success is True
    assert result.metadata["before_sha256"]
    assert result.metadata["after_sha256"]
    assert "-before" in result.metadata["diff"]
    policy.restore(result.metadata["restore_path"])
    assert path.read_text(encoding="utf-8") == "before\n"
    assert not list(workspace.glob(".openjarvis-*"))


@pytest.mark.skipif(os.name != "nt", reason="Windows locked-file test")
def test_locked_file_fails_without_partial_write(roots) -> None:
    import msvcrt

    workspace, _, policy = roots
    path = workspace / "locked.txt"
    path.write_text("original", encoding="utf-8")
    with path.open("r+b") as handle:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        result = SafeFileWriteTool(policy).execute(
            path=str(path), content="replacement"
        )
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    assert result.success is False
    assert path.read_text(encoding="utf-8") == "original"
    assert not list(workspace.glob(".openjarvis-*"))


def test_patch_copy_move_and_read_verification(roots) -> None:
    workspace, _, policy = roots
    source = workspace / "source.txt"
    source.write_text("alpha\n", encoding="utf-8")
    patch = "--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-alpha\n+beta\n"
    patched = SafeFilePatchTool(policy).execute(path=str(source), patch=patch)
    assert patched.success
    copied_path = workspace / "copy.txt"
    copied = SafeFileCopyTool(policy).execute(
        source=str(source), target=str(copied_path)
    )
    assert copied.success
    moved_path = workspace / "moved.txt"
    moved = SafeFileMoveTool(policy).execute(
        source=str(copied_path), target=str(moved_path)
    )
    assert moved.success
    read = SafeFileReadTool(policy).execute(path=str(moved_path))
    assert read.content == "beta\n"
    assert read.metadata["sha256"] == copied.metadata["after_sha256"]


def test_delete_moves_to_quarantine_and_restore_works(roots) -> None:
    workspace, _, policy = roots
    target = workspace / "delete-me.txt"
    target.write_text("recoverable", encoding="utf-8")
    result = SafeFileDeleteTool(policy).execute(path=str(target))
    assert result.success
    assert not target.exists()
    assert Path(result.metadata["quarantine_path"]).exists()
    policy.restore(result.metadata["restore_path"])
    assert target.read_text(encoding="utf-8") == "recoverable"


def test_list_stat_search_and_directory_create(roots) -> None:
    workspace, _, policy = roots
    created = SafeDirectoryCreateTool(policy).execute(path="notes")
    assert created.success
    note = workspace / "notes" / "one.txt"
    note.write_text("Cobalt marker", encoding="utf-8")
    listed = SafeFileListTool(policy).execute(path="notes")
    searched = SafeFileSearchTool(policy).execute(path="notes", query="cobalt")
    stated = SafeFileStatTool(policy).execute(path=str(note))
    assert "one.txt" in listed.content
    assert "one.txt:1:Cobalt marker" in searched.content
    assert stated.metadata["sha256"]


def test_unknown_parameter_is_rejected_by_central_executor(roots) -> None:
    from openjarvis.core.types import ToolCall
    from openjarvis.tools._stubs import ToolExecutor

    _, _, policy = roots
    result = ToolExecutor([SafeFileReadTool(policy)]).execute(
        ToolCall(
            id="call-1",
            name="file.read",
            arguments='{"path":"x.txt","approval":true}',
        )
    )
    assert result.success is False
    assert "unknown parameters" in result.content
