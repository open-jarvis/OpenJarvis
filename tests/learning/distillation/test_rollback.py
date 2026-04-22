"""Integration test: apply session then rollback via CheckpointStore."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _setup_config_tree(root: Path) -> None:
    (root / "agents" / "simple").mkdir(parents=True)
    (root / "tools").mkdir(parents=True)
    (root / "config.toml").write_text("[learning]\nenabled = true\n")
    (root / "agents" / "simple" / "system_prompt.md").write_text(
        "You are a helpful assistant.\n"
    )
    (root / "tools" / "descriptions.toml").write_text("[web_search]\n")


class TestRollbackIntegration:
    def test_rollback_restores_files(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.checkpoint.store import (
            CheckpointStore,
        )

        root = tmp_path / "oj_home"
        _setup_config_tree(root)

        store = CheckpointStore(root)
        store.init()
        original_prompt = (root / "agents" / "simple" / "system_prompt.md").read_text()

        # Simulate two edits in a session
        h1 = store.begin_stage("edit-001")
        prompt_file = root / "agents" / "simple" / "system_prompt.md"
        prompt_file.write_text("Modified prompt v1.\n")
        store.commit_stage(
            h1,
            message="learning: edit-001",
            session_id="session-A",
            risk_tier="auto",
        )

        h2 = store.begin_stage("edit-002")
        tools_file = root / "tools" / "descriptions.toml"
        tools_file.write_text("[web_search]\nupdated = true\n")
        store.commit_stage(
            h2,
            message="learning: edit-002",
            session_id="session-A",
            risk_tier="auto",
        )

        # Verify files changed
        assert prompt_file.read_text() == "Modified prompt v1.\n"

        # Rollback the session
        revert_shas = store.revert_session("session-A")
        assert len(revert_shas) == 2

        # Files restored
        assert prompt_file.read_text() == original_prompt
        assert tools_file.read_text() == "[web_search]\n"

        # History preserved (reverts are new commits)
        log_count = len(_git(root, "log", "--oneline").splitlines())
        assert log_count >= 5  # baseline + 2 edits + 2 reverts

    def test_rollback_nonexistent_session(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.checkpoint.store import (
            CheckpointStore,
        )

        root = tmp_path / "oj_home"
        _setup_config_tree(root)

        store = CheckpointStore(root)
        store.init()

        result = store.revert_session("nonexistent-session")
        assert result == []
