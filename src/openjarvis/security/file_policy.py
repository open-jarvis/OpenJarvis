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

    Checks both the lexical path and its resolved target. Resolution failures
    are denied because the target cannot be established safely. Uses the Rust
    implementation when available and falls back to Python.
    """
    candidates = _path_candidates(Path(path))
    if candidates is None:
        return True

    try:
        from openjarvis._rust_bridge import get_rust_module

        _rust = get_rust_module()
        matcher = _rust.is_sensitive_file
    except ImportError:
        matcher = _is_sensitive_file_py

    return any(matcher(str(candidate)) for candidate in candidates)


def _path_candidates(path: Path) -> tuple[Path, ...] | None:
    """Return lexical and resolved policy candidates, or ``None`` on failure."""
    try:
        resolved = path.resolve(strict=False)
    except (OSError, RuntimeError):
        return None
    if resolved == path:
        return (path,)
    return path, resolved


def _is_sensitive_file_py(path_str: str) -> bool:
    """Pure-Python fallback for sensitive file detection."""
    import fnmatch

    p = Path(path_str)
    name = p.name.casefold()
    full_path = str(p).casefold()
    for pattern in DEFAULT_SENSITIVE_PATTERNS:
        folded_pattern = pattern.casefold()
        if fnmatch.fnmatchcase(name, folded_pattern) or fnmatch.fnmatchcase(
            full_path, folded_pattern
        ):
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
