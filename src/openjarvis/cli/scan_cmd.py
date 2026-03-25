"""``jarvis scan`` — audit your environment for privacy and security risks."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

import click

# Engine ports that should only be listening on localhost.
_ENGINE_PORTS = {11434, 8080, 8000, 30000, 1234, 52415, 18181}

# Processes associated with cloud-sync agents.
_CLOUD_SYNC_PROCS = ["Dropbox", "OneDrive", "Google Drive", "iCloudDrive"]

# Screen-recording / remote-access processes (macOS).
_SCREEN_RECORDING_PROCS = [
    "TeamViewer", "AnyDesk", "ScreenConnect", "vncviewer", "Vine"
]

# Remote-access processes (Linux).
_REMOTE_ACCESS_PROCS = ["xrdp", "x11vnc", "vncserver", "AnyDesk"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ScanResult:
    """Result of a single privacy/security check."""

    name: str
    status: str  # "ok" | "warn" | "fail" | "skip"
    message: str
    platform: str  # "darwin" | "linux" | "all"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class PrivacyScanner:
    """Collection of environment privacy checks."""

    # -- Subprocess helper ---------------------------------------------------

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10)

    # -- Individual checks ---------------------------------------------------

    def check_filevault(self) -> ScanResult:
        """Check whether FileVault disk encryption is enabled (macOS)."""
        try:
            proc = self._run(["fdesetup", "status"])
            if "On" in proc.stdout:
                return ScanResult(
                    name="FileVault",
                    status="ok",
                    message="FileVault is enabled.",
                    platform="darwin",
                )
            return ScanResult(
                name="FileVault",
                status="fail",
                message="FileVault is NOT enabled. Enable full-disk encryption.",
                platform="darwin",
            )
        except Exception:
            return ScanResult(
                name="FileVault",
                status="skip",
                message="fdesetup not available.",
                platform="darwin",
            )

    def check_mdm(self) -> ScanResult:
        """Check whether the device is enrolled in an MDM profile (macOS)."""
        try:
            proc = self._run(["profiles", "status", "-type", "enrollment"])
            output = proc.stdout + proc.stderr
            lower = output.lower()
            # "not enrolled" is a strong negative signal — check it first.
            not_enrolled = "not enrolled" in lower or "no" in lower
            # Positive signals: explicit Yes/enrolled without a negation.
            enrolled_yes = (
                "mdm enrollment: yes" in lower
                or "enrolled via dep: yes" in lower
                or ("enrolled" in lower and not not_enrolled)
            )
            if enrolled_yes:
                return ScanResult(
                    name="MDM Enrollment",
                    status="warn",
                    message="Device appears to be enrolled in an MDM profile.",
                    platform="darwin",
                )
            return ScanResult(
                name="MDM Enrollment",
                status="ok",
                message="Device is not enrolled in an MDM profile.",
                platform="darwin",
            )
        except Exception:
            return ScanResult(
                name="MDM Enrollment",
                status="skip",
                message="profiles command not available.",
                platform="darwin",
            )

    def check_icloud_sync(self) -> ScanResult:
        """Check whether ~/.openjarvis is inside iCloud Drive sync scope."""
        try:
            config_path = Path("~/.openjarvis").expanduser().resolve()
            icloud_path = Path("~/Library/Mobile Documents/").expanduser().resolve()
            if str(config_path).startswith(str(icloud_path)):
                return ScanResult(
                    name="iCloud Sync",
                    status="warn",
                    message="~/.openjarvis may be synced to iCloud.",
                    platform="darwin",
                )
            # Also probe defaults for com.apple.bird (iCloud daemon)
            try:
                proc = self._run(
                    ["defaults", "read", "com.apple.bird", "optout_preference"]
                )
                val = proc.stdout.strip()
                if val == "0":
                    return ScanResult(
                        name="iCloud Sync",
                        status="warn",
                        message="iCloud Desktop/Documents sync may be active.",
                        platform="darwin",
                    )
            except Exception:
                pass
            return ScanResult(
                name="iCloud Sync",
                status="ok",
                message="~/.openjarvis is not inside iCloud Drive.",
                platform="darwin",
            )
        except Exception:
            return ScanResult(
                name="iCloud Sync",
                status="skip",
                message="Could not determine iCloud sync status.",
                platform="darwin",
            )

    def check_luks(self) -> ScanResult:
        """Check whether any block device uses LUKS encryption (Linux)."""
        try:
            proc = self._run(["lsblk", "-o", "NAME,TYPE,FSTYPE", "-J"])
            data = json.loads(proc.stdout)
        except Exception:
            return ScanResult(
                name="LUKS Encryption",
                status="skip",
                message="lsblk not available or returned unexpected output.",
                platform="linux",
            )

        def _has_luks(devices: list) -> bool:  # type: ignore[type-arg]
            for dev in devices:
                if dev.get("fstype") == "crypto_LUKS":
                    return True
                children = dev.get("children") or []
                if _has_luks(children):
                    return True
            return False

        try:
            devices = data.get("blockdevices", [])
            if _has_luks(devices):
                return ScanResult(
                    name="LUKS Encryption",
                    status="ok",
                    message="At least one LUKS-encrypted device found.",
                    platform="linux",
                )
            return ScanResult(
                name="LUKS Encryption",
                status="fail",
                message="No LUKS-encrypted block devices found.",
                platform="linux",
            )
        except Exception:
            return ScanResult(
                name="LUKS Encryption",
                status="skip",
                message="Could not parse lsblk output.",
                platform="linux",
            )

    def _check_processes(
        self,
        names: list[str],
        check_name: str,
        warn_msg: str,
        platform: str,
    ) -> ScanResult:
        """Shared helper: pgrep for any of the given process names."""
        try:
            for name in names:
                try:
                    proc = self._run(["pgrep", "-x", name])
                    if proc.returncode == 0:
                        return ScanResult(
                            name=check_name,
                            status="warn",
                            message=warn_msg.format(name=name),
                            platform=platform,
                        )
                except Exception:
                    continue
            return ScanResult(
                name=check_name,
                status="ok",
                message=f"No {check_name.lower()} processes detected.",
                platform=platform,
            )
        except Exception:
            return ScanResult(
                name=check_name,
                status="skip",
                message="pgrep not available.",
                platform=platform,
            )

    def check_cloud_sync_agents(self) -> ScanResult:
        """Check for running cloud-sync agent processes."""
        return self._check_processes(
            names=_CLOUD_SYNC_PROCS,
            check_name="Cloud Sync Agents",
            warn_msg="{name} sync agent is running — weights may be uploaded to cloud.",
            platform="all",
        )

    def check_network_exposure(self) -> ScanResult:
        """Check if engine ports are exposed on 0.0.0.0 rather than localhost."""
        try:
            if sys.platform == "darwin":
                proc = self._run(["lsof", "-iTCP", "-sTCP:LISTEN", "-n", "-P"])
            else:
                proc = self._run(["ss", "-tlnp"])
            output = proc.stdout

            exposed: list[int] = []
            for port in _ENGINE_PORTS:
                # Look for patterns like *:PORT or 0.0.0.0:PORT
                for token in (f"*:{port}", f"0.0.0.0:{port}", f":::{ port}"):
                    if token.replace(" ", "") in output.replace(" ", ""):
                        exposed.append(port)
                        break

            if exposed:
                ports_str = ", ".join(str(p) for p in sorted(exposed))
                return ScanResult(
                    name="Network Exposure",
                    status="warn",
                    message=f"Engine port(s) {ports_str} exposed on all interfaces.",
                    platform="all",
                )
            return ScanResult(
                name="Network Exposure",
                status="ok",
                message="All engine ports appear to be bound to localhost only.",
                platform="all",
            )
        except Exception:
            return ScanResult(
                name="Network Exposure",
                status="skip",
                message="Could not determine network exposure (lsof/ss unavailable).",
                platform="all",
            )

    def check_screen_recording(self) -> ScanResult:
        """Check for running screen-recording / remote-desktop processes (macOS)."""
        return self._check_processes(
            names=_SCREEN_RECORDING_PROCS,
            check_name="Screen Recording",
            warn_msg="{name} is running — screen may be accessible remotely.",
            platform="darwin",
        )

    def check_remote_access(self) -> ScanResult:
        """Check for running remote-access processes (Linux)."""
        return self._check_processes(
            names=_REMOTE_ACCESS_PROCS,
            check_name="Remote Access",
            warn_msg="{name} is running — system may be accessible remotely.",
            platform="linux",
        )

    # -- Orchestration -------------------------------------------------------

    def _get_all_checks(self) -> list[Callable[[], ScanResult]]:
        return [
            self.check_filevault,
            self.check_mdm,
            self.check_icloud_sync,
            self.check_cloud_sync_agents,
            self.check_network_exposure,
            self.check_luks,
            self.check_screen_recording,
            self.check_remote_access,
        ]

    def run_all(self) -> list[ScanResult]:
        """Run all checks, filter to the current platform, hide 'skip' results."""
        current_plat = "darwin" if sys.platform == "darwin" else "linux"
        results: list[ScanResult] = []
        for check_fn in self._get_all_checks():
            result = check_fn()
            if result.platform not in (current_plat, "all"):
                continue
            if result.status == "skip":
                continue
            results.append(result)
        return results

    def run_quick(self) -> list[ScanResult]:
        """Run only critical checks: disk encryption + cloud sync agents."""
        current_plat = "darwin" if sys.platform == "darwin" else "linux"
        quick_checks: list[Callable[[], ScanResult]]
        if current_plat == "darwin":
            quick_checks = [self.check_filevault, self.check_cloud_sync_agents]
        else:
            quick_checks = [self.check_luks, self.check_cloud_sync_agents]
        results = []
        for check_fn in quick_checks:
            result = check_fn()
            if result.status != "skip":
                results.append(result)
        return results


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

_STATUS_ICONS = {"ok": "✓", "warn": "!", "fail": "✗", "skip": "-"}


@click.command()
@click.option("--quick", is_flag=True, default=False, help="Run only critical checks.")
def scan(quick: bool) -> None:
    """Audit your environment for privacy and security risks."""
    scanner = PrivacyScanner()
    results: List[ScanResult] = scanner.run_quick() if quick else scanner.run_all()

    if not results:
        click.echo("No applicable checks for this platform.")
        return

    warnings = 0
    failures = 0
    for r in results:
        icon = _STATUS_ICONS.get(r.status, "?")
        click.echo(f"  [{icon}] {r.name}: {r.message}")
        if r.status == "warn":
            warnings += 1
        elif r.status == "fail":
            failures += 1

    click.echo("")
    parts = []
    if warnings:
        parts.append(f"{warnings} warning(s)")
    if failures:
        parts.append(f"{failures} issue(s)")
    if parts:
        click.echo("Summary: " + ", ".join(parts) + ".")
    else:
        click.echo("Summary: all checks passed.")
