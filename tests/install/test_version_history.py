"""Exercise installer clone flags and update repair against real local Git repos."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from openjarvis.cli.self_update_cmd import _update_git_checkout

ROOT = Path(__file__).resolve().parents[2]
_RUN = subprocess.run


def _git(repo: Path, *args: str) -> str:
    return _RUN(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    _git(repo, "add", name)
    _git(repo, "-c", "commit.gpgsign=false", "commit", "-m", name)


@pytest.fixture()
def tagged_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Version Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "uploadpack.allowFilter", "true")
    _commit(repo, "README.md", "release\n")
    _git(repo, "-c", "tag.gpgsign=false", "tag", "v1.0.3")
    _commit(repo, "new-file.txt", "development commit after the release\n")
    return repo


@pytest.mark.parametrize(
    "script,command_prefix",
    [
        ("scripts/install/install.sh", "git clone "),
        ("deploy/windows/install.ps1", "& $gitExe clone "),
    ],
)
def test_installer_clone_retains_reachable_release_tag(
    tagged_repo: Path,
    tmp_path: Path,
    script: str,
    command_prefix: str,
) -> None:
    # Execute the actual clone arguments shipped by each installer, substituting
    # only a local origin and destination. No network or installer side effects.
    lines = (ROOT / script).read_text().splitlines()
    clone_line = next(
        line.strip() for line in lines if line.strip().startswith(command_prefix)
    )
    args = shlex.split(clone_line[len(command_prefix) :])[:-2]
    clone = tmp_path / "fresh install"
    _git(tmp_path, "clone", *args, tagged_repo.as_uri(), str(clone))

    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"
    assert _git(clone, "describe", "--tags", "--long").startswith("v1.0.3-1-g")


@pytest.mark.parametrize("shallow", [True, False])
def test_update_recovers_version_before_reinstall_and_preserves_user_files(
    tagged_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shallow: bool,
) -> None:
    clone = tmp_path / "installed repo with spaces"
    flags = ["--depth", "1"] if shallow else ["--no-tags"]
    _git(tmp_path, "clone", *flags, tagged_repo.as_uri(), str(clone))
    assert _git(clone, "tag") == ""
    user_file = clone / "my settings.txt"
    user_file.write_text("preserve this\n")
    head = _git(clone, "rev-parse", "HEAD")
    active_venv = tmp_path / "managed environment"
    monkeypatch.setattr("openjarvis.cli.self_update_cmd.sys.prefix", str(active_venv))
    rebuild_versions: list[str] = []

    def run(command, **kwargs):
        if command[0] != "uv":
            return _RUN(command, **kwargs)
        assert command == [
            "uv",
            "sync",
            "--python",
            sys.executable,
            "--inexact",
            "--reinstall-package",
            "openjarvis",
        ]
        assert kwargs["env"]["UV_PROJECT_ENVIRONMENT"] == str(active_venv)
        rebuild_versions.append(_git(clone, "describe", "--tags", "--long"))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("openjarvis.cli.self_update_cmd.subprocess.run", run)
    assert _update_git_checkout(clone) == 0
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"
    assert _git(clone, "rev-parse", "HEAD") == head
    assert user_file.read_text() == "preserve this\n"
    assert len(rebuild_versions) == 1
    assert rebuild_versions[0].startswith("v1.0.3-1-g")


def test_update_does_not_merge_or_reinstall_diverged_checkout(
    tagged_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clone = tmp_path / "diverged"
    _git(tmp_path, "clone", tagged_repo.as_uri(), str(clone))
    _git(clone, "config", "user.name", "Version Test")
    _git(clone, "config", "user.email", "test@example.invalid")
    _commit(clone, "local.txt", "local work\n")
    _commit(tagged_repo, "remote.txt", "upstream work\n")
    original_head = _git(clone, "rev-parse", "HEAD")

    def run(command, **kwargs):
        assert command[0] != "uv", "Failed Git update must not report a rebuilt package"
        return _RUN(command, **kwargs)

    monkeypatch.setattr("openjarvis.cli.self_update_cmd.subprocess.run", run)
    assert _update_git_checkout(clone) != 0
    assert _git(clone, "rev-parse", "HEAD") == original_head
    assert (clone / "local.txt").read_text() == "local work\n"
