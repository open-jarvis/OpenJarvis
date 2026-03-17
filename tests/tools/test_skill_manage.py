from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


def test_skill_create(skills_dir: Path):
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=skills_dir)
    result = tool.execute(
        action="create",
        name="api_health",
        description="Check API health",
        steps=[
            {
                "tool_name": "http_request",
                "arguments_template": '{"url": "{endpoint}/health"}',
            }
        ],
    )
    assert result.success
    assert (skills_dir / "api_health.toml").exists()


def test_skill_list(skills_dir: Path):
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=skills_dir)
    tool.execute(
        action="create",
        name="skill_a",
        description="Skill A",
        steps=[{"tool_name": "calculator"}],
    )
    tool.execute(
        action="create",
        name="skill_b",
        description="Skill B",
        steps=[{"tool_name": "calculator"}],
    )
    result = tool.execute(action="list")
    assert "skill_a" in result.content
    assert "skill_b" in result.content


def test_skill_delete(skills_dir: Path):
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=skills_dir)
    tool.execute(
        action="create",
        name="temp_skill",
        description="Temp",
        steps=[{"tool_name": "calculator"}],
    )
    assert (skills_dir / "temp_skill.toml").exists()
    result = tool.execute(action="delete", name="temp_skill")
    assert result.success
    assert not (skills_dir / "temp_skill.toml").exists()


def test_skill_load(skills_dir: Path):
    from openjarvis.tools.skill_manage import SkillManageTool

    tool = SkillManageTool(skills_dir=skills_dir)
    tool.execute(
        action="create",
        name="my_skill",
        description="My skill desc",
        steps=[
            {
                "tool_name": "web_search",
                "arguments_template": '{"q": "test"}',
            }
        ],
    )
    result = tool.execute(action="load", name="my_skill")
    assert "web_search" in result.content
    assert "My skill desc" in result.content
