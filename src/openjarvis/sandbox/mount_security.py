"""Mount validation and security for container sandboxes.

Port of NanoClaw's ``mount-security.ts`` — validates bind mounts
against an allowlist and blocks paths containing sensitive files.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default blocked patterns
# ---------------------------------------------------------------------------

DEFAULT_BLOCKED_PATTERNS: List[str] = [
    ".ssh",
    ".gnupg",
    ".env",
    "credentials",
    "id_rsa",
    "id_ed25519",
    ".aws",
    ".config/gcloud",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    ".git/config",
    "shadow",
    "passwd",
    "token",
    "secret",
    ".docker/config.json",
    ".kube/config",
    ".npmrc",
    ".pypirc",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AllowedRoot:
    """An allowed mount root with optional read-only constraint."""

    path: str
    read_only: bool = True


@dataclass(slots=True)
class MountAllowlist:
    """Allowlist for container mounts."""

    roots: List[AllowedRoot] = field(default_factory=list)
    blocked_patterns: List[str] = field(
        default_factory=lambda: list(DEFAULT_BLOCKED_PATTERNS),
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def load_mount_allowlist(path: str) -> MountAllowlist:
    """Load a mount allowlist from a JSON file.

    Expected format::

        {
            "roots": [
                {"path": "/home/user/projects", "read_only": false},
                {"path": "/data", "read_only": true}
            ],
            "blocked_patterns": [".ssh", ".env", "*.pem"]
        }

    If ``blocked_patterns`` is omitted, :data:`DEFAULT_BLOCKED_PATTERNS`
    is used.
    """
    raw = Path(path).read_text()
    data = json.loads(raw)

    roots = [
        AllowedRoot(
            path=r["path"],
            read_only=r.get("read_only", True),
        )
        for r in data.get("roots", [])
    ]

    blocked = data.get("blocked_patterns", list(DEFAULT_BLOCKED_PATTERNS))
    return MountAllowlist(roots=roots, blocked_patterns=blocked)


def _is_blocked(mount_path: str, patterns: List[str]) -> bool:
    """Check whether any component of *mount_path* matches a block pattern."""
    resolved = Path(mount_path).resolve()
    parts = resolved.parts
    name = resolved.name

    for pattern in patterns:
        # Match against final component (filename)
        if fnmatch.fnmatch(name, pattern):
            return True
        # Match against any path component
        for part in parts:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def _is_under_allowed_root(
    mount_path: str,
    roots: List[AllowedRoot],
) -> bool:
    """Check whether *mount_path* is under any allowed root."""
    if not roots:
        return True  # No roots configured = allow all non-blocked

    resolved = Path(mount_path).resolve()
    for root in roots:
        root_resolved = Path(root.path).resolve()
        try:
            resolved.relative_to(root_resolved)
            return True
        except ValueError:
            continue
    return False


def validate_mount(
    mount_path: str,
    allowlist: MountAllowlist,
) -> bool:
    """Validate a single mount path against the allowlist.

    Returns ``True`` if the mount is allowed, ``False`` otherwise.
    """
    # Resolve symlinks and normalize
    try:
        resolved = str(Path(mount_path).resolve())
    except (OSError, ValueError):
        return False

    # Check blocked patterns
    if _is_blocked(resolved, allowlist.blocked_patterns):
        logger.debug("Mount blocked by pattern: %s", mount_path)
        return False

    # Check allowed roots
    if not _is_under_allowed_root(resolved, allowlist.roots):
        logger.debug("Mount not under any allowed root: %s", mount_path)
        return False

    return True


def validate_mounts(
    mounts: List[str],
    allowlist: MountAllowlist,
) -> List[str]:
    """Validate a list of mount paths. Returns only valid mounts.

    Raises :class:`ValueError` for any blocked mount.
    """
    valid: List[str] = []
    for mount in mounts:
        if _is_blocked(mount, allowlist.blocked_patterns):
            raise ValueError(f"Mount path blocked by security policy: {mount}")
        if _is_under_allowed_root(mount, allowlist.roots):
            valid.append(mount)
        else:
            raise ValueError(f"Mount path not under any allowed root: {mount}")
    return valid


__all__ = [
    "AllowedRoot",
    "DEFAULT_BLOCKED_PATTERNS",
    "MountAllowlist",
    "load_mount_allowlist",
    "validate_mount",
    "validate_mounts",
]
