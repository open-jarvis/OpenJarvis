"""Exercise installer clone flags and update repair against real local Git repos."""

from __future__ import annotations

import json
import os
import shutil
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
        timeout=30,
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
    _commit(repo, "README.md", "release\n")
    _git(repo, "-c", "tag.gpgsign=false", "tag", "v1.0.3")
    _commit(repo, "new-file.txt", "development commit after the release\n")
    return repo


@pytest.fixture(params=["bash", "powershell"])
def installer(request):
    if request.param == "bash":
        if sys.platform == "win32":
            pytest.skip("Native Windows uses the PowerShell installer")
        executable = shutil.which("bash")
    else:
        executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        pytest.skip(f"{request.param} is not installed")
    return request.param, executable


def _installer_clone(installer, source, clone, cwd, *, env_extra=None):
    """Execute the shipped clone branch without bootstrapping an entire install."""
    kind, executable = installer
    env = {
        **os.environ,
        "OPENJARVIS_REPO_URL": source,
        "SRC_DIR": str(clone),
        "FORCE": "0",
    }
    env.update(env_extra or {})
    if kind == "bash":
        script = (ROOT / "scripts/install/install.sh").read_text()
        start = script.index("clone_repo() {\n")
        end = script.index("\n}\n", start) + 2
        command = [
            executable,
            "-c",
            "set -euo pipefail\n" + script[start:end] + "\nclone_repo",
        ]
    else:
        script = (ROOT / "deploy/windows/install.ps1").read_text()
        start = script.index("    if ($repoUrl -like 'file://*'")
        end = script.index("    if ($LASTEXITCODE", start)
        body = (
            "$ErrorActionPreference = 'Stop'\n"
            "$repoUrl = $env:OPENJARVIS_REPO_URL\n"
            "$srcDir = $env:SRC_DIR\n"
            "$gitExe = (Get-Command git).Source\n"
            + script[start:end]
            + "\nexit $LASTEXITCODE\n"
        )
        command = [executable, "-NoProfile", "-NonInteractive", "-Command", body]
    return _RUN(
        command,
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )


@pytest.mark.parametrize("source_kind", ["path", "file-url", "remote-url"])
def test_installer_clone_retains_reachable_release_tag(
    tagged_repo: Path,
    tmp_path: Path,
    installer,
    source_kind: str,
) -> None:
    clone = tmp_path / "fresh install"
    source = str(tagged_repo) if source_kind == "path" else tagged_repo.as_uri()
    env_extra = {}
    if source_kind == "remote-url":
        # Exercise remote argument selection without network access. This full
        # local server explicitly supports filtering, unlike shallow CI clones.
        _git(tagged_repo, "config", "uploadpack.allowFilter", "true")
        source = "https://example.invalid/openjarvis.git"
        env_extra = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{tagged_repo.as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_0": source,
        }
    _installer_clone(installer, source, clone, tmp_path, env_extra=env_extra)

    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"
    assert _git(clone, "describe", "--tags", "--long").startswith("v1.0.3-1-g")
    config = _git(clone, "config", "--local", "--list")
    assert ("remote.origin.promisor=true" in config) is (source_kind == "remote-url")


@pytest.mark.parametrize("source_kind", ["path", "relative-path", "file-url"])
def test_installer_clones_shallow_local_source_without_lazy_fetch_recursion(
    tagged_repo: Path,
    tmp_path: Path,
    installer,
    source_kind: str,
) -> None:
    source_repo = tmp_path / "shallow [local] source"
    _git(tmp_path, "clone", "--depth", "1", tagged_repo.as_uri(), str(source_repo))
    assert _git(source_repo, "rev-parse", "--is-shallow-repository") == "true"
    source = {
        "path": str(source_repo),
        "relative-path": source_repo.name,
        "file-url": source_repo.as_uri(),
    }[source_kind]
    clone = tmp_path / "installed from shallow source"
    trace_path = tmp_path / "clone-trace.jsonl"
    completed = _installer_clone(
        installer,
        source,
        clone,
        tmp_path,
        env_extra={"GIT_TRACE2_EVENT": str(trace_path)},
    )

    assert "filtering not recognized" not in completed.stderr
    assert "unable to fork" not in completed.stderr
    assert "shallow roots" not in completed.stderr
    events = [json.loads(line) for line in trace_path.read_text().splitlines()]
    upload_packs = [
        event
        for event in events
        if event.get("event") == "child_start"
        and any("upload-pack" in arg for arg in event.get("argv", []))
    ]
    assert len(upload_packs) <= 1, (
        "Local clone must not recursively fetch missing objects"
    )
    assert _git(clone, "rev-parse", "HEAD") == _git(source_repo, "rev-parse", "HEAD")
    assert _git(clone, "rev-list", "--all", "--count") == _git(
        source_repo, "rev-list", "--all", "--count"
    )
    assert (clone / "README.md").read_text() == "release\n"
    config = _git(clone, "config", "--local", "--list")
    assert "promisor" not in config
    assert "partialclone" not in config.lower()
    assert not list((clone / ".git" / "objects" / "pack").glob("*.promisor"))


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
