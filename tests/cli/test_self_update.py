"""Smoke tests for `jarvis self-update`.

Focus on the surface that's easy to corrupt (output formatting, exit
codes, --check short-circuit). We don't actually run pip/uv from a
unit test; the subprocess call is mocked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli._install_detect import InstallInfo
from openjarvis.cli.self_update_cmd import self_update


def _mock_info(kind: str = "pypi") -> InstallInfo:
    return InstallInfo(
        kind=kind,
        upgrade_command={
            "pypi": "pip install --upgrade openjarvis",
            "uv-tool": "uv tool upgrade openjarvis",
            "editable-git": "cd /tmp/repo && git pull && uv sync",
            "unknown": "pip install --upgrade openjarvis",
        }[kind],
    )


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


def test_yes_skips_confirmation_and_runs():
    mock_proc = MagicMock(returncode=0)
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=_mock_info("pypi"),
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            return_value=mock_proc,
        ) as mock_run,
    ):
        result = CliRunner().invoke(self_update, ["-y"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
    # PyPI path uses shlex.split (no shell=True)
    args, kwargs = mock_run.call_args
    assert kwargs.get("shell") is not True
    assert args[0] == ["pip", "install", "--upgrade", "openjarvis"]


def test_editable_git_uses_shell_true():
    """The git path uses `&&` so shell=True is needed; the others don't."""
    mock_proc = MagicMock(returncode=0)
    with (
        patch(
            "openjarvis.cli.self_update_cmd.detect_install",
            return_value=_mock_info("editable-git"),
        ),
        patch(
            "openjarvis.cli.self_update_cmd.subprocess.run",
            return_value=mock_proc,
        ) as mock_run,
    ):
        CliRunner().invoke(self_update, ["-y"])
    _, kwargs = mock_run.call_args
    assert kwargs.get("shell") is True


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
