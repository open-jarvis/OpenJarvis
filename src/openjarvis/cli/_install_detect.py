"""Detect how OpenJarvis was installed so we can show the right upgrade
command (and run the right upgrade command for ``jarvis self-update``).

Three install paths are supported today:

- **PyPI** (``pip install openjarvis``). The package lives somewhere
  inside ``site-packages``. Upgrade with ``pip install --upgrade openjarvis``.
- **uv tool** (``uv tool install openjarvis``). Lives in a uv-managed
  isolated venv under ``~/.local/share/uv/tools/``. Upgrade with
  ``uv tool upgrade openjarvis``.
- **Editable git checkout** (``uv sync`` / ``pip install -e .`` from a
  cloned repo). The package's ``__file__`` is inside a working tree
  with a ``.git`` directory at the repo root. Pull the checkout, then
  sync its project venv or reinstall into the active external venv.

We detect by inspecting ``openjarvis.__file__``. If we can't tell with
confidence we fall back to the PyPI command — that's the most common
case and the worst outcome is a no-op for a user who has nothing to
pull from PyPI.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from openjarvis.cli._install_profile import (
    load_install_profile,
    profile_sync_args,
)


@dataclass(frozen=True)
class InstallInfo:
    """How OpenJarvis was installed."""

    kind: str  # "pypi" | "uv-tool" | "editable-git" | "unknown"
    upgrade_command: str
    repo_root: Optional[Path] = None  # only set for editable-git
    editable_mode: Optional[str] = None  # "project-venv" | "external-venv"
    sync_args: tuple[str, ...] = ()
    python_executable: Optional[Path] = None
    warning: Optional[str] = None


def _display_command(argv: list[str]) -> str:
    """Format trusted argv for display only; execution never parses this text."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _editable_install_info(repo_root: Path) -> InstallInfo:
    git_argv = ["git", "-C", str(repo_root), "pull", "--ff-only"]
    project_venv = (repo_root / ".venv").resolve()

    if Path(sys.prefix).resolve() == project_venv:
        profile, profile_warning = load_install_profile(repo_root)
        if profile is None:
            sync_args = ("--inexact",)
            preservation_warning = (
                "No valid install profile was found. Optional dependencies will "
                "be preserved with `uv sync --inexact`; re-run the official "
                "installer to record an exact profile."
            )
            warning = (
                f"{profile_warning}\n{preservation_warning}"
                if profile_warning
                else preservation_warning
            )
        else:
            sync_args = profile_sync_args(profile)
            warning = None
        uv_argv = ["uv", "sync", *sync_args]
        return InstallInfo(
            kind="editable-git",
            upgrade_command=(
                f"{_display_command(git_argv)} && {_display_command(uv_argv)}"
            ),
            repo_root=repo_root,
            editable_mode="project-venv",
            sync_args=sync_args,
            warning=warning,
        )

    python_executable = Path(sys.executable)
    uv_argv = [
        "uv",
        "pip",
        "install",
        "--python",
        str(python_executable),
        "-e",
        str(repo_root),
    ]
    return InstallInfo(
        kind="editable-git",
        upgrade_command=f"{_display_command(git_argv)} && {_display_command(uv_argv)}",
        repo_root=repo_root,
        editable_mode="external-venv",
        python_executable=python_executable,
    )


def detect_install() -> InstallInfo:
    """Return an :class:`InstallInfo` for the running interpreter.

    Cheap: just walks the parent directories of ``openjarvis.__file__``
    once and checks for marker directories. No subprocess calls.
    """
    try:
        import openjarvis

        pkg_file = Path(openjarvis.__file__).resolve()
    except Exception:
        return InstallInfo(
            kind="unknown",
            upgrade_command="pip install --upgrade openjarvis",
        )

    parts = [p.lower() for p in pkg_file.parts]

    if "uv" in parts and "tools" in parts:
        return InstallInfo(
            kind="uv-tool",
            upgrade_command="uv tool upgrade openjarvis",
        )

    # Editable install: a ``.git`` dir within a few parents of the
    # package source. Walk up at most ~8 levels — enough for typical
    # ``<repo>/src/openjarvis/__init__.py`` layouts plus headroom, but
    # not so deep we wander into home or root.
    candidate = pkg_file.parent
    for _ in range(8):
        if (candidate / ".git").exists() and (candidate / "pyproject.toml").exists():
            return _editable_install_info(candidate)
        if candidate.parent == candidate:
            break
        candidate = candidate.parent

    if "site-packages" in parts:
        return InstallInfo(
            kind="pypi",
            upgrade_command="pip install --upgrade openjarvis",
        )

    return InstallInfo(
        kind="unknown",
        upgrade_command="pip install --upgrade openjarvis",
    )
