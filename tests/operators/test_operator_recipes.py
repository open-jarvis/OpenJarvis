"""Tests for the 3 operator recipes: researcher, correspondent, sentinel."""

from pathlib import Path

import pytest

from friday_ai.operators.loader import load_operator

_OPERATORS_DIR = (
    Path(__file__).parent.parent.parent
    / "src"
    / "friday_ai"
    / "recipes"
    / "data"
    / "operators"
)


class TestResearcherOperator:
    def test_loads_valid_manifest(self):
        manifest = load_operator(_OPERATORS_DIR / "researcher.toml")
        assert manifest.name == "researcher"
        assert manifest.max_turns >= 10
        assert manifest.system_prompt  # loaded from prompt file

    def test_has_required_tools(self):
        manifest = load_operator(_OPERATORS_DIR / "researcher.toml")
        required = {
            "web_search",
            "http_request",
            "memory_store",
            "memory_search",
            "think",
            "file_write",
        }
        assert required.issubset(set(manifest.tools))

    def test_has_kg_tools(self):
        manifest = load_operator(_OPERATORS_DIR / "researcher.toml")
        assert "kg_add_entity" in manifest.tools
        assert "kg_add_relation" in manifest.tools

    def test_has_schedule(self):
        manifest = load_operator(_OPERATORS_DIR / "researcher.toml")
        assert manifest.schedule_type in ("cron", "interval")


class TestCorrespondentOperator:
    def test_loads_valid_manifest(self):
        manifest = load_operator(_OPERATORS_DIR / "correspondent.toml")
        assert manifest.name == "correspondent"
        assert manifest.max_turns >= 10
        assert manifest.system_prompt

    def test_has_required_tools(self):
        manifest = load_operator(_OPERATORS_DIR / "correspondent.toml")
        required = {"memory_store", "memory_search", "think", "llm_call"}
        assert required.issubset(set(manifest.tools))

    def test_interval_schedule(self):
        manifest = load_operator(_OPERATORS_DIR / "correspondent.toml")
        assert manifest.schedule_type == "interval"
        assert manifest.schedule_value == "300"


class TestSentinelOperator:
    def test_loads_valid_manifest(self):
        manifest = load_operator(_OPERATORS_DIR / "sentinel.toml")
        assert manifest.name == "sentinel"
        assert manifest.max_turns >= 10
        assert manifest.system_prompt

    def test_has_required_tools(self):
        manifest = load_operator(_OPERATORS_DIR / "sentinel.toml")
        required = {
            "web_search",
            "http_request",
            "memory_store",
            "memory_search",
            "think",
        }
        assert required.issubset(set(manifest.tools))

    def test_has_kg_tools(self):
        manifest = load_operator(_OPERATORS_DIR / "sentinel.toml")
        assert "kg_add_entity" in manifest.tools


class TestAllOperators:
    @pytest.mark.parametrize(
        "filename",
        ["researcher.toml", "correspondent.toml", "sentinel.toml"],
    )
    def test_all_load_without_error(self, filename):
        manifest = load_operator(_OPERATORS_DIR / filename)
        assert manifest.name
        assert manifest.tools
        assert manifest.system_prompt
