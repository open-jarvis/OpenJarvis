"""Tests for the shell_exec tool.

Most tests run real commands through the subprocess path. A mocked Rust
extension is only used to check that it is NOT called: the Rust
ShellExecTool has no timeout, env allowlist or exit code yet (#1332).
"""

from __future__ import annotations

import importlib
import os
import shlex
import subprocess
import sys
import time
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


def _python_cmd(code: str) -> str:
    """Shell command that runs *code* with Python, quoted for sh or cmd."""
    args = [get_python_executable(), "-c", code]
    if os.name == "nt":
        return subprocess.list2cmdline(args)
    return shlex.join(args)


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
        tool = ShellExecTool()
        result = tool.execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.content
        assert "=== STDOUT ===" in result.content

    def test_capture_stderr(self):
        tool = ShellExecTool()
        result = tool.execute(command="echo error_msg >&2")
        assert "error_msg" in result.content
        assert "=== STDERR ===" in result.content

    def test_timeout_exceeded(self):
        tool = ShellExecTool()
        start = time.monotonic()
        result = tool.execute(
            command=_python_cmd("import time; time.sleep(30)"), timeout=1
        )
        assert time.monotonic() - start < 10
        assert result.success is False
        assert "timed out" in result.content
        assert result.metadata["returncode"] == -1
        assert result.metadata["timeout_used"] == 1

    def test_timeout_stops_a_descendant_before_it_can_write(self, tmp_path):
        marker = tmp_path / "after-timeout.txt"
        child = (
            "import time; from pathlib import Path; time.sleep(3); "
            f"Path({str(marker)!r}).write_text('should not run')"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
            "time.sleep(30)"
        )
        result = ShellExecTool().execute(command=_python_cmd(parent), timeout=1)
        assert result.success is False
        assert "timed out" in result.content
        time.sleep(3.2)
        assert not marker.exists()

    def test_timeout_capped_at_max(self):
        tool = ShellExecTool()
        result = tool.execute(command="echo ok", timeout=999)
        assert result.success is True
        assert result.metadata["timeout_used"] == 300

    def test_working_dir(self, tmp_path):
        tool = ShellExecTool()
        result = tool.execute(
            command=_python_cmd("import os; print(os.getcwd())"),
            working_dir=str(tmp_path),
        )
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

    def test_env_clearing(self):
        """Verify that arbitrary env vars are NOT passed through, also when
        the Rust extension is installed (it inherits the full env)."""
        marker = "OPENJARVIS_TEST_SECRET_12345"
        os.environ[marker] = "leaked"
        # what the Rust path printed for the same command before #1332
        mock_mod = _make_mock_rust(return_value=_rust_output(stdout="leaked\n"))
        try:
            tool = ShellExecTool()
            with patch(
                "openjarvis._rust_bridge.get_rust_module",
                return_value=mock_mod,
            ):
                result = tool.execute(
                    command=_python_cmd(
                        f"import os; print(os.environ.get('{marker}'))"
                    ),
                )
            assert result.success is True
            assert "leaked" not in result.content
        finally:
            os.environ.pop(marker, None)

    def test_env_passthrough(self):
        """Verify that explicitly listed env vars ARE passed through."""
        marker = "OPENJARVIS_TEST_PASSTHROUGH_67890"
        os.environ[marker] = "allowed_value"
        try:
            tool = ShellExecTool()
            result = tool.execute(
                command=_python_cmd(f"import os; print(os.environ.get('{marker}'))"),
                env_passthrough=[marker],
            )
            assert result.success is True
            assert "allowed_value" in result.content
        finally:
            os.environ.pop(marker, None)

    def test_returncode_in_metadata(self):
        tool = ShellExecTool()
        result = tool.execute(command="echo ok")
        assert result.success is True
        assert result.metadata["returncode"] == 0

    def test_nonzero_returncode(self):
        """The real exit code comes back even when the Rust extension is
        installed. The Rust path used to report success=True and
        returncode 0 for every command (#1332)."""
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

    def test_max_output_truncation(self, tmp_path):
        """Stdout exceeding 100 KB is truncated."""
        tool = ShellExecTool()
        result = tool.execute(command=_python_cmd("print('A' * 200000)"))
        assert "truncated" in result.content
        assert len(result.content) < 200_000

    def test_no_output(self):
        tool = ShellExecTool()
        result = tool.execute(command="exit 0")
        assert result.success is True
        assert result.content == "(no output)"

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
        tool = ShellExecTool()
        result = tool.execute(command="echo ok")
        assert result.metadata["timeout_used"] == 30


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

        tool = ShellExecTool()
        result = tool.execute(
            command=_python_cmd(
                "import os; print(os.environ['SystemRoot']); "
                "print(os.environ['LOCALAPPDATA'])"
            )
        )
        assert result.success is True
        assert r"C:\Windows" in result.content
        assert r"C:\Users\tester\AppData\Local" in result.content

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
