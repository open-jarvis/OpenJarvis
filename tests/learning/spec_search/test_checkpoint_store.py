"""Tests for openjarvis.learning.spec_search.checkpoint.store module."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(cwd: Path, *args: str) -> str:
    """Helper to run git commands in tests."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _setup_isolated_repo_root(tmp_path: Path) -> Path:
    """Create a fake openjarvis-home directory tree with config files for the
    CheckpointStore to track. Returns the root."""
    root = tmp_path / "openjarvis_home"
    (root / "agents" / "simple").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    (root / "config.toml").write_text("[learning]\nenabled = true\n")
    (root / "agents" / "simple" / "system_prompt.md").write_text(
        "You are a helpful assistant.\n"
    )
    (root / "tools" / "descriptions.toml").write_text("[web_search]\n")
    return root


class TestCheckpointStoreInit:
    """Tests for CheckpointStore.init()."""

    def test_creates_repo_with_baseline_commit(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.checkpoint.store import (
            CheckpointStore,
        )

        root = _setup_isolated_repo_root(tmp_path)
        store = CheckpointStore(root)
        store.init()

        assert (root / ".git").exists()
        log = _git(root, "log", "--oneline")
        assert "baseline" in log

    def test_init_idempotent(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.checkpoint.store import (
            CheckpointStore,
        )

        root = _setup_isolated_repo_root(tmp_path)
        store = CheckpointStore(root)
        store.init()
        first_sha = store.current_sha()

        store.init()  # Should not raise or create a second baseline.
        assert store.current_sha() == first_sha

    def test_init_refuses_inside_source_tree(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from openjarvis.learning.spec_search.checkpoint.store import (
            CheckpointStore,
        )
        from openjarvis.learning.spec_search.storage import paths

        source_root = paths._find_source_root()
        assert source_root is not None
        bad_root = source_root / "fake_openjarvis_home"

        store = CheckpointStore(bad_root)
        with pytest.raises(paths.ConfigurationError):
            store.init()


class TestStageCommitDiscard:
    """Tests for begin_stage / commit_stage / discard_stage."""

    def test_commit_stage_creates_commit_with_trailers(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.checkpoint.store import (
            CheckpointStore,
        )

        root = _setup_isolated_repo_root(tmp_path)
        store = CheckpointStore(root)
        store.init()

        handle = store.begin_stage("edit-001")
        # Mutate a tracked file in the working tree.
        (root / "agents" / "simple" / "system_prompt.md").write_text(
            "You are a helpful, math-aware assistant.\n"
        )

        new_sha = store.commit_stage(
            handle,
            message="learning: edit-001 add math hint",
            session_id="session-001",
            risk_tier="review",
        )

        # New commit exists.
        assert new_sha != handle.pre_stage_sha
        # Commit message contains structured trailers.
        body = _git(root, "log", "-1", "--format=%B", new_sha)
        assert "Edit-ID: edit-001" in body
        assert "Session-ID: session-001" in body
        assert "Risk-Tier: review" in body

    def test_discard_stage_restores_working_tree(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.checkpoint.store import (
            CheckpointStore,
        )

        root = _setup_isolated_repo_root(tmp_path)
        store = CheckpointStore(root)
        store.init()
        original = (root / "agents" / "simple" / "system_prompt.md").read_text()

        handle = store.begin_stage("edit-002")
        (root / "agents" / "simple" / "system_prompt.md").write_text(
            "Mutated content that should be discarded.\n"
        )

        store.discard_stage(handle)

        restored = (root / "agents" / "simple" / "system_prompt.md").read_text()
        assert restored == original
        # HEAD must equal the pre-stage sha.
        assert store.current_sha() == handle.pre_stage_sha

    def test_begin_stage_refuses_dirty_working_tree(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.checkpoint.store import (
            CheckpointStore,
            DirtyWorkingTreeError,
        )

        root = _setup_isolated_repo_root(tmp_path)
        store = CheckpointStore(root)
        store.init()

        # Create an untracked, uncommitted change.
        (root / "agents" / "simple" / "system_prompt.md").write_text(
            "Pre-existing manual edit.\n"
        )

        with pytest.raises(DirtyWorkingTreeError):
            store.begin_stage("edit-003")


class TestRevertSession:
    """Tests for revert_session."""

    def test_revert_creates_new_commits_and_does_not_rewrite(
        self, tmp_path: Path
    ) -> None:
        from openjarvis.learning.spec_search.checkpoint.store import (
            CheckpointStore,
        )

        root = _setup_isolated_repo_root(tmp_path)
        store = CheckpointStore(root)
        store.init()

        # Apply two commits tagged with the same session id.
        handle1 = store.begin_stage("edit-001")
        (root / "agents" / "simple" / "system_prompt.md").write_text("version A\n")
        store.commit_stage(
            handle1,
            message="learning: edit-001 v A",
            session_id="session-XYZ",
            risk_tier="auto",
        )

        handle2 = store.begin_stage("edit-002")
        (root / "tools" / "descriptions.toml").write_text(
            "[web_search]\nupdated = true\n"
        )
        store.commit_stage(
            handle2,
            message="learning: edit-002 update tool",
            session_id="session-XYZ",
            risk_tier="auto",
        )

        before_revert_log_count = len(_git(root, "log", "--oneline").splitlines())

        revert_shas = store.revert_session("session-XYZ")
        assert len(revert_shas) == 2

        # Two new commits added (the reverts), no history rewriting.
        after_revert_log_count = len(_git(root, "log", "--oneline").splitlines())
        assert after_revert_log_count == before_revert_log_count + 2

        # Files restored to baseline.
        assert (
            root / "agents" / "simple" / "system_prompt.md"
        ).read_text() == "You are a helpful assistant.\n"
        assert (root / "tools" / "descriptions.toml").read_text() == "[web_search]\n"

    def test_revert_session_with_no_commits_returns_empty(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.checkpoint.store import (
            CheckpointStore,
        )

        root = _setup_isolated_repo_root(tmp_path)
        store = CheckpointStore(root)
        store.init()

        result = store.revert_session("session-with-no-commits")
        assert result == []
