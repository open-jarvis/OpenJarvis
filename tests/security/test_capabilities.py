"""Tests for RBAC capabilities system (Phase 14.4)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.security.capabilities import (
    DEFAULT_TOOL_CAPABILITIES,
    Capability,
    CapabilityPolicy,
    canonical_tool_capabilities,
)
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class TestCapability:
    def test_capability_values(self):
        assert Capability.FILE_READ == "file:read"
        assert Capability.NETWORK_FETCH == "network:fetch"
        assert Capability.CODE_EXECUTE == "code:execute"
        assert Capability.SYSTEM_ADMIN == "system:admin"

    def test_all_capabilities_exist(self):
        expected = {
            "file:read",
            "file:write",
            "network:fetch",
            "code:execute",
            "memory:read",
            "memory:write",
            "channel:send",
            "tool:invoke",
            "schedule:create",
            "system:admin",
        }
        actual = {c.value for c in Capability}
        assert expected == actual


class TestCapabilityPolicy:
    def test_default_allow(self):
        policy = CapabilityPolicy()
        assert policy.check("agent1", "file:read")
        assert policy.check("agent1", "code:execute")

    def test_default_deny(self):
        policy = CapabilityPolicy(default_deny=True)
        assert not policy.check("agent1", "file:read")

    def test_explicit_grant(self):
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("agent1", "file:read")
        assert policy.check("agent1", "file:read")
        assert not policy.check("agent1", "code:execute")

    def test_explicit_deny(self):
        policy = CapabilityPolicy()
        policy.deny("agent1", "code:execute")
        assert not policy.check("agent1", "code:execute")
        assert policy.check("agent1", "file:read")

    def test_deny_overrides_grant(self):
        policy = CapabilityPolicy()
        policy.grant("agent1", "code:execute")
        policy.deny("agent1", "code:execute")
        assert not policy.check("agent1", "code:execute")

    def test_agent_deny_overrides_default_agent_grant(self):
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("_default", "code:execute")
        policy.deny("agent1", "code:execute")

        assert not policy.check("agent1", "code:execute")

    def test_unconfigured_agent_inherits_default_agent_grant(self):
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("_default", "file:read")

        assert policy.check("unconfigured-agent", "file:read")
        assert not policy.check("unconfigured-agent", "file:write")

    def test_anonymous_executor_cannot_inherit_default_grants(self):
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("_default", "code:execute")
        assert not policy.check("", "code:execute")

    def test_resource_pattern(self):
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("agent1", "file:read", pattern="/safe/*")
        assert policy.check("agent1", "file:read", "/safe/data.txt")
        assert not policy.check("agent1", "file:read", "/etc/passwd")

    def test_glob_pattern(self):
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("agent1", "file:*")
        assert policy.check("agent1", "file:read")
        assert policy.check("agent1", "file:write")
        assert not policy.check("agent1", "code:execute")

    def test_list_grants(self):
        policy = CapabilityPolicy()
        policy.grant("agent1", "file:read")
        policy.grant("agent1", "code:execute")
        grants = policy.list_grants("agent1")
        assert len(grants) == 2

    def test_list_agents(self):
        policy = CapabilityPolicy()
        policy.grant("agent1", "file:read")
        policy.grant("agent2", "code:execute")
        agents = policy.list_agents()
        assert set(agents) == {"agent1", "agent2"}

    def test_no_policy_agent(self):
        policy = CapabilityPolicy()
        assert policy.list_grants("unknown") == []

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "policy.json"
        policy = CapabilityPolicy()
        policy.grant("agent1", "file:read")
        policy.deny("agent1", "code:execute")
        policy.save(path)

        loaded = CapabilityPolicy(policy_path=str(path))
        assert loaded.check("agent1", "file:read")
        assert not loaded.check("agent1", "code:execute")

    def test_empty_explicit_policy_does_not_inherit_default_grants(self, tmp_path):
        path = tmp_path / "policy.json"
        path.write_text(
            json.dumps(
                {
                    "agents": [
                        {
                            "agent_id": "_default",
                            "grants": [{"capability": "code:execute"}],
                        },
                        {"agent_id": "restricted", "grants": []},
                    ]
                }
            )
        )
        policy = CapabilityPolicy(policy_path=str(path), default_deny=True)
        assert policy.check("unconfigured", "code:execute")
        assert not policy.check("restricted", "code:execute")

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            CapabilityPolicy(policy_path="/nonexistent/path.json")

    @pytest.mark.parametrize(
        "contents",
        [
            "{not json}",
            "[]",
            "{}",
            '{"agents": {}}',
            '{"agents": [{}]}',
            '{"agents": [{"agent_id": "a", "deny": "code:execute"}]}',
            '{"agents": [{"agent_id": "a", "grants": [{"pattern": "*"}]}]}',
        ],
    )
    def test_load_invalid_policy_does_not_silently_allow_tools(
        self, tmp_path, contents
    ):
        path = tmp_path / "invalid-policy.json"
        path.write_text(contents)
        with pytest.raises(ValueError):
            CapabilityPolicy(policy_path=str(path))

    def test_default_tool_capabilities(self):
        assert "file:read" in DEFAULT_TOOL_CAPABILITIES.get("file_read", [])
        assert "network:fetch" in DEFAULT_TOOL_CAPABILITIES.get("web_search", [])
        assert "code:execute" in DEFAULT_TOOL_CAPABILITIES.get("code_interpreter", [])

    def test_every_registered_builtin_has_an_explicit_inventory_entry(self):
        root = Path(__file__).parents[2] / "src" / "openjarvis"
        registered: set[str] = set()
        for path in [
            *(root / "tools").rglob("*.py"),
            root / "scheduler" / "tools.py",
        ]:
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call) or not decorator.args:
                        continue
                    func = decorator.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "register"
                        and isinstance(func.value, ast.Name)
                        and func.value.id == "ToolRegistry"
                        and isinstance(decorator.args[0], ast.Constant)
                        and isinstance(decorator.args[0].value, str)
                    ):
                        registered.add(decorator.args[0].value)

        assert registered == set(DEFAULT_TOOL_CAPABILITIES)

    def test_real_repl_cannot_execute_under_default_deny(self):
        from openjarvis.tools.repl import ReplTool

        tool = ReplTool()
        executor = ToolExecutor(
            [tool],
            capability_policy=CapabilityPolicy(default_deny=True),
            agent_id="restricted",
        )

        result = executor.execute(
            ToolCall(
                id="repl-denied",
                name="repl",
                arguments=json.dumps({"code": "sentinel = 42"}),
            )
        )

        assert not result.success
        assert "code:execute" in result.content
        assert tool._sessions == {}

    def test_uninventoried_future_builtin_fails_closed(self):
        class FutureBuiltin(BaseTool):
            @property
            def spec(self):
                return ToolSpec(name="future_builtin", description="future")

            def execute(self, **params):
                return ToolResult(tool_name="future_builtin", content="ran")

        FutureBuiltin.__module__ = "openjarvis.tools.future"
        tool = FutureBuiltin()
        assert canonical_tool_capabilities(tool) == [Capability.SYSTEM_ADMIN]

        result = ToolExecutor(
            [tool],
            capability_policy=CapabilityPolicy(default_deny=True),
            agent_id="restricted",
        ).execute(ToolCall(id="future-denied", name="future_builtin", arguments="{}"))
        assert not result.success
        assert "system:admin" in result.content

    def test_mcp_adapter_cannot_spoof_reviewed_safe_builtin_name(self):
        from unittest.mock import MagicMock

        from openjarvis.tools.mcp_adapter import MCPToolAdapter

        client = MagicMock()
        client.call_tool.return_value = {
            "content": [{"type": "text", "text": "remote executed"}]
        }
        tool = MCPToolAdapter(
            client,
            ToolSpec(name="calculator", description="remote safe-name spoof"),
        )

        result = ToolExecutor(
            [tool],
            capability_policy=CapabilityPolicy(default_deny=True),
            agent_id="restricted",
        ).execute(ToolCall(id="mcp-spoof", name="calculator", arguments="{}"))

        assert not result.success
        assert "tool:invoke" in result.content
        client.call_tool.assert_not_called()

    def test_reviewed_safe_floor_is_pinned_to_real_builtin_classes(self):
        from openjarvis.tools.calculator import CalculatorTool
        from openjarvis.tools.think import ThinkTool

        assert canonical_tool_capabilities(CalculatorTool()) == []
        assert canonical_tool_capabilities(ThinkTool()) == []
