"""Tests for skill index — sync and search."""

from __future__ import annotations

import textwrap
from pathlib import Path

from openjarvis.skills.index import SkillIndex


class TestSkillIndex:
    def test_load_index(self, tmp_path: Path):
        index_file = tmp_path / "index.toml"
        index_file.write_text(
            textwrap.dedent("""\
            [[skills]]
            name = "research"
            version = "0.1.0"
            description = "Research a topic"
            author = "openjarvis"
            source = "github.com/openjarvis/skills/research"
            sha256 = "abc123"
            tags = ["research"]
            required_capabilities = ["network:fetch"]

            [[skills]]
            name = "summarize"
            version = "0.2.0"
            description = "Summarize text"
            author = "community"
            source = "github.com/user/summarize"
            sha256 = "def456"
            tags = ["nlp"]
            required_capabilities = []
        """)
        )
        index = SkillIndex(tmp_path)
        assert len(index.entries) == 2
        assert index.entries["research"].version == "0.1.0"

    def test_search_by_name(self, tmp_path: Path):
        index_file = tmp_path / "index.toml"
        index_file.write_text(
            textwrap.dedent("""\
            [[skills]]
            name = "web_research"
            version = "0.1.0"
            description = "Search the web"
            author = "openjarvis"
            source = "github.com/openjarvis/skills/web_research"
            sha256 = "abc"
            tags = ["research"]
            required_capabilities = []

            [[skills]]
            name = "code_review"
            version = "0.1.0"
            description = "Review code"
            author = "openjarvis"
            source = "github.com/openjarvis/skills/code_review"
            sha256 = "def"
            tags = ["coding"]
            required_capabilities = []
        """)
        )
        index = SkillIndex(tmp_path)
        results = index.search("research")
        assert len(results) == 1
        assert results[0].name == "web_research"

    def test_search_by_tag(self, tmp_path: Path):
        index_file = tmp_path / "index.toml"
        index_file.write_text(
            textwrap.dedent("""\
            [[skills]]
            name = "skill_a"
            version = "0.1.0"
            description = "First"
            author = "x"
            source = "github.com/x/a"
            sha256 = "a"
            tags = ["nlp", "research"]
            required_capabilities = []
        """)
        )
        index = SkillIndex(tmp_path)
        results = index.search("nlp")
        assert len(results) == 1

    def test_search_no_results(self, tmp_path: Path):
        index_file = tmp_path / "index.toml"
        index_file.write_text(
            "[[skills]]\n"
            'name = "a"\nversion = "0.1.0"\n'
            'description = ""\nauthor = ""\n'
            'source = ""\nsha256 = ""\n'
            "tags = []\nrequired_capabilities = []\n"
        )
        index = SkillIndex(tmp_path)
        results = index.search("zzzzz")
        assert results == []

    def test_missing_index_file(self, tmp_path: Path):
        index = SkillIndex(tmp_path)
        assert index.entries == {}
