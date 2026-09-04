"""Cached skill installation survives failed upstream refreshes."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.config import JarvisConfig, SkillSourceConfig
from openjarvis.skills.sources.github import GitHubResolver
from openjarvis.skills.sources.hermes import HermesResolver
from openjarvis.skills.sources.openclaw import OpenClawResolver


@pytest.fixture(params=["hermes", "openclaw", "github"])
def resolver(request, tmp_path):
    root = tmp_path / "cache"
    kind = request.param
    if kind == "github":
        return GitHubResolver(root, "https://example.invalid/skills.git")
    return {"hermes": HermesResolver, "openclaw": OpenClawResolver}[kind](root)


def cached_skill(resolver):
    root = resolver.cache_dir()
    folder = root / "skills" / "research" / "cached"
    folder.mkdir(parents=True)
    (root / ".git").mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: cached\ndescription: A cached skill\n---\nRead these instructions."
    )
    return folder


def failed_pull(command, **kwargs):
    if "pull" in command:
        raise subprocess.CalledProcessError(1, command, stderr="network unavailable")
    if "rev-parse" in command:
        return subprocess.CompletedProcess(command, 0, stdout="cached-commit\n")
    raise AssertionError(f"Unexpected command: {command}")


def test_usable_cache_survives_refresh_failure(resolver):
    folder = cached_skill(resolver)
    with patch("subprocess.run", side_effect=failed_pull):
        resolver.sync()
        found = resolver.list_skills()
    assert len(found) == 1
    assert found[0].path == folder
    assert found[0].commit == "cached-commit"
    assert "may be stale" in resolver.refresh_warning


def test_initial_clone_failure_is_fatal(resolver):
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
        with pytest.raises(subprocess.CalledProcessError):
            resolver.sync()
    assert not resolver.refresh_warning


def test_empty_cache_does_not_hide_refresh_failure(resolver):
    (resolver.cache_dir() / ".git").mkdir(parents=True)
    with patch("subprocess.run", side_effect=failed_pull):
        with pytest.raises(subprocess.CalledProcessError):
            resolver.sync()
    assert not resolver.refresh_warning


def test_successful_refresh_clears_stale_warning(resolver):
    cached_skill(resolver)
    resolver.refresh_warning = "stale warning"
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
        resolver.sync()
    assert resolver.refresh_warning == ""


def test_install_uses_cached_skill_and_displays_warning(
    resolver, tmp_path, monkeypatch
):
    cached_skill(resolver)
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "installed"))
    with (
        patch("subprocess.run", side_effect=failed_pull),
        patch("openjarvis.cli.skill_cmd._get_resolver", return_value=resolver),
    ):
        result = CliRunner().invoke(
            cli, ["skill", "install", f"{resolver.name}:cached"]
        )
    assert result.exit_code == 0, result.output
    assert "may be stale" in result.output
    assert "Installed:" in result.output
    assert (
        tmp_path / "installed" / "skills" / resolver.name / "cached" / "SKILL.md"
    ).is_file()


def test_cache_cannot_satisfy_missing_skill(resolver, tmp_path, monkeypatch):
    cached_skill(resolver)
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "installed"))
    with (
        patch("subprocess.run", side_effect=failed_pull),
        patch("openjarvis.cli.skill_cmd._get_resolver", return_value=resolver),
    ):
        result = CliRunner().invoke(
            cli, ["skill", "install", f"{resolver.name}:missing"]
        )
    assert result.exit_code != 0
    assert "No skill named 'missing'" in result.output


def test_update_does_not_claim_refresh_succeeded(resolver):
    cached_skill(resolver)
    cfg = JarvisConfig()
    cfg.skills.sources = [SkillSourceConfig(source=resolver.name)]
    with (
        patch("subprocess.run", side_effect=failed_pull),
        patch("openjarvis.cli.skill_cmd._get_resolver", return_value=resolver),
        patch("openjarvis.cli.skill_cmd.load_config", return_value=cfg),
    ):
        result = CliRunner().invoke(cli, ["skill", "update"])
    assert "may be stale" in result.output
    assert "OK" not in result.output
