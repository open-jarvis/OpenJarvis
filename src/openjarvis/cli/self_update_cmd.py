"""`jarvis self-update` — upgrade OpenJarvis to the latest release.

Runs the right upgrade command for how the user installed OpenJarvis:

- PyPI installs get ``pip install --upgrade openjarvis``.
- uv-tool installs get ``uv tool upgrade openjarvis``.
- Editable Git checkouts recover release-tag history, fast-forward, and rebuild
  OpenJarvis in the running environment. The inexact sync preserves packages
  previously installed through extras and dependency groups.

The detection logic is shared with the post-command "new version
available" hint in ``_version_check.py`` so both surfaces stay in sync.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import click

import openjarvis
from openjarvis.cli._install_detect import detect_install


def _update_git_checkout(repo_root: Path) -> int:
    """Repair version history and update without discarding local work."""
    shallow = subprocess.run(
        ["git", "rev-parse", "--is-shallow-repository"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if shallow.returncode:
        click.echo(shallow.stderr, err=True)
        return shallow.returncode
    if shallow.stdout.strip() not in {"true", "false"}:
        click.echo("Could not determine whether the checkout is shallow.", err=True)
        return 1

    # Fetching tags alone cannot make tags beyond a shallow boundary reachable.
    fetch = ["git", "fetch", "--tags"]
    if shallow.stdout.strip() == "true":
        fetch.append("--unshallow")
        click.echo("Restoring Git history for release version detection...")
    for command in (fetch, ["git", "pull", "--ff-only"]):
        result = subprocess.run(command, cwd=repo_root)
        if result.returncode:
            return result.returncode

    # Version metadata is baked at install time, so an up-to-date checkout also
    # needs a rebuild after history repair. The Unix installer keeps its venv
    # beside src/, not inside it: target the running venv, never a new src/.venv.
    click.echo("Rebuilding OpenJarvis in the running Python environment...")
    if sys.prefix != sys.base_prefix:
        result = subprocess.run(
            [
                "uv",
                "sync",
                "--python",
                sys.executable,
                "--inexact",
                "--reinstall-package",
                "openjarvis",
            ],
            cwd=repo_root,
            env={**os.environ, "UV_PROJECT_ENVIRONMENT": sys.prefix},
        )
    else:
        # Editable installs in a non-venv interpreter have no uv project
        # environment to sync. Reinstall into that same interpreter instead.
        result = subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                sys.executable,
                "--reinstall-package",
                "openjarvis",
                "-e",
                ".",
            ],
            cwd=repo_root,
        )
    return result.returncode


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
    if info.kind == "editable-git":
        click.echo(f"Repository: {info.repo_root}")
        click.echo(
            "Upgrade plan: restore release-tag history, git pull --ff-only, "
            "then rebuild OpenJarvis while preserving installed extras."
        )
    else:
        click.echo(f"Upgrade command: {info.upgrade_command}")

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

    if info.kind == "editable-git":
        click.echo("\nUpdating the source checkout...\n")
    else:
        click.echo(f"\n→ {info.upgrade_command}\n")

    try:
        if info.kind == "editable-git":
            if info.repo_root is None:
                raise click.ClickException("Could not locate the editable checkout.")
            returncode = _update_git_checkout(info.repo_root)
        else:
            returncode = subprocess.run(shlex.split(info.upgrade_command)).returncode
    except OSError as exc:
        raise click.ClickException(f"Could not run the upgrade: {exc}") from exc

    if returncode != 0:
        click.echo(
            f"\nUpgrade command exited with code {returncode}. "
            "Inspect the output above for the failure mode.",
            err=True,
        )
        sys.exit(returncode)

    click.echo("\nUpgrade complete. Re-run `jarvis --version` to confirm.")
