"""Tests for system_prompt_template expansion in agent creation."""

from __future__ import annotations

from openjarvis.agents.manager import AgentManager


def test_create_from_template_expands_system_prompt(tmp_path):
    """system_prompt_template should be expanded with the instruction."""
    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_from_template(
        "research_monitor",
        "Test Agent",
        overrides={"instruction": "Monitor AI safety papers"},
    )
    config = agent["config"]
    # system_prompt should contain the expanded instruction
    assert "Monitor AI safety papers" in config.get("system_prompt", "")
    # system_prompt_template should NOT be in the stored config
    assert "system_prompt_template" not in config
    mgr.close()


def test_create_from_template_without_instruction(tmp_path):
    """Template with no instruction should still have a system_prompt."""
    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_from_template("research_monitor", "Test Agent")
    config = agent["config"]
    assert "system_prompt" in config
    assert len(config["system_prompt"]) > 100  # non-trivial prompt
    mgr.close()


def test_create_from_template_preserves_icon(tmp_path):
    """Template icon field should be preserved in config."""
    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_from_template("research_monitor", "Test Agent")
    config = agent["config"]
    assert config.get("icon") == "🔬"
    mgr.close()
