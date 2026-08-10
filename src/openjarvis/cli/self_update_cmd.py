"""`jarvis self-update` — upgrade OpenJarvis to the latest release.

Runs the right upgrade command for how the user installed OpenJarvis:

- PyPI installs get ``pip install --upgrade openjarvis``.
- uv-tool installs get ``uv tool upgrade openjarvis``.
- Editable git checkouts pull, then update the environment currently in use.

The detection logic is shared with the post-command "new version
available" hint in ``_version_check.py`` so both surfaces stay in sync.
"""

from __future__ import annotations

import subprocess
import sys

import click

import openjarvis
from openjarvis.cli._install_detect import InstallInfo, detect_install

_TRUSTED_UPGRADE_ARGV: dict[str, tuple[str, ...]] = {
    "pypi": ("pip", "install", "--upgrade", "openjarvis"),
    "uv-tool": ("uv", "tool", "upgrade", "openjarvis"),
    "unknown": ("pip", "install", "--upgrade", "openjarvis"),
}


def _run_editable_update(info: InstallInfo) -> int:
    """Update an editable checkout and its active Python environment."""
    if info.repo_root is None:
        raise ValueError("editable install is missing its repository root")

    git_result = subprocess.run(["git", "-C", str(info.repo_root), "pull", "--ff-only"])
    if git_result.returncode != 0:
        return git_result.returncode

    if info.editable_mode == "project-venv":
        uv_argv = ["uv", "sync", *info.sync_args]
    elif info.editable_mode == "external-venv":
        if info.python_executable is None:
            raise ValueError("external editable install is missing its Python path")
        uv_argv = [
            "uv",
            "pip",
            "install",
            "--python",
            str(info.python_executable),
            "-e",
            str(info.repo_root),
        ]
    else:
        raise ValueError(f"unknown editable install mode: {info.editable_mode!r}")

    return subprocess.run(uv_argv, cwd=info.repo_root).returncode


def _run_packaged_update(info: InstallInfo) -> int:
    """Run trusted argv for a non-editable install.

    ``upgrade_command`` is deliberately presentation-only: it may contain
    quoting intended for a shell or terminal and must never become execution
    input.
    """
    try:
        argv = _TRUSTED_UPGRADE_ARGV[info.kind]
    except KeyError as exc:
        raise ValueError(f"unknown packaged install kind: {info.kind!r}") from exc
    return subprocess.run(list(argv)).returncode


@click.command(
    "self-update",
    help=(
        "Upgrade OpenJarvis to the latest release. Detects how you "
        "installed (pip, uv tool, editable git) and runs the right "
        "command. Use --check to only print the upgrade command "
        "without running it."
    ),
)
@click.option(
    "--check",
    is_flag=True,
    help="Print the upgrade command that would run, without executing it.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip the interactive confirmation prompt.",
)
def self_update(check: bool, yes: bool) -> None:
    info = detect_install()
    current = openjarvis.__version__

    click.echo(f"Current OpenJarvis version: v{current}")
    click.echo(f"Install method: {info.kind}")
    click.echo(f"Upgrade command: {info.upgrade_command}")

    if info.warning:
        click.echo(f"\nWarning: {info.warning}", err=True)

    if check:
        return

    if info.kind == "unknown":
        click.echo(
            "\nCould not determine install method with confidence. The "
            "command above is a best guess; verify it matches how you "
            "installed before running.",
            err=True,
        )

    if not yes:
        if not click.confirm("\nRun the upgrade command now?", default=True):
            click.echo("Aborted.")
            sys.exit(1)

    click.echo(f"\n→ {info.upgrade_command}\n")

    if info.kind == "editable-git":
        returncode = _run_editable_update(info)
    else:
        returncode = _run_packaged_update(info)

    if returncode != 0:
        click.echo(
            f"\nUpgrade command exited with code {returncode}. "
            "Inspect the output above for the failure mode.",
            err=True,
        )
        sys.exit(returncode)

    click.echo("\nUpgrade complete. Re-run `jarvis --version` to confirm.")
