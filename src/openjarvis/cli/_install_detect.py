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
  with a ``.git`` directory at the repo root. Upgrade with
  ``git pull && uv sync`` from the checkout.

We detect by inspecting ``openjarvis.__file__``. If we can't tell with
confidence we fall back to the PyPI command — that's the most common
case and the worst outcome is a no-op for a user who has nothing to
pull from PyPI.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class InstallInfo:
    """How OpenJarvis was installed."""

    kind: str  # "pypi" | "uv-tool" | "editable-git" | "unknown"
    upgrade_command: str
    repo_root: Optional[Path] = None  # only set for editable-git


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
            return InstallInfo(
                kind="editable-git",
                upgrade_command=f"cd {candidate} && git pull && uv sync",
                repo_root=candidate,
            )
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
