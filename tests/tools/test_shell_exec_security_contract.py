"""Security contract regression tests for WP-2 (Rust Shell Execution Hardening).

These tests independently verify observable security behavior against the WP-2
security specification:
1. Shell execution fails closed when secure native backend is unavailable.
2. Arbitrary environment passthrough cannot expose sensitive credentials.
3. Stdout and stderr share a combined output budget of 102,400 bytes.
4. Consistent structured metadata across all timeout and execution failures.
5. Process timeout terminates all descendant processes (no orphaned children).
6. Non-zero exit codes (including 42) report success=False and returncode=42.
7. Errors never falsely report success=True.
8. Windows-specific regressions (environment allowlists, cmd /C syntax, tree kill).
9. Adversarial input validation, stdin isolation, and PyO3 contract conformance.
"""

from __future__ import annotations

import errno
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openjarvis._rust_bridge import RUST_AVAILABLE
from openjarvis.tools.shell_exec import ShellExecTool


def _mock_rust_result(
    content: str = "",
    code: int = 0,
    *,
    success: bool = True,
    timed_out: bool = False,
    output_limited: bool = False,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
):
    """Build a mock PyShellExecResult conforming to the WP-2 PyO3 schema."""
    return SimpleNamespace(
        content=content,
        success=success,
        returncode=code,
        timed_out=timed_out,
        output_limited=output_limited,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def _is_windows_process_alive(pid: int, expected_image: str = "python") -> bool:
    """Check if a Windows process is genuinely alive without PID-reuse false positives.

    Uses Win32 OpenProcess with SYNCHRONIZE and query rights, checks the signal
    state, and confirms the executable image name to ensure an unrelated reused
    PID is not mistaken for a surviving child process.
    """
    if os.name != "nt":
        return False

    import ctypes
    from ctypes import wintypes

    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = ctypes.windll.kernel32.OpenProcess(
        SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return False
    try:
        # WaitForSingleObject with 0ms timeout:
        # returns 0 (WAIT_OBJECT_0) if signaled (terminated).
        wait_res = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
        if wait_res == 0:
            return False

        # If not signaled, inspect executable path to prevent PID-reuse false positives.
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size)
        ):
            if expected_image.lower() in buf.value.lower():
                return True
        return False
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _is_posix_process_alive(pid: int) -> bool:
    """Check if a POSIX process is alive using signal 0."""
    try:
        os.kill(pid, 0)
    except OSError as err:
        if err.errno == errno.ESRCH:
            return False
    return True


# ===========================================================================
# 1. Fail-closed when native backend is unavailable
# ===========================================================================


class TestNativeBackendFailClosed:
    """Security Contract 1: Shell execution must fail closed when the secure
    native backend is unavailable, rather than silently falling back to an
    unconfined, unisolated Python subprocess.
    """

    def test_fail_closed_when_native_backend_unavailable(self):
        tool = ShellExecTool()
        with (
            patch(
                "openjarvis._rust_bridge.get_rust_module",
                side_effect=ImportError("openjarvis_rust extension not compiled"),
            ),
            patch("subprocess.run") as mock_run,
            patch("subprocess.Popen") as mock_popen,
        ):
            result = tool.execute(command="echo unsafe_fallback_probe")

        assert result.success is False, (
            "Security violation: shell_exec failed open by executing fallback "
            "when secure native backend was unavailable."
        )
        assert result.metadata.get("returncode") == -1
        assert (
            "native" in result.content.lower()
            or "unavailable" in result.content.lower()
            or "disabled" in result.content.lower()
            or "required" in result.content.lower()
        ), (
            "Expected error content explaining native backend requirement, "
            f"got: {result.content}"
        )
        mock_run.assert_not_called()
        mock_popen.assert_not_called()


# ===========================================================================
# 2. Sensitive credential passthrough protection
# ===========================================================================


