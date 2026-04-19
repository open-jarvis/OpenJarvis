"""Tests for SourceResolver ABC and resolver implementations."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List

from openjarvis.skills.sources.base import ResolvedSkill, SourceResolver


class _FakeResolver(SourceResolver):
    """In-memory resolver used for ABC tests."""

    name = "fake"

    def __init__(self, skills: List[ResolvedSkill]) -> None:
        self._skills = skills

    def cache_dir(self) -> Path:
        return Path("/tmp/fake-cache")

    def sync(self) -> None:
        pass

    def list_skills(self) -> List[ResolvedSkill]:
        return list(self._skills)


class TestResolvedSkill:
    def test_create(self):
        skill = ResolvedSkill(
            name="my-skill",
            source="hermes",
            path=Path("/tmp/x"),
            category="research",
            description="Does research",
            commit="abc123",
        )
        assert skill.name == "my-skill"
        assert skill.source == "hermes"

    def test_default_sidecar_data(self):
        skill = ResolvedSkill(
            name="x",
            source="x",
            path=Path("/tmp"),
            category="",
            description="",
            commit="",
        )
        assert skill.sidecar_data == {}


class TestSourceResolverABC:
    def test_resolve_filters_by_name(self):
        skills = [
            ResolvedSkill(
                name="research-it",
                source="fake",
                path=Path("/tmp/r"),
                category="research",
                description="x",
                commit="a",
            ),
            ResolvedSkill(
                name="code-it",
                source="fake",
                path=Path("/tmp/c"),
                category="coding",
                description="x",
                commit="a",
            ),
        ]
        resolver = _FakeResolver(skills)
        results = resolver.resolve("research-it")
        assert len(results) == 1
        assert results[0].name == "research-it"

    def test_resolve_filters_by_partial_name(self):
        skills = [
            ResolvedSkill(
                name="research-it",
                source="fake",
                path=Path("/tmp/r"),
                category="research",
                description="x",
                commit="a",
            ),
            ResolvedSkill(
                name="code-it",
                source="fake",
                path=Path("/tmp/c"),
                category="coding",
                description="x",
                commit="a",
            ),
        ]
        resolver = _FakeResolver(skills)
        # 'res' should match 'research-it'
        results = resolver.resolve("res")
        assert len(results) == 1

    def test_resolve_empty_query_returns_all(self):
        skills = [
            ResolvedSkill(
                name="a",
                source="fake",
                path=Path("/tmp/a"),
                category="x",
                description="x",
                commit="a",
            ),
            ResolvedSkill(
                name="b",
                source="fake",
                path=Path("/tmp/b"),
                category="x",
                description="x",
                commit="a",
            ),
        ]
        resolver = _FakeResolver(skills)
        assert len(resolver.resolve("")) == 2

    def test_filter_by_category(self):
        skills = [
            ResolvedSkill(
                name="a",
                source="fake",
                path=Path("/tmp/a"),
                category="research",
                description="x",
                commit="a",
            ),
            ResolvedSkill(
                name="b",
                source="fake",
                path=Path("/tmp/b"),
                category="coding",
                description="x",
                commit="a",
            ),
        ]
        resolver = _FakeResolver(skills)
        results = resolver.filter_by_category("research")
        assert len(results) == 1
        assert results[0].category == "research"


class TestHermesResolver:
    def test_lists_skills_in_two_level_layout(self, tmp_path: Path):
        from openjarvis.skills.sources.hermes import HermesResolver

        # Build a fake Hermes layout: skills/<category>/<skill>/SKILL.md
        skills_root = tmp_path / "skills"
        (skills_root / "apple" / "apple-notes").mkdir(parents=True)
        (skills_root / "apple" / "apple-notes" / "SKILL.md").write_text(
            textwrap.dedent("""\
                ---
                name: apple-notes
                description: Manage Apple Notes
                ---
                Body
            """)
        )
        (skills_root / "github" / "github-pr").mkdir(parents=True)
        (skills_root / "github" / "github-pr" / "SKILL.md").write_text(
            textwrap.dedent("""\
                ---
                name: github-pr
                description: Manage GitHub PRs
                ---
                Body
            """)
        )

        resolver = HermesResolver(cache_root=tmp_path)
        skills = resolver.list_skills()
        names = sorted(s.name for s in skills)
        assert names == ["apple-notes", "github-pr"]
        # Categories come from the parent directory
        for s in skills:
            if s.name == "apple-notes":
                assert s.category == "apple"
            elif s.name == "github-pr":
                assert s.category == "github"

    def test_skips_description_md(self, tmp_path: Path):
        from openjarvis.skills.sources.hermes import HermesResolver

        skills_root = tmp_path / "skills"
        category_dir = skills_root / "apple"
        category_dir.mkdir(parents=True)
        # DESCRIPTION.md at category level — should be skipped
        (category_dir / "DESCRIPTION.md").write_text("# Apple skills")
        (category_dir / "apple-notes").mkdir()
        (category_dir / "apple-notes" / "SKILL.md").write_text(
            textwrap.dedent("""\
                ---
                name: apple-notes
                description: x
                ---
            """)
        )

        resolver = HermesResolver(cache_root=tmp_path)
        skills = resolver.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "apple-notes"

    def test_filter_by_category(self, tmp_path: Path):
        from openjarvis.skills.sources.hermes import HermesResolver

        skills_root = tmp_path / "skills"
        for cat in ("apple", "github"):
            d = skills_root / cat / f"{cat}-skill"
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(
                textwrap.dedent(f"""\
                    ---
                    name: {cat}-skill
                    description: x
                    ---
                """)
            )

        resolver = HermesResolver(cache_root=tmp_path)
        results = resolver.filter_by_category("apple")
        assert len(results) == 1
        assert results[0].category == "apple"


class TestOpenClawResolver:
    def test_lists_skills_in_owner_layout(self, tmp_path: Path):
        from openjarvis.skills.sources.openclaw import OpenClawResolver

        skills_root = tmp_path / "skills"
        # OpenClaw layout: skills/<owner>/<skill>/SKILL.md
        d = skills_root / "alice" / "etherscan"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            textwrap.dedent("""\
                ---
                name: etherscan
                description: Query EVM chain data
                ---
                Body
            """)
        )

        resolver = OpenClawResolver(cache_root=tmp_path)
        skills = resolver.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "etherscan"
        assert skills[0].category == "alice"

    def test_reads_meta_json_sidecar(self, tmp_path: Path):
        import json

        from openjarvis.skills.sources.openclaw import OpenClawResolver

        skills_root = tmp_path / "skills"
        d = skills_root / "alice" / "etherscan"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            textwrap.dedent("""\
                ---
                name: etherscan
                description: x
                ---
            """)
        )
        (d / "_meta.json").write_text(
            json.dumps(
                {
                    "owner": "alice",
                    "slug": "etherscan",
                    "latest": {"version": "1.0.0", "commit": "abc123"},
                }
            )
        )

        resolver = OpenClawResolver(cache_root=tmp_path)
        skills = resolver.list_skills()
        assert len(skills) == 1
        assert skills[0].sidecar_data["owner"] == "alice"
        assert skills[0].sidecar_data["latest"]["version"] == "1.0.0"


class TestGitHubResolver:
    def test_recursive_walk_finds_skill_md(self, tmp_path: Path):
        from openjarvis.skills.sources.github import GitHubResolver

        # Arbitrary nested layout
        d = tmp_path / "any" / "depth" / "my-skill"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            textwrap.dedent("""\
                ---
                name: my-skill
                description: x
                ---
                Body
            """)
        )

        resolver = GitHubResolver(cache_root=tmp_path, repo_url="https://example.com/x")
        skills = resolver.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "my-skill"

    def test_finds_lowercase_skill_md(self, tmp_path: Path):
        from openjarvis.skills.sources.github import GitHubResolver

        d = tmp_path / "my-skill"
        d.mkdir()
        (d / "skill.md").write_text(
            textwrap.dedent("""\
                ---
                name: my-skill
                description: x
                ---
            """)
        )

        resolver = GitHubResolver(cache_root=tmp_path, repo_url="https://example.com/x")
        skills = resolver.list_skills()
        assert len(skills) == 1
