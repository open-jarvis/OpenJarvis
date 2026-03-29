"""Secure file and directory creation helpers.

All OpenJarvis data files under ``~/.openjarvis/`` should be created
through these helpers to ensure consistent, restrictive permissions.
"""

from __future__ import annotations

import os
from pathlib import Path


def secure_mkdir(path: Path, mode: int = 0o700) -> Path:
    """Create a directory with restrictive permissions.

    Creates parent directories as needed, then sets *mode* on the
    target directory (even if it already exists).
    """
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    return path


def secure_create(path: Path, mode: int = 0o600) -> Path:
    """Ensure a file exists with restrictive permissions.

    Creates the parent directory with ``0o700`` if needed, touches the
    file if it doesn't exist, and sets *mode* on it.
    """
    secure_mkdir(path.parent, mode=0o700)
    if not path.exists():
        path.touch()
    os.chmod(path, mode)
    return path
