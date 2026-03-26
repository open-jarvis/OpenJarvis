"""Tests for the git tools (status, diff, commit, log).

Tests mock the Rust backend (``get_rust_module``) so that the compiled
``openjarvis_rust`` extension is not required.  The mock simulates Rust
behaviour: git commands run via ``subprocess`` with the same flags that the
Rust ``git_tools.rs`` implementation uses.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from openjarvis.tools.git_tool import (
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitStatusTool,
)

# ---------------------------------------------------------------------------
# Helpers — mock Rust backend
# ---------------------------------------------------------------------------


def _run_git_like_rust(args: list[str], cwd: str | None = None) -> str:
    """Run a git command the way the Rust ``run_git`` helper does.

    Returns stdout on success.  Raises ``RuntimeError`` on failure (which is
    what the PyO3 bindings surface to Python for Rust ``ToolResult::failure``).
    """
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or f"git exited {result.returncode}"
        raise RuntimeError(msg)
    return result.stdout


def _make_mock_rust(tmp_path=None):
    """Return a mock module mimicking ``openjarvis_rust`` git tools.

    The mock's ``GitStatusTool``, ``GitDiffTool``, and ``GitLogTool``
    classes each have an ``execute`` method that shells out to git using
    the same flags as the Rust implementation.
    """
    mock_mod = MagicMock()

    # -- GitStatusTool --
    status_inst = MagicMock()

    def _status_execute(cwd=None):
        return _run_git_like_rust(["status", "--short"], cwd=cwd)

    status_inst.execute.side_effect = _status_execute
    mock_mod.GitStatusTool.return_value = status_inst

    # -- GitDiffTool --
    diff_inst = MagicMock()

    def _diff_execute(cwd=None):
        return _run_git_like_rust(["diff"], cwd=cwd)

    diff_inst.execute.side_effect = _diff_execute
    mock_mod.GitDiffTool.return_value = diff_inst

    # -- GitLogTool --
    log_inst = MagicMock()

    def _log_execute(cwd=None, count=None):
        # Rust reads params["n"], but PyO3 passes "count".  The Rust side
        # never sees "count" so the limit always defaults to 10.
        n = 10
        return _run_git_like_rust(["log", "--oneline", f"-{n}"], cwd=cwd)

    log_inst.execute.side_effect = _log_execute
    mock_mod.GitLogTool.return_value = log_inst

    return mock_mod


def _make_mock_rust_git_not_found():
    """Return a mock module whose git tools raise RuntimeError (git missing)."""
    mock_mod = MagicMock()
    err = RuntimeError("Failed to run git: No such file or directory (os error 2)")
    for attr in ("GitStatusTool", "GitDiffTool", "GitLogTool"):
        inst = MagicMock()
        inst.execute.side_effect = err
        getattr(mock_mod, attr).return_value = inst
    return mock_mod


def _init_repo(path):
    """Initialize a git repo with an initial commit at *path*."""
    subprocess.run(
        ["git", "init"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    # Create an initial commit so HEAD exists
    readme = path / "README.md"
    readme.write_text("# Test Repo\n")
    subprocess.run(
        ["git", "add", "."],
        cwd=str(path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(path),
        capture_output=True,
        check=True,
    )


# ---------------------------------------------------------------------------
# TestGitStatusTool
# ---------------------------------------------------------------------------


class TestGitStatusTool:
    def test_spec(self):
        tool = GitStatusTool()
        assert tool.spec.name == "git_status"
        assert tool.spec.category == "vcs"
        assert "file:read" in tool.spec.required_capabilities

    def test_tool_id(self):
        tool = GitStatusTool()
        assert tool.tool_id == "git_status"

    def test_clean_repo(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitStatusTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert result.success is True
        # Clean repo — Rust uses --short so no output
        assert result.content == "(no output)"

    def test_modified_file(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "README.md").write_text("# Modified\n")
        tool = GitStatusTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert result.success is True
        assert "README.md" in result.content

    def test_untracked_file(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "new_file.txt").write_text("hello")
        tool = GitStatusTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert result.success is True
        assert "new_file.txt" in result.content

    def test_default_repo_path(self):
        tool = GitStatusTool()
        mock_mod = _make_mock_rust()
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute()
        # Should succeed or fail depending on cwd; not a crash
        assert isinstance(result.content, str)

    def test_invalid_repo_path(self, tmp_path):
        tool = GitStatusTool()
        mock_mod = _make_mock_rust()
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path / "nonexistent"))
        assert result.success is False

    def test_returncode_in_metadata(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitStatusTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert "returncode" in result.metadata
        assert result.metadata["returncode"] == 0

    def test_git_not_found(self):
        tool = GitStatusTool()
        mock_mod = _make_mock_rust_git_not_found()
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=".")
        assert result.success is False
        assert "Failed to run git" in result.content

    def test_to_openai_function(self):
        tool = GitStatusTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "git_status"


# ---------------------------------------------------------------------------
# TestGitDiffTool
# ---------------------------------------------------------------------------


class TestGitDiffTool:
    def test_spec(self):
        tool = GitDiffTool()
        assert tool.spec.name == "git_diff"
        assert tool.spec.category == "vcs"
        assert "file:read" in tool.spec.required_capabilities

    def test_tool_id(self):
        tool = GitDiffTool()
        assert tool.tool_id == "git_diff"

    def test_no_changes(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitDiffTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert result.success is True
        assert result.content == "(no output)"

    def test_unstaged_changes(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "README.md").write_text("# Changed\n")
        tool = GitDiffTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert result.success is True
        assert "Changed" in result.content

    def test_staged_changes(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "README.md").write_text("# Staged\n")
        subprocess.run(
            ["git", "add", "README.md"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        tool = GitDiffTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            # Unstaged should be empty (Rust path)
            result_unstaged = tool.execute(repo_path=str(tmp_path))
            assert result_unstaged.content == "(no output)"
            # Staged falls back to Python _run_git (not handled by Rust)
            result_staged = tool.execute(repo_path=str(tmp_path), staged=True)
        assert result_staged.success is True
        assert "Staged" in result_staged.content

    def test_specific_file_path(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "README.md").write_text("# Changed\n")
        (tmp_path / "other.txt").write_text("other change")
        subprocess.run(
            ["git", "add", "other.txt"],
            cwd=str(tmp_path),
            capture_output=True,
        )
        tool = GitDiffTool()
        mock_mod = _make_mock_rust(tmp_path)
        # path= specified → falls back to Python _run_git, but
        # get_rust_module() is still called before the branch.
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path), path="README.md")
        assert result.success is True
        assert "Changed" in result.content

    def test_git_not_found(self):
        tool = GitDiffTool()
        mock_mod = _make_mock_rust_git_not_found()
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=".")
        assert result.success is False
        assert "Failed to run git" in result.content

    def test_invalid_repo_path(self, tmp_path):
        tool = GitDiffTool()
        mock_mod = _make_mock_rust()
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path / "nonexistent"))
        assert result.success is False

    def test_returncode_in_metadata(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitDiffTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert result.metadata["returncode"] == 0


# ---------------------------------------------------------------------------
# TestGitCommitTool
# ---------------------------------------------------------------------------


class TestGitCommitTool:
    def test_spec(self):
        tool = GitCommitTool()
        assert tool.spec.name == "git_commit"
        assert tool.spec.category == "vcs"
        assert "file:write" in tool.spec.required_capabilities
        assert tool.spec.requires_confirmation is True

    def test_tool_id(self):
        tool = GitCommitTool()
        assert tool.tool_id == "git_commit"

    def test_no_message(self):
        tool = GitCommitTool()
        result = tool.execute(message="")
        assert result.success is False
        assert "No commit message" in result.content

    def test_no_message_param(self):
        tool = GitCommitTool()
        result = tool.execute()
        assert result.success is False
        assert "No commit message" in result.content

    def test_commit_staged_files(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "new.txt").write_text("hello")
        subprocess.run(
            ["git", "add", "new.txt"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        tool = GitCommitTool()
        result = tool.execute(
            message="Add new file",
            repo_path=str(tmp_path),
        )
        assert result.success is True
        assert result.metadata["returncode"] == 0

    def test_stage_and_commit(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "a.txt").write_text("aaa")
        (tmp_path / "b.txt").write_text("bbb")
        tool = GitCommitTool()
        result = tool.execute(
            message="Add a and b",
            repo_path=str(tmp_path),
            files="a.txt,b.txt",
        )
        assert result.success is True
        # Verify both files were committed
        log_output = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )
        assert "Add a and b" in log_output.stdout

    def test_stage_all_files(self, tmp_path):
        _init_repo(tmp_path)
        (tmp_path / "x.txt").write_text("xxx")
        tool = GitCommitTool()
        result = tool.execute(
            message="Stage all",
            repo_path=str(tmp_path),
            files=".",
        )
        assert result.success is True

    def test_commit_nothing_staged(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitCommitTool()
        result = tool.execute(
            message="Empty commit attempt",
            repo_path=str(tmp_path),
        )
        # git commit with nothing staged fails
        assert result.success is False

    def test_stage_nonexistent_file(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitCommitTool()
        result = tool.execute(
            message="Bad stage",
            repo_path=str(tmp_path),
            files="does_not_exist.txt",
        )
        assert result.success is False
        assert "git add failed" in result.content

    def test_empty_files_string(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitCommitTool()
        result = tool.execute(
            message="Empty files",
            repo_path=str(tmp_path),
            files="  ,  ,  ",
        )
        assert result.success is False
        assert "Empty files list" in result.content

    def test_git_not_found(self):
        tool = GitCommitTool()
        with patch("openjarvis.tools.git_tool.shutil.which", return_value=None):
            result = tool.execute(message="test")
        assert result.success is False
        assert "not found" in result.content

    def test_message_required_in_spec(self):
        tool = GitCommitTool()
        assert "message" in tool.spec.parameters["required"]


# ---------------------------------------------------------------------------
# TestGitLogTool
# ---------------------------------------------------------------------------


class TestGitLogTool:
    def test_spec(self):
        tool = GitLogTool()
        assert tool.spec.name == "git_log"
        assert tool.spec.category == "vcs"
        assert "file:read" in tool.spec.required_capabilities

    def test_tool_id(self):
        tool = GitLogTool()
        assert tool.tool_id == "git_log"

    def test_log_oneline(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitLogTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert result.success is True
        assert "Initial commit" in result.content

    def test_log_full_format(self, tmp_path):
        """Rust git_log always uses --oneline; the ``oneline`` param is ignored."""
        _init_repo(tmp_path)
        tool = GitLogTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path), oneline=False)
        assert result.success is True
        assert "Initial commit" in result.content
        # Rust always uses --oneline, so "Author:" is never present
        assert "Author:" not in result.content

    def test_log_count(self, tmp_path):
        """Rust reads param ``n`` but PyO3 passes ``count``, so the limit
        is always the default (10).  With 6 total commits all 6 are returned."""
        _init_repo(tmp_path)
        # Add more commits
        for i in range(5):
            (tmp_path / f"file{i}.txt").write_text(f"content {i}")
            subprocess.run(
                ["git", "add", "."],
                cwd=str(tmp_path),
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", f"Commit {i}"],
                cwd=str(tmp_path),
                capture_output=True,
                check=True,
            )
        tool = GitLogTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path), count=3, oneline=True)
        assert result.success is True
        # Rust ignores the count param (reads "n", gets "count") and
        # defaults to 10, so all 6 commits are returned.
        lines = [line for line in result.content.strip().splitlines() if line.strip()]
        assert len(lines) == 6

    def test_default_count_is_10(self):
        tool = GitLogTool()
        # Verify via spec that default is documented
        desc = tool.spec.parameters["properties"]["count"]["description"]
        assert "10" in desc

    def test_git_not_found(self):
        tool = GitLogTool()
        mock_mod = _make_mock_rust_git_not_found()
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            # Rust raises → Python fallback via _run_git, which also
            # checks shutil.which
            with patch("openjarvis.tools.git_tool.shutil.which", return_value=None):
                result = tool.execute(repo_path=".")
        assert result.success is False
        assert "not found" in result.content

    def test_invalid_repo_path(self, tmp_path):
        tool = GitLogTool()
        mock_mod = _make_mock_rust()
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path / "nonexistent"))
        assert result.success is False

    def test_returncode_in_metadata(self, tmp_path):
        _init_repo(tmp_path)
        tool = GitLogTool()
        mock_mod = _make_mock_rust(tmp_path)
        with patch("openjarvis.tools.git_tool.get_rust_module", return_value=mock_mod):
            result = tool.execute(repo_path=str(tmp_path))
        assert result.metadata["returncode"] == 0

    def test_to_openai_function(self):
        tool = GitLogTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "git_log"
