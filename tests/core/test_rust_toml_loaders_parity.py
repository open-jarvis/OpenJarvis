"""Regression tests for Rust TOML loaders parity with Python loaders (#1175)."""

from __future__ import annotations

from pathlib import Path

import openjarvis_rust as r

from openjarvis.recipes.loader import load_recipe as py_load_recipe
from openjarvis.skills.loader import load_skill as py_load_skill
from openjarvis.templates.agent_templates import load_template as py_load_template

ROOT_DIR = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT_DIR / "src" / "openjarvis" / "templates" / "data"
RECIPES_DIR = ROOT_DIR / "src" / "openjarvis" / "recipes" / "data"
SKILLS_DIR = ROOT_DIR / "src" / "openjarvis" / "skills" / "data"


def test_rust_template_loader_all_shipped_files() -> None:
    template_files = sorted(TEMPLATES_DIR.glob("*.toml"))
    assert len(template_files) == 16

    for path in template_files:
        content = path.read_text(encoding="utf-8")
        py_tpl = py_load_template(path)
        rust_tpl = r.load_template(content)

        assert rust_tpl.name == py_tpl.name
        assert rust_tpl.description == py_tpl.description
        assert rust_tpl.system_prompt == py_tpl.system_prompt
        assert rust_tpl.agent_type == py_tpl.agent_type
        assert rust_tpl.tools == py_tpl.tools
        assert rust_tpl.max_turns == py_tpl.max_turns
        assert abs(rust_tpl.temperature - py_tpl.temperature) < 1e-6


def test_rust_recipe_loader_all_shipped_files() -> None:
    recipe_files = sorted(RECIPES_DIR.glob("*.toml"))
    operator_files = sorted((RECIPES_DIR / "operators").glob("*.toml"))
    all_files = recipe_files + operator_files
    assert len(all_files) == 16

    for path in all_files:
        content = path.read_text(encoding="utf-8")
        py_rec = py_load_recipe(path)
        rust_rec = r.load_recipe(content)

        assert rust_rec.name == py_rec.name
        assert rust_rec.model == py_rec.model
        assert rust_rec.engine_key == py_rec.engine_key
        assert rust_rec.agent_type == py_rec.agent_type
        assert rust_rec.max_turns == py_rec.max_turns
        if py_rec.temperature is not None and rust_rec.temperature is not None:
            assert abs(rust_rec.temperature - py_rec.temperature) < 1e-6


def test_rust_skill_loader_all_shipped_files() -> None:
    skill_files = sorted(SKILLS_DIR.glob("*.toml"))
    assert len(skill_files) == 20

    for path in skill_files:
        content = path.read_text(encoding="utf-8")
        py_sk = py_load_skill(path)
        rust_sk = r.load_skill(content)

        assert rust_sk.name == py_sk.name
        assert rust_sk.version == py_sk.version
        assert rust_sk.description == py_sk.description
        assert rust_sk.author == py_sk.author
        assert rust_sk.steps_count == len(py_sk.steps)
        assert rust_sk.required_capabilities == py_sk.required_capabilities
