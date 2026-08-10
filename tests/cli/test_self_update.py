"""Smoke tests for `jarvis self-update`.

Focus on the surface that's easy to corrupt (output formatting, exit
codes, --check short-circuit). We don't actually run pip/uv from a
unit test; the subprocess call is mocked.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli._install_detect import InstallInfo
from openjarvis.cli.self_update_cmd import self_update


def _mock_info(kind: str = "pypi") -> InstallInfo:
    info = InstallInfo(
        kind=kind,
        upgrade_command={
            "pypi": "pip install --upgrade openjarvis",
            "uv-tool": "uv tool upgrade openjarvis",
            "editable-git": "cd /tmp/repo && git pull && uv sync",
            "unknown": "pip install --upgrade openjarvis",
        }[kind],
    )
    if kind == "editable-git":
        return InstallInfo(
            kind=info.kind,
            upgrade_command=info.upgrade_command,
            repo_root=Path("/tmp/repo"),
            editable_mode="project-venv",
            sync_args=("--inexact",),
        )
    return info


def test_check_flag_prints_command_and_exits_clean():
    with patch(
        "openjarvis.cli.self_update_cmd.detect_install",
        return_value=_mock_info("pypi"),
    ):
        runner = CliRunner()
        result = runner.invoke(self_update, ["--check"])
    assert result.exit_code == 0
    assert "pip install --upgrade openjarvis" in result.output
    assert "Install method: pypi" in result.output


def test_check_does_not_invoke_subprocess():
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=_mock_info("pypi"),
        ),
        patch("openjarvis.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        CliRunner().invoke(self_update, ["--check"])
    mock_run.assert_not_called()


def test_yes_skips_confirmation_and_runs_trusted_argv():
    info = replace(
        _mock_info("pypi"),
        upgrade_command="display text that must never be executed",
    )
    mock_proc = MagicMock(returncode=0)
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=info,
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            return_value=mock_proc,
        ) as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert kwargs.get("shell") is not True
    assert args[0] == ["pip", "install", "--upgrade", "openjarvis"]


def test_uv_tool_update_runs_trusted_argv():
    info = replace(
        _mock_info("uv-tool"),
        upgrade_command="display text that must never be executed",
    )
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=info,
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            return_value=MagicMock(returncode=0),
        ) as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])

    assert result.exit_code == 0
    mock_run.assert_called_once_with(["uv", "tool", "upgrade", "openjarvis"])


def test_project_venv_runs_git_then_profiled_sync(tmp_path):
    info = InstallInfo(
        kind="editable-git",
        upgrade_command="preview only",
        repo_root=tmp_path / "repo with spaces",
        editable_mode="project-venv",
        sync_args=("--extra", "desktop", "--group", "desktop-native"),
    )
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=info,
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            side_effect=[MagicMock(returncode=0), MagicMock(returncode=0)],
        ) as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])

    assert result.exit_code == 0
    assert [call.args[0] for call in mock_run.call_args_list] == [
        ["git", "-C", str(info.repo_root), "pull", "--ff-only"],
        [
            "uv",
            "sync",
            "--extra",
            "desktop",
            "--group",
            "desktop-native",
        ],
    ]
    assert mock_run.call_args_list[1].kwargs["cwd"] == info.repo_root
    assert all(call.kwargs.get("shell") is not True for call in mock_run.call_args_list)


def test_external_venv_reinstalls_into_running_python(tmp_path):
    repo = tmp_path / "repo with spaces"
    python = tmp_path / "installed env" / "Scripts" / "python.exe"
    info = InstallInfo(
        kind="editable-git",
        upgrade_command="preview only",
        repo_root=repo,
        editable_mode="external-venv",
        python_executable=python,
    )
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=info,
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            side_effect=[MagicMock(returncode=0), MagicMock(returncode=0)],
        ) as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])

    assert result.exit_code == 0
    assert mock_run.call_args_list[1].args[0] == [
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "-e",
        str(repo),
    ]
    assert mock_run.call_args_list[1].kwargs["cwd"] == repo


def test_git_failure_does_not_run_uv(tmp_path):
    info = InstallInfo(
        kind="editable-git",
        upgrade_command="preview only",
        repo_root=tmp_path,
        editable_mode="project-venv",
        sync_args=("--inexact",),
    )
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=info,
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            return_value=MagicMock(returncode=7),
        ) as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])

    assert result.exit_code == 7
    assert mock_run.call_count == 1


def test_install_profile_warning_is_printed():
    info = replace(
        _mock_info("editable-git"),
        warning="Optional dependencies will be preserved.",
    )
    with patch(
        "openjarvis.cli.self_update_cmd.detect_install",
        return_value=info,
    ):
        result = CliRunner().invoke(self_update, ["--check"])

    assert result.exit_code == 0
    assert "Optional dependencies will be preserved" in result.output


def test_failed_upgrade_propagates_exit_code():
    mock_proc = MagicMock(returncode=3)
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=_mock_info("pypi"),
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            return_value=mock_proc,
        ),
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 3


def test_unknown_install_kind_warns_but_proceeds():
    mock_proc = MagicMock(returncode=0)
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=_mock_info("unknown"),
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            return_value=mock_proc,
        ),
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 0
    assert "Could not determine install method" in result.output


def test_decline_confirmation_exits_nonzero():
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=_mock_info("pypi"),
        ),
        patch("openjarvis.cli.self_update_cmd.subprocess.run") as mock_run,
    ):
        result = CliRunner().invoke(self_update, input="n\n")
    assert result.exit_code == 1
    assert "Aborted" in result.output
    mock_run.assert_not_called()
