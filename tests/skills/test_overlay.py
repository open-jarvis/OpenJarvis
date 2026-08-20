"""Tests for the skills overlay loader/writer (Plan 2A)."""

from __future__ import annotations

from pathlib import Path

from openjarvis.skills.overlay import (
    SkillOverlay,
    SkillOverlayLoader,
    write_overlay,
)


class TestSkillOverlayDataclass:
    def test_create_minimal(self):
        ov = SkillOverlay(
            skill_name="my-skill",
            optimizer="dspy",
            optimized_at="2026-04-08T14:30:00Z",
            trace_count=47,
            description="Optimized description",
        )
        assert ov.skill_name == "my-skill"
        assert ov.optimizer == "dspy"
        assert ov.few_shot == []

    def test_create_with_few_shot(self):
        ov = SkillOverlay(
            skill_name="my-skill",
            optimizer="dspy",
            optimized_at="2026-04-08T14:30:00Z",
            trace_count=47,
            description="Optimized description",
            few_shot=[
                {"input": "transformer attention", "output": "## Recent Advances..."},
            ],
        )
        assert len(ov.few_shot) == 1
        assert ov.few_shot[0]["input"] == "transformer attention"


class TestWriteOverlay:
    def test_write_creates_file(self, tmp_path: Path):
        overlay_dir = tmp_path / "learning" / "skills"
        ov = SkillOverlay(
            skill_name="test-skill",
            optimizer="dspy",
            optimized_at="2026-04-08T14:30:00Z",
            trace_count=20,
            description="Optimized",
        )
        path = write_overlay(ov, overlay_dir)
        assert path.exists()
        assert path.name == "optimized.toml"
        assert path.parent.name == "test-skill"

    def test_write_then_read_roundtrip(self, tmp_path: Path):
        overlay_dir = tmp_path / "learning" / "skills"
        ov = SkillOverlay(
            skill_name="test-skill",
            optimizer="dspy",
            optimized_at="2026-04-08T14:30:00Z",
            trace_count=42,
            description="Better description",
            few_shot=[
                {"input": "q1", "output": "a1"},
                {"input": "q2", "output": "a2"},
            ],
        )
        write_overlay(ov, overlay_dir)

        loader = SkillOverlayLoader(overlay_dir)
        loaded = loader.load("test-skill")
        assert loaded is not None
        assert loaded.skill_name == "test-skill"
        assert loaded.optimizer == "dspy"
        assert loaded.trace_count == 42
        assert loaded.description == "Better description"
        assert len(loaded.few_shot) == 2
        assert loaded.few_shot[0]["input"] == "q1"


class TestSkillOverlayLoader:
    def test_load_missing_returns_none(self, tmp_path: Path):
        overlay_dir = tmp_path / "learning" / "skills"
        loader = SkillOverlayLoader(overlay_dir)
        assert loader.load("nonexistent") is None

    def test_load_malformed_returns_none(self, tmp_path: Path):
        overlay_dir = tmp_path / "learning" / "skills" / "broken"
        overlay_dir.mkdir(parents=True)
        (overlay_dir / "optimized.toml").write_text("not valid toml = [[[")

        loader = SkillOverlayLoader(tmp_path / "learning" / "skills")
        assert loader.load("broken") is None

    def test_load_directory_does_not_exist(self, tmp_path: Path):
        loader = SkillOverlayLoader(tmp_path / "does-not-exist")
        assert loader.load("anything") is None