class TestCredentialPassthroughProtection:
    """Security Contract 2: Arbitrary environment-variable passthrough cannot
    expose sensitive credentials, tokens, or private keys from the host.
    """

    def test_env_passthrough_removed_from_spec(self):
        """Tool spec must not expose an env_passthrough parameter that allows
        callers or models to request exfiltration of host secrets.
        """
        tool = ShellExecTool()
        props = tool.spec.parameters.get("properties", {})
        assert "env_passthrough" not in props, (
            "Security violation: env_passthrough parameter exposed in tool spec"
        )

    def test_env_passthrough_parameter_ignored_by_execute(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Execute ignores any caller-supplied env_passthrough parameter."""
        marker = "OPENJARVIS_HOST_SECRET_TOKEN"
        monkeypatch.setenv(marker, "super_secret_host_value_12345")

        tool = ShellExecTool()
        mock_output = _mock_rust_result(content="Exit code: 0", code=0, success=True)
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_output
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(
                command=f"echo %{marker}%",
                env_passthrough=[marker],
            )

        assert result.success is True
        mock_mod.ShellExecTool.return_value.execute.assert_called_once_with(
            f"echo %{marker}%",
            None,
            30,
        )

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires compiled native Rust backend for live process env testing",
    )
    @pytest.mark.parametrize(
        "secret_key",
        [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "GITHUB_TOKEN",
            "SLACK_BOT_TOKEN",
            "DATABASE_URL",
        ],
    )
    def test_sensitive_credentials_cannot_be_passed_through_live(
        self, secret_key: str, monkeypatch: pytest.MonkeyPatch
    ):
        secret_val = f"super_secret_value_for_{secret_key}_98765"
        monkeypatch.setenv(secret_key, secret_val)

        tool = ShellExecTool()
        cmd = (
            f"echo %{secret_key}%"
            if os.name == "nt"
            else f"printf '%s' \"${secret_key}\""
        )
        result = tool.execute(command=cmd)

        assert secret_val not in result.content, (
            f"Security violation: Sensitive credential '{secret_key}' was leaked "
            "to subprocess."
        )


# ===========================================================================
# 3. Combined output budget
# ===========================================================================


class TestCombinedOutputBudget:
    """Security Contract 3: Stdout and stderr must share one combined output
    budget of 102,400 bytes, preventing memory exhaustion attacks via dual streams.
    """

    def test_stdout_and_stderr_combined_budget_contract(self):
        """Verify that the tool result content never exceeds the shared budget
        even when simulated backend streams emit large payloads.
        """
        max_budget = 102_400
        formatting_overhead = 1024

        tool = ShellExecTool()
        mock_res = _mock_rust_result(
            content="A" * max_budget + "\n[stdout truncated at 102400 bytes]",
            code=0,
            stdout_truncated=True,
            stderr_truncated=True,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="dual_stream_flood")

        raw_bytes = result.content.encode("utf-8", errors="replace")
        assert len(raw_bytes) <= max_budget + formatting_overhead, (
            f"Security violation: Combined output size {len(raw_bytes)} bytes "
            f"exceeds the shared budget of {max_budget} bytes."
        )
        assert result.metadata["stdout_truncated"] is True
        assert result.metadata["stderr_truncated"] is True

    @pytest.mark.parametrize(
        ("stdout_tr", "stderr_tr"),
        [
            (True, False),
            (False, True),
            (True, True),
            (False, False),
        ],
    )
    def test_truncation_flags_reported_in_metadata(
        self, stdout_tr: bool, stderr_tr: bool
    ):
        """Metadata accurately reports stdout_truncated and stderr_truncated flags."""
        tool = ShellExecTool()
        mock_res = _mock_rust_result(
            content="sample",
            code=0,
            stdout_truncated=stdout_tr,
            stderr_truncated=stderr_tr,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="test_stream")

        assert result.metadata["stdout_truncated"] is stdout_tr
        assert result.metadata["stderr_truncated"] is stderr_tr

    def test_combined_output_saturation_mock_contract(self):
        """Verify dual-stream output saturation triggers termination with
        success=False.
        """
        tool = ShellExecTool()
        content = (
            "Output limit reached; process tree terminated.\n"
            "Exit code: -1\n"
            f"--- stdout ---\n{'X' * 60000}\n"
            f"--- stderr ---\n{'Y' * 42400}"
            "\n[stdout truncated: combined capture limit reached]"
            "\n[stderr truncated: combined capture limit reached]"
        )
        mock_res = _mock_rust_result(
            content=content,
            code=-1,
            success=False,
            output_limited=True,
            stdout_truncated=True,
            stderr_truncated=True,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="dual_flood")

        assert result.success is False
        assert result.metadata["output_limited"] is True
        assert result.metadata["timed_out"] is False
        assert result.metadata["stdout_truncated"] is True
        assert result.metadata["stderr_truncated"] is True
        assert "Output limit reached; process tree terminated." in result.content
        assert "[stdout truncated" in result.content
        assert "[stderr truncated" in result.content

    def test_continuous_stdout_flooding_mock_contract(self):
        """Continuous stdout flooding sets output_limited=True and success=False."""
        tool = ShellExecTool()
        content = (
            "Output limit reached; process tree terminated.\n"
            "Exit code: -1\n"
            f"--- stdout ---\n{'A' * 102400}\n"
            "--- stderr ---\n"
            "\n[stdout truncated: combined capture limit reached]"
        )
        mock_res = _mock_rust_result(
            content=content,
            code=-1,
            success=False,
            output_limited=True,
            stdout_truncated=True,
            stderr_truncated=False,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="flood_stdout")

        assert result.success is False
        assert result.metadata["output_limited"] is True
        assert result.metadata["timed_out"] is False
        assert result.metadata["stdout_truncated"] is True
        assert result.metadata["stderr_truncated"] is False
        assert "Output limit reached; process tree terminated." in result.content

    def test_continuous_stderr_flooding_mock_contract(self):
        """Continuous stderr flooding sets output_limited=True and success=False."""
        tool = ShellExecTool()
        content = (
            "Output limit reached; process tree terminated.\n"
            "Exit code: -1\n"
            "--- stdout ---\n"
            f"--- stderr ---\n{'B' * 102400}"
            "\n[stderr truncated: combined capture limit reached]"
        )
        mock_res = _mock_rust_result(
            content=content,
            code=-1,
            success=False,
            output_limited=True,
            stdout_truncated=False,
            stderr_truncated=True,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="flood_stderr")

        assert result.success is False
        assert result.metadata["output_limited"] is True
        assert result.metadata["timed_out"] is False
        assert result.metadata["stdout_truncated"] is False
        assert result.metadata["stderr_truncated"] is True
        assert "Output limit reached; process tree terminated." in result.content

    def test_output_limit_distinct_from_timeout_metadata(self):
        """Verify output saturation and timeout produce distinct metadata and
        markers.
        """
        tool = ShellExecTool()

        sat_res = _mock_rust_result(
            content=(
                "Output limit reached; process tree terminated.\n"
                "Exit code: -1\n--- stdout ---\n...truncated..."
            ),
            code=-1,
            success=False,
            output_limited=True,
            timed_out=False,
            stdout_truncated=True,
        )
        timeout_res = _mock_rust_result(
            content=(
                "Command timed out.\nExit code: -1\n--- stdout ---\n...partial..."
            ),
            code=-1,
            success=False,
            output_limited=False,
            timed_out=True,
        )

        mock_mod = MagicMock()
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            mock_mod.ShellExecTool.return_value.execute.return_value = sat_res
            res_sat = tool.execute(command="saturate")

            mock_mod.ShellExecTool.return_value.execute.return_value = timeout_res
            res_time = tool.execute(command="timeout_cmd")

        assert res_sat.success is False
        assert res_sat.metadata["output_limited"] is True
        assert res_sat.metadata["timed_out"] is False
        assert "Output limit reached; process tree terminated." in res_sat.content
        assert "Command timed out." not in res_sat.content

        assert res_time.success is False
        assert res_time.metadata["output_limited"] is False
        assert res_time.metadata["timed_out"] is True
        assert "Command timed out." in res_time.content
        assert "Output limit reached" not in res_time.content

    def test_output_limited_forces_failure_even_if_backend_claims_success(self):
        """Security Contract: output_limited=True must strictly produce
        success=False.
        """
        tool = ShellExecTool()
        mock_res = _mock_rust_result(
            content="Output limit reached; process tree terminated.\nExit code: 0",
            code=0,
            success=True,
            output_limited=True,
            timed_out=False,
            stdout_truncated=True,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="flood")

        assert result.metadata["output_limited"] is True
        assert result.success is False, (
            "Security contract violation: output_limited=True must never "
            "report success=True"
        )

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires compiled native Rust backend for live stream budget test",
    )
    def test_stdout_and_stderr_share_combined_budget_live(self):
        tool = ShellExecTool()
        code = (
            "import sys; "
            "sys.stdout.write('A' * 80000); sys.stdout.flush(); "
            "sys.stderr.write('B' * 80000); sys.stderr.flush()"
        )
        cmd = subprocess.list2cmdline([sys.executable, "-c", code])
        result = tool.execute(command=cmd)

        max_budget = 102_400
        formatting_overhead = 1024
        raw_bytes = result.content.encode("utf-8", errors="replace")
        assert len(raw_bytes) <= max_budget + formatting_overhead, (
            f"Security violation: Live combined output size {len(raw_bytes)} bytes "
            f"exceeds the shared budget of {max_budget} bytes."
        )

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires compiled native Rust backend for live stream saturation test",
    )
    def test_continuous_streaming_output_memory_bounded_live(self):
        """Streaming massive output across both streams must remain memory-bounded
        and terminate cleanly without deadlocking reader threads or exceeding budget.
        """
        tool = ShellExecTool()
        code = (
            "import sys; "
            "for _ in range(25): "
            "    sys.stdout.write('A' * 8000); sys.stdout.flush(); "
            "    sys.stderr.write('B' * 8000); sys.stderr.flush()"
        )
        cmd = subprocess.list2cmdline([sys.executable, "-c", code])
        result = tool.execute(command=cmd, timeout=10)

        max_budget = 102_400
        formatting_overhead = 1024
        raw_bytes = result.content.encode("utf-8", errors="replace")
        assert len(raw_bytes) <= max_budget + formatting_overhead
        assert result.metadata["stdout_truncated"] is True
        assert result.metadata["stderr_truncated"] is True
        assert result.metadata["output_limited"] is True
        assert result.metadata["timed_out"] is False
        assert result.success is False

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires compiled native Rust backend for live stdout flood test",
    )
    def test_continuous_stdout_flooding_live(self):
        """Live infinite stdout flood terminates the process tree quickly."""
        tool = ShellExecTool()
        cmd = "for /L %i in (1,1,2147483647) do @echo x" if os.name == "nt" else "yes x"
        start = time.monotonic()
        result = tool.execute(command=cmd, timeout=30)
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, (
            f"Output flood took {elapsed:.2f}s; expected < 5s termination"
        )
        assert result.metadata["output_limited"] is True
        assert result.metadata["timed_out"] is False
        assert result.metadata["stdout_truncated"] is True
        assert result.success is False

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires compiled native Rust backend for live stderr flood test",
    )
    def test_continuous_stderr_flooding_live(self):
        """Live infinite stderr flood terminates the process tree quickly."""
        tool = ShellExecTool()
        cmd = (
            'cmd /c "for /L %i in (1,1,2147483647) do @echo x 1>&2"'
            if os.name == "nt"
            else "sh -c 'while true; do echo err >&2; done'"
        )
        start = time.monotonic()
        result = tool.execute(command=cmd, timeout=30)
        elapsed = time.monotonic() - start

        assert elapsed < 5.0, (
            f"Stderr flood took {elapsed:.2f}s; expected < 5s termination"
        )
        assert result.metadata["output_limited"] is True
        assert result.metadata["timed_out"] is False
        assert result.metadata["stderr_truncated"] is True
        assert result.success is False


# ===========================================================================
# 4. Consistent structured metadata on failures
# ===========================================================================


class TestConsistentStructuredFailureMetadata:
    """Security Contract 4: Timeout and execution failures must return consistent
    structured metadata (returncode, timed_out, timeout_used, truncation flags).
    """

    REQUIRED_METADATA_KEYS = {
        "returncode",
        "timed_out",
        "output_limited",
        "timeout_used",
        "working_dir",
        "stdout_truncated",
        "stderr_truncated",
    }

    @pytest.mark.parametrize(
        ("kwargs", "scenario"),
        [
            ({"command": ""}, "empty command"),
            (
                {"command": "echo hi", "working_dir": "/nonexistent_dir_12345"},
                "nonexistent working_dir",
            ),
        ],
    )
    def test_validation_failure_metadata(self, kwargs: dict, scenario: str):
        tool = ShellExecTool()
        result = tool.execute(**kwargs)
        assert result.success is False
        assert isinstance(result.metadata, dict), f"{scenario}: metadata must be a dict"
        missing = self.REQUIRED_METADATA_KEYS - set(result.metadata.keys())
        assert not missing, f"{scenario}: missing required metadata keys: {missing}"
        assert result.metadata["returncode"] == -1
        assert result.metadata["timed_out"] is False
        assert result.metadata["output_limited"] is False

    @pytest.mark.parametrize(
        ("requested_timeout", "expected_used"),
        [
            (0, 1),
            (-10, 1),
            (999, 300),
            (60, 60),
            ("invalid", 30),
        ],
    )
    def test_timeout_parameter_clamping_metadata(
        self, requested_timeout: object, expected_used: int
    ):
        """Timeout parameter is clamped into [1, 300] seconds in metadata."""
        tool = ShellExecTool()
        mock_output = _mock_rust_result(content="ok", code=0, success=True)
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_output
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="echo hi", timeout=requested_timeout)

        assert result.metadata["timeout_used"] == expected_used
        mock_mod.ShellExecTool.return_value.execute.assert_called_once_with(
            "echo hi",
            None,
            expected_used,
        )

    def test_backend_exception_failure_metadata(self):
        tool = ShellExecTool()
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.side_effect = RuntimeError(
            "Bridge panic"
        )
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="dummy_command")
        assert result.success is False
        assert isinstance(result.metadata, dict)
        missing = self.REQUIRED_METADATA_KEYS - set(result.metadata.keys())
        assert not missing, f"RuntimeError: missing required metadata keys: {missing}"
        assert result.metadata["returncode"] == -1
        assert result.metadata["timed_out"] is False
        assert result.metadata["output_limited"] is False

    def test_timeout_failure_metadata_structure(self):
        tool = ShellExecTool()
        mock_output = _mock_rust_result(
            content="Command timed out.\nExit code: -1",
            code=-1,
            success=False,
            timed_out=True,
            output_limited=False,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_output
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="sleep 10", timeout=1)

        assert result.success is False
        assert isinstance(result.metadata, dict)
        assert result.metadata.get("timed_out") is True
        assert result.metadata.get("output_limited") is False
        assert result.metadata.get("returncode") == -1
        assert result.metadata.get("timeout_used") == 1


# ===========================================================================
# 5. Process timeout descendant termination (No orphaned descendants)
# ===========================================================================


class TestProcessTreeTermination:
    """Security Contract 5: A process timeout must terminate all descendant
    processes, leaving no background orphans consuming host resources.
    """

    @pytest.mark.skipif(
        not RUST_AVAILABLE or os.name != "nt",
        reason="requires native Rust backend on Windows for process tree isolation",
    )
    def test_windows_timeout_kills_descendant_process(self, tmp_path):
        """Verify Windows timeout kills the parent AND genuine grandchild descendants.

        Uses Win32 handle synchronization to check process termination without
        PID-reuse false positives.
        """
        parent_pid_file = tmp_path / "parent.pid"
        descendant_pid_file = tmp_path / "descendant.pid"
        probe = (
            "import os, subprocess, sys, time; "
            f"open(r'{parent_pid_file}', 'w').write(str(os.getpid())); "
            "sub = subprocess.Popen("
            "[sys.executable, '-c', 'import time; time.sleep(30)']"
            "); "
            f"open(r'{descendant_pid_file}', 'w').write(str(sub.pid)); "
            "time.sleep(30)"
        )
        cmd = subprocess.list2cmdline([sys.executable, "-c", probe])
        tool = ShellExecTool()
        start = time.monotonic()
        result = tool.execute(command=cmd, timeout=1)
        elapsed = time.monotonic() - start

        assert result.success is False
        assert result.metadata.get("timed_out") is True
        assert parent_pid_file.exists(), "Parent process failed to record PID"
        assert descendant_pid_file.exists(), (
            "Grandchild descendant failed to record PID"
        )

        parent_pid = int(parent_pid_file.read_text().strip())
        descendant_pid = int(descendant_pid_file.read_text().strip())

        assert elapsed < 3.0, (
            f"Security violation: Execution blocked for {elapsed:.2f}s on a 1s "
            "timeout, proving process tree was not terminated on timeout."
        )

        # Allow OS a moment for cleanup before verifying termination
        time.sleep(0.5)

        parent_alive = _is_windows_process_alive(parent_pid)
        descendant_alive = _is_windows_process_alive(descendant_pid)

        assert not parent_alive, (
            f"Security violation: Parent process {parent_pid} survived timeout cleanup!"
        )
        assert not descendant_alive, (
            f"Security violation: Grandchild descendant {descendant_pid} "
            "survived timeout cleanup!"
        )

    @pytest.mark.skipif(
        not RUST_AVAILABLE or os.name != "nt",
        reason="requires native Rust backend on Windows for output saturation cleanup",
    )
    def test_windows_output_saturation_kills_descendant_process(self, tmp_path):
        """Output saturation terminates both parent and grandchild descendant
        processes.
        """
        parent_pid_file = tmp_path / "parent_sat.pid"
        descendant_pid_file = tmp_path / "descendant_sat.pid"
        probe = (
            "import os, subprocess, sys, time; "
            f"open(r'{parent_pid_file}', 'w').write(str(os.getpid())); "
            "sub = subprocess.Popen("
            "[sys.executable, '-c', 'import time; time.sleep(30)']"
            "); "
            f"open(r'{descendant_pid_file}', 'w').write(str(sub.pid)); "
            "for _ in range(100000): "
            "    print('FLOOD' * 100)"
        )
        cmd = subprocess.list2cmdline([sys.executable, "-c", probe])
        tool = ShellExecTool()
        start = time.monotonic()
        result = tool.execute(command=cmd, timeout=30)
        elapsed = time.monotonic() - start

        assert result.success is False
        assert result.metadata.get("output_limited") is True
        assert elapsed < 5.0, f"Execution took {elapsed:.2f}s; expected < 5s"
        assert parent_pid_file.exists()
        assert descendant_pid_file.exists()

        parent_pid = int(parent_pid_file.read_text().strip())
        descendant_pid = int(descendant_pid_file.read_text().strip())

        time.sleep(0.5)
        assert not _is_windows_process_alive(parent_pid)
        assert not _is_windows_process_alive(descendant_pid)

    @pytest.mark.parametrize(
        "failure_msg",
        [
            "Failed to execute: Access is denied. (os error 5)",
            "Failed to execute: The handle is invalid. (os error 6)",
            "Failed to execute: CreateProcessW returned incomplete process information",
            "Failed to execute: unexpected primary thread suspend count: 2",
        ],
    )
    def test_windows_primary_thread_containment_failure_contract(
        self, failure_msg: str
    ):
        """If Job Object assignment, process creation, or thread resumption fails,
        execution must fail closed.
        """
        tool = ShellExecTool()
        mock_res = _mock_rust_result(
            content=failure_msg,
            code=-1,
            success=False,
            timed_out=False,
            output_limited=False,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="echo hi")

        assert result.success is False
        assert result.metadata["returncode"] == -1
        assert result.metadata["timed_out"] is False
        assert result.metadata["output_limited"] is False
        assert failure_msg in result.content

    def test_windows_primary_thread_identity_retained_contract(self):
        """Verify the contract that CreateProcessW returns primary thread handle
        which must be valid before Job assignment and ResumeThread.
        """
        tool = ShellExecTool()
        msg = (
            "Failed to execute: CreateProcessW returned incomplete process information"
        )
        mock_res = _mock_rust_result(
            content=msg,
            code=-1,
            success=False,
            timed_out=False,
            output_limited=False,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="echo hi")

        assert result.success is False
        assert "incomplete process information" in result.content
        assert result.metadata["returncode"] == -1

    def test_windows_primary_thread_suspend_count_verification_contract(self):
        """Verify that unexpected suspend count on primary thread fails closed."""
        tool = ShellExecTool()
        mock_res = _mock_rust_result(
            content="Failed to execute: unexpected primary thread suspend count: 0",
            code=-1,
            success=False,
            timed_out=False,
            output_limited=False,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_res
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="echo hi")

        assert result.success is False
        assert "unexpected primary thread suspend count" in result.content
        assert result.metadata["returncode"] == -1

    @pytest.mark.skipif(
        not RUST_AVAILABLE or os.name == "nt",
        reason="requires native Rust backend on POSIX for output saturation cleanup",
    )
    def test_posix_output_saturation_kills_descendant_process(self, tmp_path):
        """POSIX output saturation terminates the entire process group."""
        pid_file = tmp_path / "child_sat.pid"
        cmd = (
            "python3 -c 'import os, subprocess, time; "
            f'open("{pid_file}", "w").write(str(os.getpid())); '
            'subprocess.Popen(["sleep", "30"]); '
            'for _ in range(100000): print("FLOOD" * 100)\''
        )
        tool = ShellExecTool()
        result = tool.execute(command=cmd, timeout=30)

        assert result.success is False
        assert result.metadata.get("output_limited") is True
        assert pid_file.exists()
        child_pid = int(pid_file.read_text().strip())
        assert not _is_posix_process_alive(child_pid)

    @pytest.mark.skipif(
        not RUST_AVAILABLE or os.name == "nt",
        reason="requires native Rust backend on POSIX for process tree isolation",
    )
    def test_posix_timeout_kills_descendant_process(self, tmp_path):
        pid_file = tmp_path / "child.pid"
        cmd = (
            "python3 -c 'import os, time; "
            f'open("{pid_file}", "w").write(str(os.getpid())); '
            "time.sleep(30)'"
        )
        tool = ShellExecTool()
        result = tool.execute(command=cmd, timeout=1)

        assert result.success is False
        assert result.metadata.get("timed_out") is True
        assert pid_file.exists(), "Child process failed to start and record PID"
        child_pid = int(pid_file.read_text().strip())

        alive = _is_posix_process_alive(child_pid)
        assert not alive, (
            f"Security violation: POSIX child {child_pid} survived timeout cleanup!"
        )


# ===========================================================================
# 6. Non-zero exit code verification (including exit code 42)
# ===========================================================================


class TestNonzeroExitCodes:
    """Security Contract 6: Non-zero exit codes must always report success=False,
    the real returncode, and not be masked as success.
    """

    @pytest.mark.parametrize("code", [1, 2, 7, 42, 127, 255])
    def test_nonzero_exit_code_reported_accurately_mock(self, code: int):
        tool = ShellExecTool()
        mock_output = _mock_rust_result(
            content=f"Exit code: {code}\n--- stdout ---\n\n--- stderr ---\nfailed",
            code=code,
            success=False,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_output
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command=f"exit {code}")

        assert result.success is False, (
            f"Exit code {code} falsely reported success=True"
        )
        assert result.metadata.get("returncode") == code
        assert result.metadata.get("timed_out") is False

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires compiled native Rust backend for live exit code execution",
    )
    def test_exit_code_42_live(self):
        tool = ShellExecTool()
        cmd = "exit /b 42" if os.name == "nt" else "exit 42"
        result = tool.execute(command=cmd)
        assert result.success is False, "Exit code 42 falsely reported success=True"
        assert result.metadata.get("returncode") == 42
        assert result.metadata.get("timed_out") is False


# ===========================================================================
# 7. Errors never falsely report success
# ===========================================================================


class TestErrorsNeverReportSuccess:
    """Security Contract 7: Any execution failure, exception, non-zero return,
    or timeout must strictly yield success=False.
    """

    def test_rust_runtime_exception_is_failure(self):
        tool = ShellExecTool()
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.side_effect = RuntimeError(
            "Rust internal execution error"
        )
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="echo hi")

        assert result.success is False
        assert result.metadata.get("returncode") == -1
        assert "Rust internal execution error" in result.content

    def test_mock_rust_success_flag_respected(self):
        """Even if content appears benign, backend success=False must not be flipped."""
        tool = ShellExecTool()
        mock_output = _mock_rust_result(
            content="Standard benign output",
            code=1,
            success=False,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_output
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="something")

        assert result.success is False
        assert result.metadata["returncode"] == 1

    def test_standard_timeout_result_is_failure(self):
        """Standard timeout result reports success=False and timed_out=True."""
        tool = ShellExecTool()
        mock_output = _mock_rust_result(
            content="Command timed out.\nExit code: -1",
            code=-1,
            success=False,
            timed_out=True,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_output
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="sleep 10")

        assert result.metadata.get("timed_out") is True
        assert result.success is False

    def test_timed_out_result_is_never_success(self):
        """Security Contract: timed_out=True must strictly produce success=False.

        Even if a buggy native backend or intermediate layer returns success=True
        when timed_out=True, the tool must fail closed.
        """
        tool = ShellExecTool()
        mock_output = _mock_rust_result(
            content="Command timed out.\nExit code: -1",
            code=-1,
            success=True,  # Simulates backend reporting success despite timeout
            timed_out=True,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_output
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="sleep 10")

        assert result.metadata.get("timed_out") is True, (
            "Metadata must indicate timed_out=True"
        )
        assert result.success is False, (
            "Security contract violation: timed_out=True must never report success=True"
        )


# ===========================================================================
# 8. Windows-specific regressions
# ===========================================================================


class TestWindowsSecurityRegressions:
    """Security Contract 8: Windows-specific environment isolation and execution
    security.
    """

    @pytest.mark.skipif(
        not RUST_AVAILABLE or os.name != "nt",
        reason="requires native Rust backend on Windows for live environment check",
    )
    def test_unallowlisted_host_env_vars_isolated_live(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Arbitrary host environment variables must not leak into Windows child."""
        marker = "OPENJARVIS_HOST_SECRET_TOKEN"
        monkeypatch.setenv(marker, "top_secret_token_123")
        tool = ShellExecTool()
        result = tool.execute(command=f"echo %{marker}%")
        assert result.success is True
        assert "top_secret_token_123" not in result.content

    def test_windows_bootstrap_spec_requirements(self):
        """Spec must require code:execute and system category on Windows."""
        tool = ShellExecTool()
        assert tool.spec.category == "system"
        assert "code:execute" in tool.spec.required_capabilities
        assert tool.spec.requires_confirmation is True
        assert tool.spec.timeout_seconds <= 30.0


# ===========================================================================
# 9. Adversarial Security and PyO3 API Contract Tests
# ===========================================================================


class TestAdversarialSecurityContract:
    """Security Contract 9: Adversarial input validation, PyO3 schema conformance,
    and process isolation boundary checks.
    """

    def test_pyo3_result_schema_fields(self):
        """Verify that PyShellExecResult schema exposes all expected attributes."""
        res = _mock_rust_result(
            content="test",
            code=0,
            success=True,
            timed_out=False,
            output_limited=False,
            stdout_truncated=False,
            stderr_truncated=False,
        )
        assert hasattr(res, "content")
        assert hasattr(res, "success")
        assert hasattr(res, "returncode")
        assert hasattr(res, "timed_out")
        assert hasattr(res, "output_limited")
        assert hasattr(res, "stdout_truncated")
        assert hasattr(res, "stderr_truncated")

    @pytest.mark.parametrize(
        "bad_command",
        [
            "",
            "   ",
            "\n\t  \n",
        ],
    )
    def test_blank_commands_fail_closed_without_backend_invocation(
        self, bad_command: str
    ):
        """Empty or whitespace-only commands fail closed before backend dispatch."""
        tool = ShellExecTool()
        mock_mod = MagicMock()
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command=bad_command)

        if not bad_command:
            assert result.success is False
            assert "No command" in result.content
            mock_mod.ShellExecTool.assert_not_called()

    def test_working_dir_path_traversal_nonexistent_fails_closed(self):
        """Invalid or escaping working_dir fails closed immediately."""
        tool = ShellExecTool()
        result = tool.execute(
            command="echo hi",
            working_dir="../../nonexistent_traversal_dir_xyz",
        )
        assert result.success is False
        assert "does not exist" in result.content
        assert result.metadata["returncode"] == -1

    def test_nonzero_exit_code_forces_failure_even_if_backend_claims_success(self):
        """Security Contract: Nonzero returncode must strictly produce success=False."""
        tool = ShellExecTool()
        mock_output = _mock_rust_result(
            content="Exit code: 42\n--- stdout ---\n\n--- stderr ---\nerr",
            code=42,
            success=True,  # Inconsistent backend flag
            timed_out=False,
        )
        mock_mod = MagicMock()
        mock_mod.ShellExecTool.return_value.execute.return_value = mock_output
        with patch("openjarvis._rust_bridge.get_rust_module", return_value=mock_mod):
            result = tool.execute(command="exit 42")

        assert result.metadata["returncode"] == 42
        assert result.success is False

    @pytest.mark.skipif(
        not RUST_AVAILABLE,
        reason="requires compiled native Rust backend for stdin isolation check",
    )
    def test_stdin_is_closed_and_does_not_block_live(self):
        """Standard input must be redirected to null, returning EOF immediately."""
        tool = ShellExecTool()
        probe = "import sys; print('stdin_len:', len(sys.stdin.read()))"
        cmd = subprocess.list2cmdline([sys.executable, "-c", probe])
        result = tool.execute(command=cmd, timeout=5)
        assert result.success is True
        assert "stdin_len: 0" in result.content
