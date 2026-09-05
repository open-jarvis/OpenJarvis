"""File sensitivity policy — block access to secrets, credentials, and keys."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Union

DEFAULT_SENSITIVE_PATTERNS: frozenset[str] = frozenset(
    {
        ".env",
        ".env.*",
        "*.env",
        ".secret",
        "*.secrets",
        "credentials.*",
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*.jks",
        "id_rsa",
        "id_ed25519",
        ".htpasswd",
        ".pgpass",
        ".netrc",
    }
)


def is_sensitive_file(path: Union[str, Path]) -> bool:
    """Return ``True`` if *path* matches a sensitive file pattern.

    Checks both the filename and the full name of the resolved path against
    ``DEFAULT_SENSITIVE_PATTERNS`` using :func:`fnmatch.fnmatch`. Resolving
    existing paths prevents a harmless-looking symlink from bypassing the
    policy for a sensitive target such as ``.env``.
    Uses the Rust implementation when available, falls back to Python.
    """
    path_obj = Path(path)
    try:
        checked_path = path_obj.resolve(strict=False)
    except (OSError, RuntimeError):
        # Keep the original path for missing paths and symlink loops. The
        # filesystem operation will report its own error if the path is not
        # usable, while ordinary new files retain the existing policy.
        checked_path = path_obj

    try:
        from openjarvis._rust_bridge import get_rust_module

        _rust = get_rust_module()
        return _rust.is_sensitive_file(str(checked_path))
    except ImportError:
        return _is_sensitive_file_py(str(checked_path))


def _is_sensitive_file_py(path_str: str) -> bool:
    """Pure-Python fallback for sensitive file detection."""
    import fnmatch

    p = Path(path_str)
    name = p.name
    for pattern in DEFAULT_SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(str(p), pattern):
            return True
    return False


def filter_sensitive_paths(paths: Iterable[Union[str, Path]]) -> List[Path]:
    """Return only non-sensitive paths from *paths*."""
    return [Path(p) for p in paths if not is_sensitive_file(p)]


__all__ = [
    "DEFAULT_SENSITIVE_PATTERNS",
    "filter_sensitive_paths",
    "is_sensitive_file",
]
