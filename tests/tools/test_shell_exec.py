"""Tests for the shell_exec tool.

Tests mock the Rust backend to verify the Python wrapper handles
the Rust output format correctly:
    "Exit code: {code}\\n--- stdout ---\\n{stdout}\\n--- stderr ---\\n{stderr}"
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openjarvis._rust_bridge import RUST_AVAILABLE
from openjarvis.tools.shell_exec import ShellExecTool


def _rust_output(
    stdout: str = "",
    stderr: str = "",
    code: int = 0,
    *,
    timed_out: bool = False,
    output_limited: bool = False,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
):
    """Build the structured Rust shell_exec result used by the PyO3 API."""
    content = f"Exit code: {code}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    if timed_out:
        content = f"Command timed out.\n{content}"
    if output_limited:
        content = f"Output limit reached; process tree terminated.\n{content}"
    if stdout_truncated:
        content += "\n[stdout truncated: combined capture limit reached]"
    if stderr_truncated:
        content += "\n[stderr truncated: combined capture limit reached]"
    return SimpleNamespace(
        content=content,
        success=(code == 0 and not timed_out and not output_limited),
        returncode=code,
        timed_out=timed_out,
        output_limited=output_limited,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def _make_mock_rust(side_effect=None, return_value=None):
    """Create a mock Rust module with a ShellExecTool that returns *return_value*
    or raises via *side_effect*."""
    mock_tool_instance = MagicMock()
    if side_effect is not None:
        mock_tool_instance.execute.side_effect = side_effect
    else:
        mock_tool_instance.execute.return_value = return_value
    mock_shell_cls = MagicMock(return_value=mock_tool_instance)
    mock_mod = MagicMock()
    mock_mod.ShellExecTool = mock_shell_cls
    return mock_mod


class TestShellExecTool:
    def test_registered_via_tools_package_import(self):
        import openjarvis.tools as tools_pkg
        from openjarvis.core.registry import ToolRegistry

        sys.modules.pop("openjarvis.tools.shell_exec", None)
        importlib.reload(tools_pkg)

        assert ToolRegistry.contains("shell_exec")

    def test_spec(self):
        tool = ShellExecTool()
        assert tool.spec.name == "shell_exec"
        assert tool.spec.category == "system"
        assert tool.spec.requires_confirmation is True
        assert tool.spec.timeout_seconds == 30.0
        assert "code:execute" in tool.spec.required_capabilities
        assert "command" in tool.spec.parameters["properties"]
        assert "command" in tool.spec.parameters["required"]

    def test_no_command(self):
        tool = ShellExecTool()
        result = tool.execute(command="")
        assert result.success is False
        assert "No command" in result.content

    def test_no_command_param(self):
        tool = ShellExecTool()
        result = tool.execute()
        assert result.success is False
        assert "No command" in result.content

    def test_simple_echo(self):
        mock_mod = _make_mock_rust(
            return_value=_rust_output(stdout="hello\n"),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.content
        assert "--- stdout ---" in result.content

    def test_capture_stderr(self):
        mock_mod = _make_mock_rust(
            return_value=_rust_output(stderr="error_msg\n"),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="echo error_msg >&2")
        assert "error_msg" in result.content
        assert "--- stderr ---" in result.content

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="native Rust backend required for process-tree timeout test",
    )
    def test_timeout_exceeded(self):
        tool = ShellExecTool()
        command = "ping -n 60 127.0.0.1 >nul" if os.name == "nt" else "sleep 60"
        result = tool.execute(command=command, timeout=1)
        assert result.success is False
        assert "timed out" in result.content
        assert result.metadata["returncode"] == -1
        assert result.metadata["timeout_used"] == 1
        assert result.metadata["timed_out"] is True
        assert result.metadata["output_limited"] is False

    def test_timeout_capped_at_max(self):
        """Timeout is capped in both Python and Rust."""
        mock_mod = _make_mock_rust(
            return_value=_rust_output(stdout="ok\n"),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="echo ok", timeout=999)
        assert result.success is True
        assert result.metadata["timeout_used"] == 300

    def test_working_dir(self, tmp_path):
        mock_mod = _make_mock_rust(
            return_value=_rust_output(stdout=str(tmp_path) + "\n"),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="pwd", working_dir=str(tmp_path))
        assert result.success is True
        assert str(tmp_path) in result.content
        assert result.metadata["working_dir"] == str(tmp_path)

    def test_working_dir_not_exists(self):
        tool = ShellExecTool()
        result = tool.execute(command="echo hi", working_dir="/nonexistent/path")
        assert result.success is False
        assert "does not exist" in result.content

    def test_working_dir_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data", encoding="utf-8")
        tool = ShellExecTool()
        result = tool.execute(command="echo hi", working_dir=str(f))
        assert result.success is False
        assert "not a directory" in result.content

    def test_environment_passthrough_is_not_a_tool_parameter(self):
        assert "env_passthrough" not in ShellExecTool().spec.parameters["properties"]

    def test_model_cannot_forward_a_dummy_api_key(self, monkeypatch):
        marker = "OPENJARVIS_WP2_DUMMY_API_TOKEN"
        monkeypatch.setenv(marker, "dummy-key-must-not-be-forwarded")
        mock_mod = _make_mock_rust(return_value=_rust_output(stdout=""))
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = ShellExecTool().execute(
                command=f"echo ${marker}",
                env_passthrough=[marker],
            )
        assert result.success is True
        mock_mod.ShellExecTool.return_value.execute.assert_called_once_with(
            f"echo ${marker}", None, 30
        )

    def test_returncode_in_metadata(self):
        mock_mod = _make_mock_rust(
            return_value=_rust_output(stdout="ok\n"),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="echo ok")
        assert result.success is True
        assert result.metadata["returncode"] == 0

    def test_nonzero_returncode(self):
        """The actual non-zero exit status survives the Rust/Python boundary."""
        mock_mod = _make_mock_rust(
            return_value=_rust_output(code=42),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="exit 42")
        assert result.success is False
        assert result.metadata["returncode"] == 42
        assert "Exit code: 42" in result.content

    def test_timeout_never_reports_success_even_if_backend_flag_is_inconsistent(self):
        mock_mod = _make_mock_rust(
            return_value=SimpleNamespace(
                content="Command timed out.",
                success=True,
                returncode=0,
                timed_out=True,
                stdout_truncated=False,
                stderr_truncated=False,
            ),
        )
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = ShellExecTool().execute(command="sleep 10", timeout=1)

        assert result.success is False
        assert result.metadata["timed_out"] is True

    def test_output_limit_metadata_is_preserved(self):
        mock_mod = _make_mock_rust(
            return_value=SimpleNamespace(
                content="Output limit reached.",
                success=True,
                returncode=0,
                timed_out=False,
                output_limited=True,
                stdout_truncated=True,
                stderr_truncated=False,
            ),
        )
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = ShellExecTool().execute(command="unbounded output")

        assert result.success is False
        assert result.metadata["output_limited"] is True
        assert result.metadata["stdout_truncated"] is True

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires the compiled Rust extension",
    )
    def test_native_continuous_output_is_stopped_at_combined_budget(self):
        command = (
            "for /L %i in (1,1,2147483647) do @echo x"
            if os.name == "nt"
            else "while :; do printf x; done"
        )
        started = time.monotonic()
        result = ShellExecTool().execute(command=command, timeout=30)

        assert time.monotonic() - started < 5
        assert result.success is False
        assert result.metadata["output_limited"] is True
        assert result.metadata["timed_out"] is False
        assert (
            result.metadata["stdout_truncated"] or result.metadata["stderr_truncated"]
        )

    def test_no_output(self):
        """Rust always returns the format string even when stdout/stderr are empty."""
        mock_mod = _make_mock_rust(
            return_value=_rust_output(),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="true")
        assert result.success is True
        assert "Exit code: 0" in result.content
        assert "--- stdout ---" in result.content
        assert "--- stderr ---" in result.content

    def test_tool_id(self):
        tool = ShellExecTool()
        assert tool.tool_id == "shell_exec"

    def test_to_openai_function(self):
        tool = ShellExecTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "shell_exec"
        assert "command" in fn["function"]["parameters"]["properties"]

    def test_default_timeout_metadata(self):
        mock_mod = _make_mock_rust(
            return_value=_rust_output(stdout="ok\n"),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="echo ok")
        assert result.metadata["timeout_used"] == 30

    def test_structured_result_metadata(self):
        result_obj = _rust_output(code=7, stderr_truncated=True)
        mock_mod = _make_mock_rust(return_value=result_obj)
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = ShellExecTool().execute(command="exit 7", timeout=4)
        assert result.success is False
        assert result.metadata["returncode"] == 7
        assert result.metadata["stderr_truncated"] is True
        mock_mod.ShellExecTool.return_value.execute.assert_called_once_with(
            "exit 7", None, 4
        )

    def test_unicode_output(self):
        mock_mod = _make_mock_rust(return_value=_rust_output(stdout="héllo 世界\n"))
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = ShellExecTool().execute(command="echo unicode")
        assert "héllo 世界" in result.content

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires the compiled Rust extension",
    )
    def test_native_rust_python_integration(self, monkeypatch):
        marker = "OPENJARVIS_WP2_INTEGRATION_DUMMY_SECRET"
        monkeypatch.setenv(marker, "dummy-not-a-real-secret")
        command = (
            f"echo %{marker}%" if os.name == "nt" else f"printf '%s' \"${marker}\""
        )
        hidden = ShellExecTool().execute(command=command)
        assert hidden.success is True
        assert "dummy-not-a-real-secret" not in hidden.content
        assert hidden.metadata["returncode"] == 0

        nonzero_command = "exit /b 42" if os.name == "nt" else "exit 42"
        failed = ShellExecTool().execute(command=nonzero_command)
        assert failed.success is False
        assert failed.metadata["returncode"] == 42

    def test_rust_exception_sets_failure(self):
        """When the Rust backend raises an exception, Python sets success=False."""
        mock_mod = _make_mock_rust(
            side_effect=RuntimeError("Failed to execute: No such file or directory"),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="/nonexistent_binary")
        assert result.success is False
        assert result.metadata["returncode"] == -1


def test_native_backend_unavailable_fails_closed_without_execution():
    with (
        patch(
            "openjarvis._rust_bridge.get_rust_module",
            side_effect=ImportError("native extension unavailable"),
        ),
        patch("subprocess.run") as fallback_run,
    ):
        result = ShellExecTool().execute(command="echo SHOULD_NOT_RUN", timeout=7)

    assert result.success is False
    assert "command was not executed" in result.content
    assert result.metadata == {
        "returncode": -1,
        "timeout_used": 7,
        "working_dir": None,
        "timed_out": False,
        "output_limited": False,
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    fallback_run.assert_not_called()
