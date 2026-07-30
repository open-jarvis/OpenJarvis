"""Task-worktree Git flow and prohibited-operation tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from openjarvis.tools.git_secure import GitPolicyError, SecureGitService


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return result.stdout.strip()


@pytest.fixture
def git_service(tmp_path: Path):
    repo = tmp_path / "integration"
    repo.mkdir()
    _git(repo, "init", "-b", "feature/integration")
    _git(repo, "config", "user.name", "Phase Five")
    _git(repo, "config", "user.email", "phase5@example.invalid")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "baseline")
    _git(repo, "remote", "add", "upstream", "https://example.invalid/upstream.git")
    _git(repo, "remote", "set-url", "--push", "upstream", "DISABLED")
    service = SecureGitService(
        integration_repo=repo,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    return service, repo


def test_upstream_push_is_disabled(git_service) -> None:
    service, _ = git_service
    remote = service.verify_remote_safety()
    assert remote["upstream_push"] == "DISABLED"
    with pytest.raises(GitPolicyError, match="push.*disabled"):
        service.reject_push(remote="upstream")
    with pytest.raises(GitPolicyError, match="force-push.*disabled"):
        service.reject_push(remote="origin", force=True)
    with pytest.raises(GitPolicyError, match="tag push.*disabled"):
        service.reject_push(remote="origin", tags=True)


def test_worktree_commit_restore_bundle_and_remove(git_service) -> None:
    service, repo = git_service
    worktree = service.worktree_root / "task-one"
    created = service.create_worktree(
        destination=worktree,
        branch="task/one",
    )
    assert created["branch"] == "task/one"
    assert service.branch(worktree)["owned_worktree"] is True

    readme = worktree / "README.md"
    readme.write_text("task change\n", encoding="utf-8")
    assert "task change" in service.diff(worktree)
    committed = service.commit(
        worktree=worktree,
        files=["README.md"],
        message="test: isolated task commit",
    )
    assert committed["old_head"] != committed["new_head"]
    assert _git(repo, "rev-parse", "HEAD") != committed["new_head"]

    readme.write_text("uncommitted\n", encoding="utf-8")
    restored = service.restore(
        worktree=worktree,
        files=["README.md"],
        artifact_name="task-one-before-restore",
    )
    assert Path(restored["artifact"]).exists()
    assert readme.read_text(encoding="utf-8") == "task change\n"

    bundle = service.create_bundle(ref="task/one", artifact_name="task-one")
    assert Path(bundle["bundle"]).exists()
    assert "task/one" in bundle["heads"]
    assert len(bundle["sha256"]) == 64

    removed = service.remove_worktree(worktree)
    assert removed["removed"] == "true"
    assert not worktree.exists()


def test_commit_in_integration_repo_is_blocked(git_service) -> None:
    service, repo = git_service
    with pytest.raises(GitPolicyError, match="owned task worktree"):
        service.commit(worktree=repo, files=["README.md"], message="blocked")


def test_worktree_requires_clean_integration_repo(git_service) -> None:
    service, repo = git_service
    (repo / "dirty.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(GitPolicyError, match="must be clean"):
        service.create_worktree(
            destination=service.worktree_root / "dirty",
            branch="task/dirty",
        )


def test_non_task_branch_and_foreign_worktree_are_blocked(git_service) -> None:
    service, _ = git_service
    with pytest.raises(GitPolicyError, match="must start"):
        service.create_worktree(
            destination=service.worktree_root / "bad",
            branch="feature/not-task",
        )
    foreign = service.worktree_root / "foreign"
    foreign.mkdir()
    _git(foreign, "init")
    with pytest.raises(GitPolicyError, match="not an owned"):
        service.status(foreign)
