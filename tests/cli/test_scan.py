"""Tests for ``jarvis scan`` privacy scanner CLI command."""

from __future__ import annotations

import json
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.cli.scan_cmd import ScanResult, PrivacyScanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> CompletedProcess:
    return CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# TestScanResultDataclass
# ---------------------------------------------------------------------------


class TestScanResultDataclass:
    def test_fields_exist(self) -> None:
        r = ScanResult(name="test", status="ok", message="all good", platform="all")
        assert r.name == "test"
        assert r.status == "ok"
        assert r.message == "all good"
        assert r.platform == "all"

    def test_status_values(self) -> None:
        for status in ("ok", "warn", "fail", "skip"):
            r = ScanResult(name="x", status=status, message="", platform="all")
            assert r.status == status

    def test_platform_values(self) -> None:
        for plat in ("darwin", "linux", "all"):
            r = ScanResult(name="x", status="ok", message="", platform=plat)
            assert r.platform == plat


# ---------------------------------------------------------------------------
# TestFileVault
# ---------------------------------------------------------------------------


class TestFileVault:
    def test_filevault_enabled(self) -> None:
        scanner = PrivacyScanner()
        with patch("subprocess.run", return_value=_make_proc(stdout="FileVault is On.")):
            result = scanner.check_filevault()
        assert result.status == "ok"

    def test_filevault_disabled(self) -> None:
        scanner = PrivacyScanner()
        with patch("subprocess.run", return_value=_make_proc(stdout="FileVault is Off.")):
            result = scanner.check_filevault()
        assert result.status == "fail"

    def test_command_not_found(self) -> None:
        scanner = PrivacyScanner()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = scanner.check_filevault()
        assert result.status == "skip"


# ---------------------------------------------------------------------------
# TestMDM
# ---------------------------------------------------------------------------


class TestMDM:
    def test_not_enrolled(self) -> None:
        scanner = PrivacyScanner()
        with patch(
            "subprocess.run",
            return_value=_make_proc(stdout="Enrolled via DEP: No\nMDM enrollment: not enrolled"),
        ):
            result = scanner.check_mdm()
        assert result.status == "ok"

    def test_enrolled(self) -> None:
        scanner = PrivacyScanner()
        with patch(
            "subprocess.run",
            return_value=_make_proc(stdout="MDM enrollment: Yes\nEnrolled via DEP: Yes"),
        ):
            result = scanner.check_mdm()
        assert result.status == "warn"


# ---------------------------------------------------------------------------
# TestCloudSync
# ---------------------------------------------------------------------------


class TestCloudSync:
    def test_no_agents(self) -> None:
        """pgrep returns non-zero (process not found) → no sync agents running."""
        scanner = PrivacyScanner()
        with patch("subprocess.run", return_value=_make_proc(returncode=1, stdout="")):
            result = scanner.check_cloud_sync_agents()
        assert result.status == "ok"

    def test_dropbox_running(self) -> None:
        """pgrep returns 0 when Dropbox is in the command."""
        scanner = PrivacyScanner()

        def _pgrep_side_effect(cmd, **kwargs):
            if "Dropbox" in cmd:
                return _make_proc(returncode=0, stdout="1234")
            return _make_proc(returncode=1, stdout="")

        with patch("subprocess.run", side_effect=_pgrep_side_effect):
            result = scanner.check_cloud_sync_agents()
        assert result.status == "warn"


# ---------------------------------------------------------------------------
# TestNetworkExposure
# ---------------------------------------------------------------------------


class TestNetworkExposure:
    def test_no_exposed_ports(self) -> None:
        """Only localhost bindings → ok."""
        scanner = PrivacyScanner()
        # lsof / ss output showing only 127.0.0.1
        lsof_output = "ollama  1234 user  IPv4  TCP 127.0.0.1:11434 (LISTEN)\n"
        with patch("subprocess.run", return_value=_make_proc(stdout=lsof_output)):
            result = scanner.check_network_exposure()
        assert result.status == "ok"

    def test_exposed_port(self) -> None:
        """A port bound to 0.0.0.0 or * → warn with port in message."""
        scanner = PrivacyScanner()
        lsof_output = "ollama  1234 user  IPv4  TCP *:11434 (LISTEN)\n"
        with patch("subprocess.run", return_value=_make_proc(stdout=lsof_output)):
            result = scanner.check_network_exposure()
        assert result.status == "warn"
        assert "11434" in result.message


