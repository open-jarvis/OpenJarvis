"""Central, env-aware resolution of OpenJarvis' home directory.

OpenJarvis keeps all of its runtime state (config, databases, caches, logs,
credentials, skills, recipes, …) under a single root so it never clutters the
user's home directory beyond one directory. That root is resolved here, with
the following precedence (highest first):

1. ``$OPENJARVIS_HOME`` — explicit override (also honored by the shell
   installer, see ``scripts/install/install.sh``).
2. ``$XDG_DATA_HOME/openjarvis`` — when ``$XDG_DATA_HOME`` is set, follow the
   XDG Base Directory spec by nesting a single ``openjarvis`` directory under
   it. We deliberately use ONE directory rather than splitting across XDG
   config/data/cache so the install tree stays self-contained and relocatable.
3. ``~/.openjarvis`` — the historical default. With no env vars set, the
   resolved path is exactly this, so existing installs are untouched.

``config.py`` re-exports :func:`get_config_dir` results through the legacy
``DEFAULT_CONFIG_DIR``/``DEFAULT_CONFIG_PATH`` names (computed dynamically) so
the ~45 modules that import those names keep working while honoring the
override. Modules that previously hardcoded ``Path.home() / ".openjarvis"``
should call :func:`get_config_dir` (or :func:`get_data_dir` /
:func:`get_cache_dir`) instead.

Defense in depth: the resolved root must never live inside the OpenJarvis
source tree (a misconfigured ``$OPENJARVIS_HOME`` pointing at the repo would
otherwise scatter runtime artifacts into the working tree). This mirrors the
guard in ``learning/spec_search/storage/paths.py`` and fails loudly per
REVIEW.md's no-silent-failure discipline.
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_DIR_NAME = ".openjarvis"
_XDG_SUBDIR_NAME = "openjarvis"


class ConfigurationError(RuntimeError):
    """Raised when the resolved home directory would violate isolation guarantees."""


def _find_source_root() -> Path | None:
    """Walk upward from this module to find the OpenJarvis source root.

    Returns the directory containing the OpenJarvis ``pyproject.toml`` (the one
    whose ``name = "openjarvis"``), or ``None`` when running from an installed
    wheel rather than a source checkout.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        py = candidate / "pyproject.toml"
        if py.exists():
            try:
                content = py.read_text(encoding="utf-8")
            except OSError:
                continue
            if 'name = "openjarvis"' in content.lower():
                return candidate
    return None


def _reject_source_tree(path: Path) -> Path:
    """Raise if ``path`` resolves inside the OpenJarvis source tree."""
    source_root = _find_source_root()
    if source_root is not None:
        try:
            path.relative_to(source_root)
        except ValueError:
            pass  # Good — not inside the source tree.
        else:
            raise ConfigurationError(
                f"OpenJarvis home ({path}) is inside the source tree "
                f"({source_root}). OpenJarvis refuses to write runtime state "
                "inside its own repo. Set OPENJARVIS_HOME (or XDG_DATA_HOME) "
                "to a directory outside the repo (default: ~/.openjarvis)."
            )
    return path


def get_config_dir() -> Path:
    """Resolve OpenJarvis' single root directory, honoring env overrides.

    Precedence: ``$OPENJARVIS_HOME`` > ``$XDG_DATA_HOME/openjarvis`` >
    ``~/.openjarvis``. The result is always absolute and is rejected if it
    falls inside the OpenJarvis source tree.
    """
    env_home = os.environ.get("OPENJARVIS_HOME")
    if env_home:
        resolved = Path(env_home).expanduser().resolve()
        return _reject_source_tree(resolved)

    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        resolved = (Path(xdg_data).expanduser() / _XDG_SUBDIR_NAME).resolve()
        return _reject_source_tree(resolved)

    return (Path.home() / _DEFAULT_DIR_NAME).resolve()


def get_config_path() -> Path:
    """Resolve the path to ``config.toml`` under the OpenJarvis root."""
    return get_config_dir() / "config.toml"


def get_data_dir() -> Path:
    """Resolve the directory for persistent data (databases, blobs, …).

    Consolidated under the single root; identical to :func:`get_config_dir`.
    Provided as a distinct name so call sites read intentionally.
    """
    return get_config_dir()


def get_cache_dir() -> Path:
    """Resolve the directory for regenerable caches (eval datasets, etc.).

    Lives at ``<root>/cache`` so caches stay inside the single OpenJarvis
    directory instead of scattering across ``~/.cache``.
    """
    return get_config_dir() / "cache"
