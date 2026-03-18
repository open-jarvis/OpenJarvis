"""Tests for recipe system — loader, discovery, and resolution."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from openjarvis.recipes.loader import (
    Recipe,
    discover_recipes,
    load_recipe,
    resolve_recipe,
)

SAMPLE_TOML = textwrap.dedent("""\
    [recipe]
    name = "test_recipe"
    description = "A test recipe"
    version = "2.0.0"

    [intelligence]
    model = "llama3:8b"
    quantization = "q4_K_M"

    [engine]
    key = "ollama"

    [agent]
    type = "native_react"
    max_turns = 12
    temperature = 0.4
    tools = ["calculator", "think"]
    system_prompt = "You are a test assistant."

    [learning]
    routing = "grpo"
    agent = "icl_updater"

    [eval]
    suites = ["reasoning", "coding"]
""")


class TestLoadRecipe:
    def test_load_recipe_from_toml(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(SAMPLE_TOML)

        recipe = load_recipe(toml_file)

        assert recipe.name == "test_recipe"
        assert recipe.description == "A test recipe"
        assert recipe.version == "2.0.0"
        assert recipe.model == "llama3:8b"
        assert recipe.quantization == "q4_K_M"
        assert recipe.engine_key == "ollama"
        assert recipe.agent_type == "native_react"
        assert recipe.max_turns == 12
        assert recipe.temperature == pytest.approx(0.4)
        assert recipe.tools == ["calculator", "think"]
        assert recipe.system_prompt == "You are a test assistant."
        assert recipe.routing_policy == "grpo"
        assert recipe.agent_policy == "icl_updater"
        assert recipe.eval_suites == ["reasoning", "coding"]
        assert isinstance(recipe.raw, dict)
        assert "recipe" in recipe.raw

    def test_load_recipe_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            load_recipe("/nonexistent/path/recipe.toml")

    def test_load_recipe_defaults(self, tmp_path: Path) -> None:
        """Minimal TOML should yield sensible defaults."""
        toml_file = tmp_path / "minimal.toml"
        toml_file.write_text('[recipe]\nname = "minimal"\n')

        recipe = load_recipe(toml_file)

        assert recipe.name == "minimal"
        assert recipe.version == "0.1.0"
        assert recipe.model is None
        assert recipe.tools == []
        assert recipe.eval_suites == []

    def test_load_recipe_name_from_filename(self, tmp_path: Path) -> None:
        """When [recipe] has no name, use the file stem."""
        toml_file = tmp_path / "my_recipe.toml"
        toml_file.write_text('[recipe]\ndescription = "no name"\n')

        recipe = load_recipe(toml_file)
        assert recipe.name == "my_recipe"


class TestDiscoverRecipes:
    def test_discover_builtin_recipes(self) -> None:
        recipes = discover_recipes()
        names = {r.name for r in recipes}
        assert "coding_assistant" in names
        assert "research_assistant" in names
        assert "general_assistant" in names
        assert len(recipes) >= 3

    def test_discover_extra_dirs(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "custom.toml"
        toml_file.write_text('[recipe]\nname = "custom"\ndescription = "extra"\n')
        recipes = discover_recipes(extra_dirs=[tmp_path])
        names = {r.name for r in recipes}
        assert "custom" in names

    def test_discover_skips_malformed(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.toml"
        bad.write_text("this is not valid toml {{{{")
        recipes = discover_recipes(extra_dirs=[tmp_path])
        # Should not raise; malformed files are silently skipped
        names = {r.name for r in recipes}
        assert "bad" not in names


class TestRecipeToBuilderKwargs:
    def test_recipe_to_builder_kwargs(self, tmp_path: Path) -> None:
        toml_file = tmp_path / "test.toml"
        toml_file.write_text(SAMPLE_TOML)

        recipe = load_recipe(toml_file)
        kwargs = recipe.to_builder_kwargs()

        assert kwargs["model"] == "llama3:8b"
        assert kwargs["engine_key"] == "ollama"
        assert kwargs["agent"] == "native_react"
        assert kwargs["tools"] == ["calculator", "think"]
        assert kwargs["temperature"] == pytest.approx(0.4)
        assert kwargs["max_turns"] == 12
        assert kwargs["system_prompt"] == "You are a test assistant."
        assert kwargs["routing_policy"] == "grpo"
        assert kwargs["agent_policy"] == "icl_updater"
        assert kwargs["quantization"] == "q4_K_M"
        assert kwargs["eval_suites"] == ["reasoning", "coding"]

    def test_kwargs_omit_none_fields(self) -> None:
        recipe = Recipe(name="sparse")
        kwargs = recipe.to_builder_kwargs()
        assert "model" not in kwargs
        assert "engine_key" not in kwargs
        assert "agent" not in kwargs
        assert "tools" not in kwargs
        assert "temperature" not in kwargs


class TestResolveRecipe:
    def test_resolve_recipe_found(self) -> None:
        recipe = resolve_recipe("coding_assistant")
        assert recipe is not None
        assert recipe.name == "coding_assistant"

    def test_resolve_recipe_not_found(self) -> None:
        result = resolve_recipe("nonexistent_recipe_xyz")
        assert result is None
