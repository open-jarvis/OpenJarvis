"""End-to-end skill CLI execution and security regressions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolResult


def write_skill(root: Path, name: str, steps: list[dict]) -> None:
    folder = root / name
    folder.mkdir()
    lines = [f'[skill]\nname = "{name}"\nversion = "1.0.0"\n']
    for step in steps:
        lines.append("[[skill.steps]]")
        lines.extend(f"{key} = {json.dumps(value)}" for key, value in step.items())
    (folder / "skill.toml").write_text("\n".join(lines))


@pytest.fixture
def skill_cli(tmp_path):
    from openjarvis.core.registry import ToolRegistry
    from openjarvis.tools.calculator import CalculatorTool
    from openjarvis.tools.shell_exec import ShellExecTool

    ToolRegistry.register_value("calculator", CalculatorTool)
    ToolRegistry.register_value("shell_exec", ShellExecTool)
    cfg = JarvisConfig()
    cfg.security.audit_log_path = str(tmp_path / "audit.db")
    cfg.security.capabilities.enabled = True
    cfg.security.capabilities.default_deny = True
    cfg.security.rate_limit_enabled = False
    cfg.learning.skills.overlay_dir = str(tmp_path / "overlays")
    bus = EventBus(record_history=True)
    with (
        patch("openjarvis.cli.skill_cmd._get_skill_paths", return_value=[tmp_path]),
        patch("openjarvis.cli.skill_cmd.load_config", return_value=cfg),
        patch("openjarvis.core.config.load_config", return_value=cfg),
        patch("openjarvis.cli.skill_cmd.EventBus", return_value=bus),
    ):
        yield tmp_path, cfg, bus


def test_executes_real_registered_tool_and_nested_skill(skill_cli):
    root, _, bus = skill_cli
    write_skill(
        root,
        "child",
        [
            {
                "tool_name": "calculator",
                "arguments_template": '{"expression": "{value} + 2"}',
                "output_key": "answer",
            }
        ],
    )
    write_skill(
        root,
        "parent",
        [{"skill_name": "child", "arguments_template": '{"value": "{value}"}'}],
    )
    result = CliRunner().invoke(cli, ["skill", "run", "parent", "-a", "value=3"])
    assert result.exit_code == 0, result.output
    assert "Success" in result.output
    assert "5" in result.output
    calls = [
        event for event in bus.history if event.event_type == EventType.TOOL_CALL_START
    ]
    assert len(calls) == 1
    assert calls[0].data["agent"] == "skill:cli"


@pytest.mark.parametrize("nested", [False, True])
def test_prose_skill_is_not_reported_as_success(skill_cli, nested):
    root, _, _ = skill_cli
    folder = root / "prose"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: prose\ndescription: Instructions\n---\nRead this."
    )
    name = "prose"
    if nested:
        write_skill(root, "parent", [{"skill_name": "prose"}])
        name = "parent"
    result = CliRunner().invoke(cli, ["skill", "run", name])
    assert result.exit_code != 0
    assert "no executable steps" in result.output
    assert "Success" not in result.output


def test_respects_configured_tool_selection(skill_cli):
    root, cfg, _ = skill_cli
    cfg.tools.enabled = "think"
    write_skill(
        root,
        "calc",
        [{"tool_name": "calculator", "arguments_template": '{"expression": "2+2"}'}],
    )
    result = CliRunner().invoke(cli, ["skill", "run", "calc"])
    assert result.exit_code != 0
    assert "disabled tools: calculator" in result.output


def test_default_deny_blocks_real_shell_before_dispatch(skill_cli):
    root, cfg, bus = skill_cli
    write_skill(
        root,
        "shell",
        [
            {
                "tool_name": "shell_exec",
                "arguments_template": '{"command": "echo blocked"}',
            }
        ],
    )
    with patch("openjarvis.tools.shell_exec.ShellExecTool.execute") as execute:
        result = CliRunner().invoke(cli, ["skill", "run", "shell"], input="y\n")
    assert result.exit_code != 0
    assert "code:execute" in result.output and "denied" in result.output
    execute.assert_not_called()
    denied = [
        event
        for event in bus.history
        if event.event_type == EventType.CAPABILITY_DENIED
    ]
    assert denied[0].data["agent_id"] == "skill:cli"
    with sqlite3.connect(cfg.security.audit_log_path) as db:
        previews = db.execute("SELECT content_preview FROM security_events").fetchall()
    assert any("agent=skill:cli" in row[0] for row in previews)


@pytest.mark.parametrize("answer, expected_calls", [("y", 1), ("n", 0)])
def test_granted_shell_still_requires_user_confirmation(
    skill_cli, answer, expected_calls
):
    root, cfg, _ = skill_cli
    policy = root / "policy.json"
    policy.write_text(
        json.dumps(
            {
                "agents": [
                    {
                        "agent_id": "skill:cli",
                        "grants": [{"capability": "code:execute"}],
                    }
                ]
            }
        )
    )
    cfg.security.capabilities.policy_path = str(policy)
    write_skill(
        root,
        "shell",
        [
            {
                "tool_name": "shell_exec",
                "arguments_template": '{"command": "echo allowed"}',
            }
        ],
    )
    with patch(
        "openjarvis.tools.shell_exec.ShellExecTool.execute",
        return_value=ToolResult(
            tool_name="shell_exec",
            content="STEP_RAN",
            success=True,
        ),
    ) as execute:
        result = CliRunner().invoke(cli, ["skill", "run", "shell"], input=answer + "\n")
    assert execute.call_count == expected_calls
    assert "Allow execution" in result.output
    assert (result.exit_code == 0) is bool(expected_calls), result.output
    assert ("STEP_RAN" in result.output) is bool(expected_calls)


def test_rate_limit_applies_across_skill_steps(skill_cli):
    root, cfg, bus = skill_cli
    cfg.security.rate_limit_enabled = True
    cfg.security.rate_limit_rpm = 1
    cfg.security.rate_limit_burst = 1
    write_skill(
        root,
        "twice",
        [{"tool_name": "calculator", "arguments_template": '{"expression": "2+2"}'}]
        * 2,
    )
    result = CliRunner().invoke(cli, ["skill", "run", "twice"])
    assert result.exit_code != 0
    assert "Rate limit exceeded" in result.output
    limited = [
        event for event in bus.history if event.event_type == EventType.RATE_LIMITED
    ]
    assert limited[0].data["agent_id"] == "skill:cli"


def test_policy_startup_failure_never_dispatches(skill_cli):
    root, cfg, _ = skill_cli
    cfg.security.capabilities.policy_path = str(root / "missing-policy.json")
    write_skill(
        root,
        "shell",
        [
            {
                "tool_name": "shell_exec",
                "arguments_template": '{"command": "echo blocked"}',
            }
        ],
    )
    with patch("openjarvis.tools.shell_exec.ShellExecTool.execute") as execute:
        result = CliRunner().invoke(cli, ["skill", "run", "shell"])
    assert result.exit_code != 0
    execute.assert_not_called()


@pytest.mark.parametrize("command", [["sync"], ["sources"], ["search", "x"]])
def test_no_sources_message_keeps_literal_toml_section(skill_cli, command):
    result = CliRunner().invoke(cli, ["skill", *command])
    assert "[skills.sources]" in result.output
