"""File sensitivity policy — block access to secrets, credentials, and keys."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, List, Union

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
        ".git-credentials",
        "credentials",
        "shadow",
        "gshadow",
        "pass.txt",
        "password.txt",
        "passwords.txt",
    }
)


def is_sensitive_file(path: Union[str, Path]) -> bool:
    """Return ``True`` if *path* matches a sensitive file pattern.

    Checks the original path, symlink targets, and resolved path against
    ``DEFAULT_SENSITIVE_PATTERNS``. A symlink must not bypass the policy by
    hiding a sensitive name anywhere in its chain.
    Uses the Rust implementation when available, falls back to Python.
    """
    try:
        from openjarvis._rust_bridge import get_rust_module

        _rust = get_rust_module()
        check = _rust.is_sensitive_file
    except ImportError:
        check = _is_sensitive_file_py

    return any(check(str(candidate)) for candidate in _paths_for_policy(Path(path)))


def _paths_for_policy(path: Path) -> Iterator[Path]:
    """Keep sensitive names that full resolution would discard."""
    yield path
    candidate = path
    for _ in range(40):
        try:
            target = candidate.readlink()
        except OSError:
            break
        candidate = target if target.is_absolute() else candidate.parent / target
        yield candidate

    try:
        # Also resolve symlinks in parent directories and normalize the target.
        yield path.resolve(strict=False)
    except (OSError, RuntimeError):
        # Missing files and loops retain the checks above. The filesystem
        # operation will report its own error when a path is not usable.
        return


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
