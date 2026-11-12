"""Tests for the local Claude skill source and the on-demand skill library."""

from __future__ import annotations

from pathlib import Path

from openjarvis.skills.library import SkillLibrary, skill_hint
from openjarvis.skills.sources.claude import ClaudeResolver
from openjarvis.tools.skill_library_tools import FindSkillsTool, UseSkillTool


def _skill(root: Path, folder: str, name: str, description: str, body: str = "") -> None:
    d = root / folder
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body or 'Do it well.'}\n",
        encoding="utf-8",
    )


def test_claude_resolver_lists_local_skills(tmp_path: Path) -> None:
    _skill(tmp_path, "marketing-campaign", "marketing-campaign", "Plan a marketing campaign")
    (tmp_path / "not-a-skill").mkdir()
    resolver = ClaudeResolver(skills_dir=tmp_path)
    resolver.sync()
    skills = resolver.list_skills()
    assert [s.name for s in skills] == ["marketing-campaign"]
    assert skills[0].source == "claude"
    assert skills[0].description == "Plan a marketing campaign"


def test_claude_resolver_missing_folder(tmp_path: Path) -> None:
    resolver = ClaudeResolver(skills_dir=tmp_path / "absent")
    resolver.sync()
    assert resolver.list_skills() == []
    assert "No Claude skills folder" in resolver.refresh_warning


def test_library_search_and_load(tmp_path: Path) -> None:
    _skill(tmp_path, "claude/marketing-campaign", "marketing-campaign",
           "Plan and run a marketing campaign with channels and budget", "Step 1: goals.")
    _skill(tmp_path, "claude/python-testing", "python-testing",
           "Python testing with pytest fixtures and coverage")
    lib = SkillLibrary(tmp_path)
    assert len(lib) == 2
    hits = lib.search("plan a marketing campaign", k=2)
    assert hits[0][0].name == "marketing-campaign"
    assert lib.search("hello there") == []
    text = lib.load("claude:marketing-campaign")
    assert text is not None and "Step 1: goals." in text
    assert lib.load("nope") is None


def test_skill_hint_skips_small_talk(tmp_path: Path, monkeypatch) -> None:
    _skill(tmp_path, "marketing-campaign", "marketing-campaign",
           "Plan and run a marketing campaign with channels and budget")
    import openjarvis.skills.library as library

    monkeypatch.setattr(library, "_LIBRARY", SkillLibrary(tmp_path))
    assert skill_hint("how are you today") == ""
    assert "marketing-campaign" in skill_hint("plan a marketing campaign budget", min_score=0.1)


def test_skill_tools(tmp_path: Path, monkeypatch) -> None:
    _skill(tmp_path, "pdf-report", "pdf-report", "Build a PDF report from data", "Use tables.")
    import openjarvis.skills.library as library

    monkeypatch.setattr(library, "_LIBRARY", SkillLibrary(tmp_path))
    found = FindSkillsTool().execute(query="pdf report")
    assert found.success and "pdf-report" in found.content
    loaded = UseSkillTool().execute(name="pdf-report")
    assert loaded.success and "Use tables." in loaded.content
    missing = UseSkillTool().execute(name="pdf reprot")
    assert not missing.success
