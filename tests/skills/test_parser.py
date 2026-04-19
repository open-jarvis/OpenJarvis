"""Tests for the SkillParser strict + tolerant passes."""

from __future__ import annotations

import pytest

from openjarvis.skills.parser import SkillParseError, SkillParser


class TestStrictRequiredFields:
    def test_missing_name_raises(self):
        parser = SkillParser()
        frontmatter = {"description": "x"}
        with pytest.raises(SkillParseError, match="name"):
            parser.parse_frontmatter(frontmatter)

    def test_missing_description_raises(self):
        parser = SkillParser()
        frontmatter = {"name": "test-skill"}
        with pytest.raises(SkillParseError, match="description"):
            parser.parse_frontmatter(frontmatter)

    def test_minimal_valid_frontmatter(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {"name": "minimal", "description": "Does something useful"}
        )
        assert manifest.name == "minimal"
        assert manifest.description == "Does something useful"


class TestStrictNamingRules:
    def test_uppercase_rejected(self):
        parser = SkillParser()
        with pytest.raises(SkillParseError, match="lowercase"):
            parser.parse_frontmatter({"name": "MySkill", "description": "x"})

    def test_underscore_rejected(self):
        parser = SkillParser()
        with pytest.raises(SkillParseError, match="hyphen"):
            parser.parse_frontmatter({"name": "my_skill", "description": "x"})

    def test_leading_hyphen_rejected(self):
        parser = SkillParser()
        with pytest.raises(SkillParseError, match="hyphen"):
            parser.parse_frontmatter({"name": "-skill", "description": "x"})

    def test_trailing_hyphen_rejected(self):
        parser = SkillParser()
        with pytest.raises(SkillParseError, match="hyphen"):
            parser.parse_frontmatter({"name": "skill-", "description": "x"})

    def test_consecutive_hyphens_rejected(self):
        parser = SkillParser()
        with pytest.raises(SkillParseError, match="consecutive"):
            parser.parse_frontmatter({"name": "my--skill", "description": "x"})

    def test_valid_kebab_name_accepted(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {"name": "my-skill-123", "description": "x"}
        )
        assert manifest.name == "my-skill-123"


class TestStrictLengthLimits:
    def test_name_over_64_chars_rejected(self):
        parser = SkillParser()
        too_long = "a" * 65
        with pytest.raises(SkillParseError, match="64"):
            parser.parse_frontmatter({"name": too_long, "description": "x"})

    def test_description_over_1024_chars_rejected(self):
        parser = SkillParser()
        too_long = "a" * 1025
        with pytest.raises(SkillParseError, match="1024"):
            parser.parse_frontmatter({"name": "test", "description": too_long})


class TestTolerantFieldMapping:
    def test_top_level_version_mapped_to_metadata(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "version": "1.2.3",
            }
        )
        assert manifest.version == "1.2.3"

    def test_top_level_author_mapped_to_metadata(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "author": "alice",
            }
        )
        assert manifest.author == "alice"

    def test_top_level_tags_mapped_to_metadata(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "tags": ["research", "nlp"],
            }
        )
        assert manifest.tags == ["research", "nlp"]

    def test_top_level_required_capabilities_mapped(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "required_capabilities": ["network:fetch"],
            }
        )
        assert manifest.required_capabilities == ["network:fetch"]

    def test_top_level_depends_mapped(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "depends": ["summarize"],
            }
        )
        assert manifest.depends == ["summarize"]

    def test_top_level_user_invocable_mapped(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "user_invocable": False,
            }
        )
        assert manifest.user_invocable is False

    def test_top_level_disable_model_invocation_mapped(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "disable_model_invocation": True,
            }
        )
        assert manifest.disable_model_invocation is True

    def test_metadata_openjarvis_namespace_used(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "metadata": {
                    "openjarvis": {
                        "version": "9.9.9",
                        "tags": ["already", "mapped"],
                    },
                },
            }
        )
        assert manifest.version == "9.9.9"
        assert manifest.tags == ["already", "mapped"]

    def test_unmapped_field_logs_warning(self, caplog):
        import logging

        parser = SkillParser()
        with caplog.at_level(logging.WARNING):
            parser.parse_frontmatter(
                {
                    "name": "test",
                    "description": "x",
                    "weird_vendor_field": "something",
                }
            )
        assert any("weird_vendor_field" in record.message for record in caplog.records)

    def test_original_frontmatter_preserved(self):
        parser = SkillParser()
        original = {
            "name": "test",
            "description": "x",
            "weird_field": "preserved",
        }
        manifest = parser.parse_frontmatter(original)
        # Stored under metadata.openjarvis.original_frontmatter
        oj = manifest.metadata.get("openjarvis", {})
        assert "original_frontmatter" in oj
        assert oj["original_frontmatter"]["weird_field"] == "preserved"

    def test_platforms_list_mapped_to_compatibility_string(self):
        parser = SkillParser()
        manifest = parser.parse_frontmatter(
            {
                "name": "test",
                "description": "x",
                "platforms": ["macos", "linux"],
            }
        )
        # Platforms get rendered into a compatibility string under metadata
        oj = manifest.metadata.get("openjarvis", {})
        assert "platforms" in oj or "compatibility" in oj
