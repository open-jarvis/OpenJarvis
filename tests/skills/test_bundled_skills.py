"""Tests for bundled skill TOML files."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.skills.loader import load_skill

# Resolve the skills/builtin/ directory relative to the project root.
BUILTIN_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "openjarvis" / "skills" / "data"
)

# Collect all TOML files once so parametrized IDs are readable.
_toml_files = sorted(BUILTIN_DIR.glob("*.toml")) if BUILTIN_DIR.is_dir() else []


def _load_all():
    """Load every bundled skill manifest.

    Returns a list of (path, manifest) tuples.
    """
    results = []
    for toml_path in _toml_files:
        manifest = load_skill(toml_path)
        results.append((toml_path, manifest))
    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBundledSkillsLoad:
    """Verify every TOML in skills/builtin/ can be loaded without errors."""

    @pytest.mark.parametrize(
        "toml_path",
        _toml_files,
        ids=[p.stem for p in _toml_files],
    )
    def test_all_bundled_skills_load(self, toml_path: Path):
        manifest = load_skill(toml_path)
        assert manifest is not None


class TestBundledSkillsHaveName:
    """Every bundled skill must declare a non-empty name."""

    @pytest.mark.parametrize(
        "toml_path",
        _toml_files,
        ids=[p.stem for p in _toml_files],
    )
    def test_all_skills_have_name(self, toml_path: Path):
        manifest = load_skill(toml_path)
        assert manifest.name, f"{toml_path.name} has an empty name"
        assert len(manifest.name) > 0


class TestBundledSkillsHaveSteps:
    """Every bundled skill must have at least one step."""

    @pytest.mark.parametrize(
        "toml_path",
        _toml_files,
        ids=[p.stem for p in _toml_files],
    )
    def test_all_skills_have_steps(self, toml_path: Path):
        manifest = load_skill(toml_path)
        assert len(manifest.steps) >= 1, f"{toml_path.name} has no steps"


class TestSkillCount:
    """The builtin directory must contain at least 20 skill files."""

    def test_skill_count(self):
        assert len(_toml_files) >= 20, (
            f"Expected at least 20 bundled skills, found {len(_toml_files)}"
        )


class TestStepsHaveToolNames:
    """Every step in every bundled skill must have a non-empty tool_name."""

    @pytest.mark.parametrize(
        "toml_path",
        _toml_files,
        ids=[p.stem for p in _toml_files],
    )
    def test_steps_have_tool_names(self, toml_path: Path):
        manifest = load_skill(toml_path)
        for i, step in enumerate(manifest.steps):
            assert step.tool_name, f"{toml_path.name} step {i} has empty tool_name"
