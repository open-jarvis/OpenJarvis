"""Locate the starter config presets used by ``jarvis init --preset``.

The presets live in ``configs/openjarvis/examples/*.toml`` at the root of the
source tree, outside the ``openjarvis`` package. An installed wheel does not
contain that directory, so ``pyproject.toml`` bundles a copy inside the
package at ``openjarvis/presets/`` (see
``[tool.hatch.build.targets.wheel.force-include]``). Lookups try the bundled
copy first and fall back to the source tree so editable installs and
``uv run`` from a checkout keep working.
"""

from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parents[1]

# Copy bundled into the wheel by hatch ``force-include``.
PACKAGED_PRESETS_DIR = _PACKAGE_DIR / "presets"

# Canonical location in a source checkout: ``<repo>/configs/openjarvis/examples``.
SOURCE_PRESETS_DIR = _PACKAGE_DIR.parents[1] / "configs" / "openjarvis" / "examples"


def preset_search_paths() -> list[Path]:
    """Directories searched for ``<name>.toml``, in priority order."""
    return [PACKAGED_PRESETS_DIR, SOURCE_PRESETS_DIR]


def resolve_preset(name: str) -> Path | None:
    """Return the path of preset ``name``, or ``None`` if no copy exists."""
    for directory in preset_search_paths():
        candidate = directory / f"{name}.toml"
        if candidate.is_file():
            return candidate
    return None


def available_presets() -> list[str]:
    """Sorted names of every preset found across the search paths."""
    names: set[str] = set()
    for directory in preset_search_paths():
        if directory.is_dir():
            names.update(path.stem for path in directory.glob("*.toml"))
    return sorted(names)
