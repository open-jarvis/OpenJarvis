"""Tests for Apple FM shim and ``jarvis host apple-fm`` on macOS 15+."""

from __future__ import annotations

import platform
import subprocess
import sys
import time
from unittest import mock

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.cli.host_cmd import _BACKENDS, _build_serve_command

pytestmark = pytest.mark.apple


def _macos_version() -> tuple[int, int]:
    """Return (major, minor) macOS version, or (0, 0) if not darwin."""
    if platform.system() != "Darwin":
        return (0, 0)
    try:
        result = subprocess.run(
            ["sw_vers", "-productVersion"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return (0, 0)
        parts = result.stdout.strip().split(".")
        major = int(parts[0]) if parts else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        return (major, minor)
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        return (0, 0)


def _is_macos15_plus() -> bool:
    major, minor = _macos_version()
    return major >= 15


# ---------------------------------------------------------------------------
# Unit tests (run on any platform with apple marker)
# ---------------------------------------------------------------------------


class TestAppleFmBackend:
    """Unit tests for apple_fm backend configuration."""

    def test_apple_fm_in_backends(self) -> None:
        assert "apple_fm" in _BACKENDS
        info = _BACKENDS["apple_fm"]
        assert info["display"] == "Apple FM (Apple Silicon)"
        assert info["default_port"] == 8079
        assert info["platform"] == "darwin"

    def test_build_serve_command_apple_fm(self) -> None:
        cmd = _build_serve_command("apple_fm", "apple-fm", 8079)
        assert cmd[0] == sys.executable
        assert "uvicorn" in cmd
        assert "openjarvis.engine.apple_fm_shim:app" in cmd
        assert "8079" in cmd


class TestHostAppleFmCli:
    """CLI tests for jarvis host apple-fm."""

    @mock.patch("openjarvis.cli.host_cmd._is_package_available", return_value=True)
    @mock.patch("platform.system", return_value="Darwin")
    @mock.patch("openjarvis.cli.host_cmd.subprocess.Popen")
    def test_host_apple_fm_selects_backend_on_darwin(
        self, mock_popen: mock.MagicMock, mock_system: mock.MagicMock, mock_avail: mock.MagicMock
    ) -> None:
        """On darwin, jarvis host apple-fm uses Apple FM backend."""
        mock_popen.return_value.wait.return_value = 0
        runner = CliRunner()
        result = runner.invoke(cli, ["host", "apple-fm"])
        assert result.exit_code == 0
        assert "Apple FM" in result.output
        assert "8079" in result.output
        call_args = mock_popen.call_args[0][0]
        assert "uvicorn" in call_args
        assert "apple_fm_shim" in " ".join(call_args)


class TestHostAppleFmIntegration:
    """Integration test: jarvis host apple-fm on macOS 15+."""

    @pytest.mark.macos15
    @pytest.mark.skipif(
        platform.system() != "Darwin",
        reason="Apple FM only on macOS",
    )
    @pytest.mark.skipif(
        not _is_macos15_plus(),
        reason="Apple FM requires macOS 15+ (Sequoia)",
    )
    @pytest.mark.slow
    def test_jarvis_host_apple_fm_health(self) -> None:
        """Start Apple FM shim, hit /health, verify response."""
        try:
            import apple_fm_sdk  # noqa: F401
        except ImportError:
            pytest.skip("apple-fm-sdk not installed")

        proc = subprocess.Popen(
            [
                "uvicorn",
                "openjarvis.engine.apple_fm_shim:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8079",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            # Wait for server to start
            for _ in range(30):
                try:
                    import urllib.request

                    with urllib.request.urlopen(
                        "http://127.0.0.1:8079/health", timeout=2
                    ) as resp:
                        data = resp.read().decode()
                        assert "status" in data
                        break
                except OSError:
                    time.sleep(0.5)
            else:
                pytest.fail("Apple FM shim did not become ready in time")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
