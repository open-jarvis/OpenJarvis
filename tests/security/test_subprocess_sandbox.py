"""Tests for subprocess sandbox — secure process execution."""

from __future__ import annotations

import os
import tempfile

from openjarvis.security.subprocess_sandbox import (
    build_safe_env,
    kill_process_tree,
    run_sandboxed,
)

# ---------------------------------------------------------------------------
# build_safe_env tests
# ---------------------------------------------------------------------------


class TestBuildSafeEnv:
    def test_only_safe_vars_included(self) -> None:
        env = build_safe_env()
        # All keys should be from the safe set
        safe_keys = {
            "PATH",
            "HOME",
            "USER",
            "LANG",
            "TERM",
            "SHELL",
            "LC_ALL",
            "LC_CTYPE",
            "TMPDIR",
            "TZ",
        }
        for key in env:
            assert key in safe_keys

    def test_passthrough_works(self) -> None:
        os.environ["MY_CUSTOM_VAR_FOR_TEST"] = "hello"
        try:
            env = build_safe_env(passthrough=["MY_CUSTOM_VAR_FOR_TEST"])
            assert env.get("MY_CUSTOM_VAR_FOR_TEST") == "hello"
        finally:
            del os.environ["MY_CUSTOM_VAR_FOR_TEST"]

    def test_extra_vars_added(self) -> None:
        env = build_safe_env(extra={"FOO": "bar", "BAZ": "qux"})
        assert env["FOO"] == "bar"
        assert env["BAZ"] == "qux"

    def test_unknown_env_var_excluded(self) -> None:
        os.environ["SUPER_SECRET_KEY_XYZ"] = "secret"
        try:
            env = build_safe_env()
            assert "SUPER_SECRET_KEY_XYZ" not in env
        finally:
            del os.environ["SUPER_SECRET_KEY_XYZ"]


# ---------------------------------------------------------------------------
# run_sandboxed tests
# ---------------------------------------------------------------------------


class TestRunSandboxed:
    def test_simple_echo(self) -> None:
        result = run_sandboxed("echo hello", timeout=10.0)
        assert result.returncode == 0
        assert "hello" in result.stdout
        assert not result.timed_out
        assert not result.killed

    def test_timeout_kills_process(self) -> None:
        result = run_sandboxed("sleep 60", timeout=1.0)
        assert result.timed_out
        assert result.killed
        assert result.returncode == -1

    def test_working_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_sandboxed("pwd", working_dir=tmpdir, timeout=10.0)
            assert result.returncode == 0
            assert tmpdir in result.stdout.strip()

    def test_env_isolation(self) -> None:
        os.environ["TEST_SECRET"] = "super_secret_value"
        try:
            result = run_sandboxed(
                'echo "val=$TEST_SECRET"',
                timeout=10.0,
            )
            assert result.returncode == 0
            assert "super_secret_value" not in result.stdout
        finally:
            del os.environ["TEST_SECRET"]

    def test_output_truncation(self) -> None:
        # Generate output larger than max_output_bytes
        result = run_sandboxed(
            "python3 -c \"print('A' * 200)\"",
            timeout=10.0,
            max_output_bytes=50,
        )
        assert result.returncode == 0
        assert len(result.stdout) <= 50

    def test_non_zero_exit_code(self) -> None:
        result = run_sandboxed("exit 42", timeout=10.0)
        assert result.returncode == 42
        assert not result.timed_out


# ---------------------------------------------------------------------------
# kill_process_tree tests
# ---------------------------------------------------------------------------


class TestKillProcessTree:
    def test_no_crash_on_nonexistent_pid(self) -> None:
        # Should not raise on a PID that doesn't exist
        kill_process_tree(999999999)
