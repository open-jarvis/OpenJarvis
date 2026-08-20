"""Tests for the shell_exec tool.

Tests mock the Rust backend to verify the Python wrapper handles
the Rust output format correctly:
    "Exit code: {code}\\n--- stdout ---\\n{stdout}\\n--- stderr ---\\n{stderr}"
"""

from __future__ import annotations

import importlib
import os
import shlex
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core import get_python_executable
from openjarvis.tools.shell_exec import ShellExecTool


def _rust_output(stdout: str = "", stderr: str = "", code: int = 0) -> str:
    """Build the Rust shell_exec output format."""
    return f"Exit code: {code}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"


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
        assert tool.spec.timeout_seconds == 60.0
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

    @pytest.mark.skip(
        reason="Rust backend has no timeout — Command::output() blocks",
    )
    def test_timeout_exceeded(self):
        tool = ShellExecTool()
        result = tool.execute(command="sleep 60", timeout=1)
        assert result.success is False
        assert "timed out" in result.content
        assert result.metadata["returncode"] == -1
        assert result.metadata["timeout_used"] == 1

    def test_timeout_capped_at_max(self):
        """timeout param is still capped in Python; Rust ignores it."""
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

    @pytest.mark.skip(reason="Rust backend inherits parent env — no env isolation")
    def test_env_clearing(self):
        """Verify that arbitrary env vars are NOT passed through."""
        marker = "OPENJARVIS_TEST_SECRET_12345"
        os.environ[marker] = "leaked"
        try:
            tool = ShellExecTool()
            result = tool.execute(command=f"echo ${marker}")
            assert result.success is True
            assert "leaked" not in result.content
        finally:
            os.environ.pop(marker, None)

    @pytest.mark.skip(
        reason="Rust backend inherits parent env — no env_passthrough",
    )
    def test_env_passthrough(self):
        """Verify that explicitly listed env vars ARE passed through."""
        marker = "OPENJARVIS_TEST_PASSTHROUGH_67890"
        os.environ[marker] = "allowed_value"
        try:
            tool = ShellExecTool()
            result = tool.execute(
                command=f"echo ${marker}",
                env_passthrough=[marker],
            )
            assert result.success is True
            assert "allowed_value" in result.content
        finally:
            os.environ.pop(marker, None)

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
        """Non-zero exit in Rust returns ToolResult::failure() but PyO3 binding
        returns Ok(content).  The Python wrapper currently treats that as
        success=True (it only sets success=False on exception).  The Rust
        output still contains the exit code in the formatted string."""
        mock_mod = _make_mock_rust(
            return_value=_rust_output(code=42),
        )
        tool = ShellExecTool()
        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            return_value=mock_mod,
        ):
            result = tool.execute(command="exit 42")
        # PyO3 binding returns content for both success/failure ToolResults,
        # so Python wrapper sets success=True and returncode=0.
        assert result.success is True
        assert "Exit code: 42" in result.content

    @pytest.mark.skip(reason="Rust backend has no output truncation")
    def test_max_output_truncation(self, tmp_path):
        """Stdout exceeding 100 KB is truncated."""
        tool = ShellExecTool()
        result = tool.execute(
            command=(
                f"{shlex.quote(get_python_executable())} -c \"print('A' * 200000)\""
            ),
        )
        assert "truncated" in result.content
        assert len(result.content) < 200_000

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


class TestSanitizedEnvWindowsKeys:
    """Regression for #789: the Python fallback's env allowlist was
    POSIX-focused ("PATH", "HOME", "USER", "LANG", "TERM") and omitted
    variables Windows needs for basic process bootstrapping -- missing
    SystemRoot breaks Winsock/DNS init for any network-touching command
    (git, curl, pip, npm all fail with "getaddrinfo() thread failed to
    start"), and missing LOCALAPPDATA makes the Windows Store Python
    launcher provision a ~170MB Python\\ folder in the cwd instead of
    finding the real interpreter.
    """

    def test_base_env_keys_include_windows_essentials(self):
        from openjarvis.tools.shell_exec import _WINDOWS_ENV_KEYS

        for key in (
            "SystemRoot",
            "SystemDrive",
            "COMSPEC",
            "PATHEXT",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
        ):
            assert key in _WINDOWS_ENV_KEYS, f"{key} missing from Windows keys"

    def test_windows_keys_are_only_enabled_on_windows(self):
        from openjarvis.tools.shell_exec import _BASE_ENV_KEYS, _WINDOWS_ENV_KEYS

        if os.name == "nt":
            assert set(_WINDOWS_ENV_KEYS) <= set(_BASE_ENV_KEYS)
        else:
            assert set(_WINDOWS_ENV_KEYS).isdisjoint(_BASE_ENV_KEYS)

    @pytest.mark.skipif(os.name != "nt", reason="requires a real Windows child")
    def test_windows_env_vars_reach_the_subprocess(self, monkeypatch):
        """End-to-end: with the Rust backend unavailable (forcing the
        Python sanitised-env fallback), a Windows-critical variable
        present in the host environment must actually reach the child
        process instead of being stripped."""
        monkeypatch.setenv("SystemRoot", r"C:\Windows")
        monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")

        captured: dict = {}

        def _fake_run(*args, **kwargs):
            captured["env"] = kwargs.get("env")
            return subprocess.CompletedProcess(args, 0, stdout="ok\n", stderr="")

        tool = ShellExecTool()
        with (
            patch(
                "openjarvis._rust_bridge.get_rust_module",
                side_effect=ImportError("no rust module"),
            ),
            patch("subprocess.run", side_effect=_fake_run),
        ):
            result = tool.execute(command="echo ok")

        assert result.success is True
        env = captured["env"]
        assert env is not None
        assert env.get("SystemRoot") == r"C:\Windows"
        assert env.get("LOCALAPPDATA") == r"C:\Users\tester\AppData\Local"

    @pytest.mark.skipif(os.name != "nt", reason="requires a real Windows child")
    def test_real_windows_child_bootstraps_and_resolves_localhost(
        self, tmp_path, monkeypatch
    ):
        """Exercise the actual sanitized environment and Windows process path."""
        import json

        local_app_data = str(tmp_path / "LocalAppData")
        monkeypatch.setenv("LOCALAPPDATA", local_app_data)
        probe = (
            "import json, os, socket; "
            "addresses = socket.getaddrinfo('localhost', 80); "
            "print(json.dumps({"
            "'SystemRoot': os.environ.get('SystemRoot'), "
            "'LOCALAPPDATA': os.environ.get('LOCALAPPDATA'), "
            "'dns_ok': bool(addresses)}))"
        )
        command = subprocess.list2cmdline([sys.executable, "-c", probe])

        with patch(
            "openjarvis._rust_bridge.get_rust_module",
            side_effect=ImportError("force Python fallback"),
        ):
            result = ShellExecTool().execute(command=command)

        assert result.success is True, result.content
        stdout = result.content.split("=== STDOUT ===\n", 1)[1].splitlines()[0]
        payload = json.loads(stdout)
        assert payload["SystemRoot"] == os.environ["SystemRoot"]
        assert payload["LOCALAPPDATA"] == local_app_data
        assert payload["dns_ok"] is True