# ---------------------------------------------------------------------------
# TestLUKS
# ---------------------------------------------------------------------------


class TestLUKS:
    def test_encrypted(self) -> None:
        """lsblk JSON contains crypto_LUKS → ok."""
        scanner = PrivacyScanner()
        lsblk_data = {
            "blockdevices": [
                {
                    "name": "sda",
                    "type": "disk",
                    "fstype": None,
                    "children": [
                        {"name": "sda1", "type": "part", "fstype": "crypto_LUKS"}
                    ],
                }
            ]
        }
        with patch(
            "subprocess.run",
            return_value=_make_proc(stdout=json.dumps(lsblk_data)),
        ):
            result = scanner.check_luks()
        assert result.status == "ok"

    def test_not_encrypted(self) -> None:
        """lsblk JSON has only ext4 → fail."""
        scanner = PrivacyScanner()
        lsblk_data = {
            "blockdevices": [
                {"name": "sda", "type": "disk", "fstype": None},
                {"name": "sda1", "type": "part", "fstype": "ext4"},
            ]
        }
        with patch(
            "subprocess.run",
            return_value=_make_proc(stdout=json.dumps(lsblk_data)),
        ):
            result = scanner.check_luks()
        assert result.status == "fail"


# ---------------------------------------------------------------------------
# TestScreenRecording
# ---------------------------------------------------------------------------


class TestScreenRecording:
    def test_none_running(self) -> None:
        """No screen-recording processes → ok."""
        scanner = PrivacyScanner()
        with patch("subprocess.run", return_value=_make_proc(returncode=1, stdout="")):
            result = scanner.check_screen_recording()
        assert result.status == "ok"

    def test_teamviewer_running(self) -> None:
        """TeamViewer found → warn."""
        scanner = PrivacyScanner()

        def _pgrep_side_effect(cmd, **kwargs):
            if "TeamViewer" in cmd:
                return _make_proc(returncode=0, stdout="5678")
            return _make_proc(returncode=1, stdout="")

        with patch("subprocess.run", side_effect=_pgrep_side_effect):
            result = scanner.check_screen_recording()
        assert result.status == "warn"


# ---------------------------------------------------------------------------
# TestPlatformFiltering
# ---------------------------------------------------------------------------


class TestPlatformFiltering:
    def test_run_all_filters_to_current_platform(self) -> None:
        """run_all() should only call checks tagged 'all' or current platform."""
        scanner = PrivacyScanner()
        called_platforms: list[str] = []

        # Patch every check method to record its platform tag instead of running
        checks = scanner._get_all_checks()
        for check_fn in checks:
            # Run the real method but capture which ones get included
            pass

        import sys

        current_plat = "darwin" if sys.platform == "darwin" else "linux"
        other_plat = "linux" if current_plat == "darwin" else "darwin"

        # Make every check return immediately with a known platform
        with patch.object(scanner, "_get_all_checks") as mock_get:
            darwin_check = MagicMock(return_value=ScanResult("d", "ok", "msg", "darwin"))
            linux_check = MagicMock(return_value=ScanResult("l", "ok", "msg", "linux"))
            all_check = MagicMock(return_value=ScanResult("a", "ok", "msg", "all"))

            mock_get.return_value = [darwin_check, linux_check, all_check]
            results = scanner.run_all()

        # The check for the other platform should not appear in results
        other_result_platform = "linux" if current_plat == "darwin" else "darwin"
        result_platforms = {r.platform for r in results}
        assert other_result_platform not in result_platforms
        assert "all" in result_platforms or current_plat in result_platforms
