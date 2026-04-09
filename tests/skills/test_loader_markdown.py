"""Tests for SKILL.md and directory-based skill loading."""

from __future__ import annotations

import textwrap
from pathlib import Path

from openjarvis.skills.loader import load_skill_directory, load_skill_markdown


class TestLoadSkillMarkdown:
    def test_load_markdown_with_frontmatter(self, tmp_path: Path):
        md = tmp_path / "SKILL.md"
        md.write_text(
            textwrap.dedent("""\
            ---
            name: research
            required_capabilities: [network:fetch]
            ---

            When asked to research a topic:
            1. Break into sub-questions
            2. Search each one
        """)
        )
        manifest = load_skill_markdown(md)
        assert manifest.name == "research"
        assert manifest.required_capabilities == ["network:fetch"]
        assert "Break into sub-questions" in manifest.markdown_content

    def test_load_markdown_no_frontmatter(self, tmp_path: Path):
        md = tmp_path / "SKILL.md"
        md.write_text("Just some instructions.\n")
        manifest = load_skill_markdown(md)
        assert manifest.name == "SKILL"
        assert manifest.markdown_content == "Just some instructions.\n"


class TestLoadSkillDirectory:
    def test_directory_with_toml_only(self, tmp_path: Path):
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
            [skill]
            name = "my_skill"
            description = "A test skill"
            tags = ["test"]

            [[skill.steps]]
            tool_name = "echo"
            output_key = "result"
        """)
        )
        manifest = load_skill_directory(skill_dir)
        assert manifest.name == "my_skill"
        assert manifest.tags == ["test"]
        assert len(manifest.steps) == 1
        assert manifest.markdown_content == ""

    def test_directory_with_markdown_only(self, tmp_path: Path):
        skill_dir = tmp_path / "guide_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent("""\
            ---
            name: guide_skill
            required_capabilities: [filesystem:read]
            ---

            Follow these steps when reviewing code.
        """)
        )
        manifest = load_skill_directory(skill_dir)
        assert manifest.name == "guide_skill"
        assert manifest.required_capabilities == ["filesystem:read"]
        assert "reviewing code" in manifest.markdown_content

    def test_directory_with_both(self, tmp_path: Path):
        skill_dir = tmp_path / "hybrid"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
            [skill]
            name = "hybrid"
            description = "Hybrid skill"
            tags = ["hybrid"]

            [[skill.steps]]
            tool_name = "web_search"
            arguments_template = '{"query": "{query}"}'
            output_key = "results"
        """)
        )
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent("""\
            ---
            name: hybrid
            ---

            Present results with citations.
        """)
        )
        manifest = load_skill_directory(skill_dir)
        assert manifest.name == "hybrid"
        assert len(manifest.steps) == 1
        assert "citations" in manifest.markdown_content

    def test_directory_with_depends_and_skill_steps(self, tmp_path: Path):
        skill_dir = tmp_path / "composed"
        skill_dir.mkdir()
        (skill_dir / "skill.toml").write_text(
            textwrap.dedent("""\
            [skill]
            name = "composed"
            depends = ["summarize"]

            [[skill.steps]]
            tool_name = "web_search"
            arguments_template = '{"query": "{query}"}'
            output_key = "raw"

            [[skill.steps]]
            skill_name = "summarize"
            arguments_template = '{"text": "{raw}"}'
            output_key = "summary"
        """)
        )
        manifest = load_skill_directory(skill_dir)
        assert manifest.depends == ["summarize"]
        assert manifest.steps[1].skill_name == "summarize"
        assert manifest.steps[1].tool_name == ""


class TestParserDelegation:
    def test_load_skill_markdown_uses_parser_for_validation(self, tmp_path: Path):
        """SKILL.md loading goes through SkillParser, gaining strict validation."""
        from openjarvis.skills.loader import load_skill_markdown

        md = tmp_path / "SKILL.md"
        md.write_text("---\nname: my-skill\ndescription: x\n---\nBody")
        manifest = load_skill_markdown(md)
        assert manifest.name == "my-skill"
        assert manifest.description == "x"
        assert "Body" in manifest.markdown_content

    def test_load_skill_markdown_handles_legacy_top_level_fields(self, tmp_path: Path):
        """Legacy SKILL.md with top-level tags/version/etc. still works."""
        from openjarvis.skills.loader import load_skill_markdown

        md = tmp_path / "SKILL.md"
        md.write_text(
            "---\n"
            "name: legacy-skill\n"
            "description: x\n"
            "version: 2.0.0\n"
            "tags: [a, b]\n"
            "required_capabilities: [network:fetch]\n"
            "---\n"
            "Body"
        )
        manifest = load_skill_markdown(md)
        assert manifest.version == "2.0.0"
        assert manifest.tags == ["a", "b"]
        assert manifest.required_capabilities == ["network:fetch"]


class TestLoadSkillDirectorySourcePromotion:
    def test_dot_source_file_promoted_to_metadata(self, tmp_path: Path):
        """A .source file in the skill directory promotes its source field
        into manifest.metadata.openjarvis.source."""
        from openjarvis.skills.loader import load_skill_directory

        skill_dir = tmp_path / "imported-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: imported-skill\ndescription: x\n---\nBody"
        )
        (skill_dir / ".source").write_text(
            'source = "hermes:apple-notes"\n'
            'commit = "abc123"\n'
            'category = "apple"\n'
            'installed_at = "2026-04-04T22:30:00Z"\n'
            "translated_tools = []\n"
            "missing_tools = []\n"
            "scripts_imported = false\n"
        )
        manifest = load_skill_directory(skill_dir)
        oj = manifest.metadata.get("openjarvis", {})
        assert oj.get("source") == "hermes"

    def test_no_dot_source_file_no_metadata(self, tmp_path: Path):
        """When no .source file is present, metadata.openjarvis.source is unset."""
        from openjarvis.skills.loader import load_skill_directory

        skill_dir = tmp_path / "user-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: user-skill\ndescription: x\n---\nBody"
        )
        manifest = load_skill_directory(skill_dir)
        oj = manifest.metadata.get("openjarvis", {})
        assert "source" not in oj

    def test_malformed_dot_source_does_not_crash(self, tmp_path: Path):
        """A malformed .source file is ignored, not crashed on."""
        from openjarvis.skills.loader import load_skill_directory

        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: bad\ndescription: x\n---\nBody")
        (skill_dir / ".source").write_text("this is not valid toml = [[[")
        # Should load the manifest without raising
        manifest = load_skill_directory(skill_dir)
        assert manifest.name == "bad"
