"""Tests for the agent template loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.templates.agent_templates import (
    AgentTemplate,
    discover_templates,
    load_template,
)

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[2] / "src" / "openjarvis" / "templates" / "data"
)

VALID_AGENT_TYPES = {"simple", "orchestrator", "native_react", "monitor"}


def test_load_single_template() -> None:
    """Load a single template and verify its fields are populated."""
    path = TEMPLATES_DIR / "code-reviewer.toml"
    tpl = load_template(path)

    assert isinstance(tpl, AgentTemplate)
    assert tpl.name == "code-reviewer"
    assert tpl.description != ""
    assert tpl.system_prompt != ""
    assert tpl.agent_type == "native_react"
    assert isinstance(tpl.tools, list)
    assert len(tpl.tools) > 0
    assert isinstance(tpl.max_turns, int)
    assert isinstance(tpl.temperature, float)


def test_discover_all_templates() -> None:
    """Discover all built-in templates and verify count."""
    templates = discover_templates()
    assert len(templates) >= 15


def test_all_templates_have_required_fields() -> None:
    """Every template must have name, system_prompt, and agent type."""
    templates = discover_templates()
    for tpl in templates:
        assert tpl.name, f"Template missing name: {tpl}"
        assert tpl.system_prompt, f"Template '{tpl.name}' missing system_prompt"
        assert tpl.agent_type, f"Template '{tpl.name}' missing agent type"


def test_all_templates_have_valid_agent_type() -> None:
    """Agent type must be one of the known types."""
    templates = discover_templates()
    for tpl in templates:
        assert tpl.agent_type in VALID_AGENT_TYPES, (
            f"Template '{tpl.name}' has invalid agent_type '{tpl.agent_type}'. "
            f"Expected one of {VALID_AGENT_TYPES}"
        )


def test_template_missing_file_raises() -> None:
    """Loading a non-existent template file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_template("/tmp/nonexistent_template_12345.toml")
