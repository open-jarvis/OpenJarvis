"""jarvis upgrade — upgrade the OpenJarvis CLI to the latest published release."""

from __future__ import annotations

import shutil
import subprocess
import sys

import click


@click.command("upgrade")
@click.option("--pre", is_flag=True, default=False, help="Include pre-release versions")
@click.option("--check", "check_only", is_flag=True, default=False, help="Only report whether an update is available; do not install")
def upgrade(pre: bool, check_only: bool) -> None:
    """Upgrade the OpenJarvis CLI to the latest release on PyPI."""
    import openjarvis

    current = openjarvis.__version__
    latest = _fetch_latest(pre)

    if latest is None:
        click.echo("Could not reach PyPI to check for updates.", err=True)
        sys.exit(1)

    try:
        from packaging.version import Version
        up_to_date = Version(latest) <= Version(current)
    except Exception:
        up_to_date = latest == current

    if up_to_date:
        click.echo(f"Already up to date (v{current}).")
        return

    click.echo(f"Upgrading openjarvis  v{current} → v{latest} ...")

    if check_only:
        click.echo(f"Run  jarvis upgrade  to install.")
        return

    _run_install(pre)


def _fetch_latest(pre: bool) -> str | None:
    """Return latest version string from PyPI JSON API."""
    try:
        import urllib.request, json

        url = "https://pypi.org/pypi/openjarvis/json"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())

        releases = data.get("releases", {})
        versions: list[str] = []

        try:
            from packaging.version import Version
            for v in releases:
                parsed = Version(v)
                if pre or not parsed.is_prerelease:
                    versions.append(v)
            versions.sort(key=Version)
        except Exception:
            versions = list(releases.keys())

        return versions[-1] if versions else None
    except Exception:
        return None


def _run_install(pre: bool) -> None:
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", "-U", "openjarvis"]
        if pre:
            cmd.append("--prerelease=allow")
    else:
        cmd = [sys.executable, "-m", "pip", "install", "-U", "openjarvis"]
        if pre:
            cmd.append("--pre")

    result = subprocess.run(cmd)
    if result.returncode != 0:
        click.echo("Upgrade failed — see output above.", err=True)
        sys.exit(result.returncode)

    click.echo("Upgrade complete. Run  jarvis --version  to confirm.")
