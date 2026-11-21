"""Team accounts never borrow global credentials or another team's session."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.agents.team_tools import ManagedSendTool, TeamMCPTool
from openjarvis.agents.tool_resolver import (
    ensure_registries_populated,
    resolve_agent_tools,
)
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import ToolSpec


@pytest.fixture
def manager(tmp_path):
    value = AgentManager(str(tmp_path / "agents.db"))
    yield value
    value.close()


def connection(manager, team, token="company-token"):
    return manager.create_team_connection(
        team["id"],
        name="Company Gmail",
        provider="Gmail",
        url="https://mcp.example.test/mcp",
        token=token,
    )


def test_same_mcp_different_accounts_never_share_client_or_global(manager, monkeypatch):
    ensure_registries_populated()
    from openjarvis.mcp import client, transport
    from openjarvis.tools import mcp_adapter

    teams = [manager.create_team("Company A"), manager.create_team("Company B")]
    agents = [manager.create_agent("Employee", team_id=t["id"]) for t in teams]
    connections = [
        connection(manager, teams[0], "token-a"),
        connection(manager, teams[1], "token-b"),
    ]
    seen = []

    def build_transport(url, *, token, **kwargs):
        seen.append((url, token))
        return Mock(account=token)

    def build_client(value):
        return Mock(transport=value)

    def provider(value):
        tool = Mock()
        tool.spec = ToolSpec(name="gmail_read", description="Read mail", parameters={})
        tool.execute.return_value = ToolResult(
            tool_name="gmail_read", success=True, content=value.transport.account
        )
        return Mock(discover=Mock(return_value=[tool]))

    monkeypatch.setattr(transport, "StreamableHTTPTransport", build_transport)
    monkeypatch.setattr(client, "MCPClient", build_client)
    monkeypatch.setattr(mcp_adapter, "MCPToolProvider", provider)
    global_tool = Mock()
    global_tool.spec = ToolSpec(name="gmail_read", description="Global", parameters={})
    kits = [
        resolve_agent_tools(
            a, manager=manager, engine=None, model="", mcp_tools=[global_tool]
        )
        for a in agents
    ]
    tools = [
        next(tool for tool in kit.instances if isinstance(tool, TeamMCPTool))
        for kit in kits
    ]
    assert tools[0].spec.name != tools[1].spec.name
    assert [tool.execute().content for tool in tools] == [
        "token-a",
        "token-b",
    ]
    assert seen == [
        ("https://mcp.example.test/mcp", "token-a"),
        ("https://mcp.example.test/mcp", "token-b"),
    ]
    assert kits[0].mcp_clients[0] is not kits[1].mcp_clients[0]
    global_tool.execute.assert_not_called()
    assert "token-a" not in json.dumps(manager.list_team_connections(teams[0]["id"]))
    assert (
        manager._connection_secret_path(connections[0]["id"]).stat().st_mode & 0o777
        == 0o600
    )
    manager.delete_team_connection(teams[0]["id"], connections[0]["id"])
    assert not tools[0].execute().success
    assert tools[1].execute().success
    for kit in kits:
        clients = kit.mcp_clients[:]
        kit.close()
        clients[0].close.assert_called_once()


def test_missing_auth_and_failure_do_not_fall_back(manager, monkeypatch):
    team = manager.create_team("A")
    agent = manager.create_agent("Employee", team_id=team["id"])
    connection(manager, team, "")
    global_tool = Mock()
    global_tool.spec = ToolSpec(name="gmail_read", description="Global", parameters={})
    kit = resolve_agent_tools(
        agent, manager=manager, engine=None, model="", mcp_tools=[global_tool]
    )
    assert "gmail_read" not in kit.by_name
    assert (
        manager.list_team_connections(team["id"])[0]["status"] == "needs_authentication"
    )
    kit.close()
    manager.delete_team(team["id"])
    team = manager.create_team("B")
    connection(manager, team)
    manager.update_agent(agent["id"], team_id=team["id"])
    from openjarvis.mcp import client

    monkeypatch.setattr(
        client, "MCPClient", Mock(side_effect=RuntimeError("private-token"))
    )
    kit = resolve_agent_tools(
        manager.get_agent(agent["id"]),
        manager=manager,
        engine=None,
        model="",
        mcp_tools=[global_tool],
    )
    assert "gmail_read" not in kit.by_name
    global_tool.execute.assert_not_called()
    kit.close()


def test_bilateral_messaging_revocation_and_attribution(manager):
    a, b = manager.create_team("A"), manager.create_team("B")
    source = manager.create_agent("Employee A", team_id=a["id"])
    target = manager.create_agent("Employee B", team_id=b["id"])
    send = ManagedSendTool(manager, source["id"])
    assert manager.list_agent_peers(source["id"]) == []
    assert not send.execute(target_agent_id=target["id"], message="Hello").success
    manager.update_team_policy(a["id"], communicate_with=[b["id"]])
    assert not send.execute(target_agent_id=target["id"], message="Hello").success
    manager.update_team_policy(b["id"], communicate_with=[a["id"]])
    assert send.execute(target_agent_id=target["id"], message="Hello").success
    pending = manager.get_pending_messages(target["id"])
    assert pending[0]["direction"] == "agent_to_agent"
    assert json.loads(pending[0]["content"])["source_agent_id"] == source["id"]
    assert not send.execute(
        target_agent_id=target["id"], message="Hello", source_id=target["id"]
    ).success
    manager.update_team_policy(b["id"], communicate_with=[])
    assert manager.get_pending_messages(target["id"]) == []
    assert not send.execute(target_agent_id=target["id"], message="Hello").success
    assert manager.list_messages(target["id"])[0]["status"] == "blocked"


def test_reassignment_blocks_pending_message_and_connection(manager):
    from openjarvis.agents.team_tools import TeamMCPTool

    a, b = manager.create_team("A"), manager.create_team("B")
    source = manager.create_agent("One", team_id=a["id"])
    target = manager.create_agent("Two", team_id=a["id"])
    conn = connection(manager, a)
    raw = Mock()
    raw.spec = ToolSpec(name="mail", description="mail", parameters={})
    wrapped = TeamMCPTool(raw, manager, source["id"], connection_id=conn["id"])
    manager.send_agent_message(source["id"], target["id"], "Company A data")
    manager.update_agent(target["id"], team_id=b["id"])
    manager.update_agent(source["id"], team_id=b["id"])
    assert manager.get_pending_messages(target["id"]) == []
    assert not wrapped.execute().success
    raw.execute.assert_not_called()


def test_delete_team_removes_own_secret_only(manager):
    a, b = manager.create_team("A"), manager.create_team("B")
    ca, cb = connection(manager, a), connection(manager, b)
    manager.update_team_policy(b["id"], communicate_with=[a["id"]])
    manager.delete_team(a["id"])
    assert not manager._connection_secret_path(ca["id"]).exists()
    assert manager._connection_secret_path(cb["id"]).exists()
    assert manager.get_team(b["id"])["communicate_with"] == []


def test_policy_persists_and_unassigned_has_no_peer_access(manager):
    a, b = manager.create_team("A"), manager.create_team("B")
    manager.update_team_policy(a["id"], communicate_with=[b["id"]])
    other = AgentManager(manager._db_path)
    assert other.get_team(a["id"])["communicate_with"] == [b["id"]]
    other.close()
    agent = manager.create_agent("Unassigned")
    assert manager.list_agent_peers(agent["id"]) == []
    with pytest.raises(ValueError):
        manager.update_team_policy(a["id"], communicate_with=["missing"])


def test_team_missing_runtime_fails_closed_and_global_revokes_on_assignment(manager):
    from openjarvis.agents.team_tools import GlobalMCPTool

    team = manager.create_team("A")
    agent = manager.create_agent("Employee")
    raw = Mock()
    raw.spec = ToolSpec(name="gmail_read", description="Global", parameters={})
    raw.execute.return_value = ToolResult(
        tool_name="gmail_read", success=True, content="ok"
    )
    global_bound = GlobalMCPTool(raw, manager, agent["id"])
    assert global_bound.execute().success
    manager.update_agent(agent["id"], team_id=team["id"])
    assert not global_bound.execute().success
    assert raw.execute.call_count == 1
    kit = resolve_agent_tools(
        manager.get_agent(agent["id"]), engine=None, model="", mcp_tools=[raw]
    )
    assert "gmail_read" not in kit.by_name
    kit.close()


def test_mcp_opt_out_skips_team_discovery(manager, monkeypatch):
    team = manager.create_team("A")
    agent = manager.create_agent(
        "Employee", team_id=team["id"], config={"mcp_tools": False}
    )
    discover = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr(
        "openjarvis.agents.team_tools.discover_team_connections", discover
    )
    kit = resolve_agent_tools(agent, manager=manager, engine=None, model="")
    assert "managed_connection_status" in kit.by_name
    assert not kit.mcp_clients
    discover.assert_not_called()
    kit.close()


def test_unassignment_or_team_deletion_never_enables_global_accounts(manager):
    team = manager.create_team("Company")
    agent = manager.create_agent("Employee", team_id=team["id"])
    raw = Mock()
    raw.spec = ToolSpec(name="global_mail", description="Personal", parameters={})
    manager.update_agent(agent["id"], team_id=None)
    unassigned = manager.get_agent(agent["id"])
    assert unassigned["team_scoped"]
    kit = resolve_agent_tools(
        unassigned, manager=manager, engine=None, model="", mcp_tools=[raw]
    )
    assert "global_mail" not in kit.by_name
    kit.close()
    manager.update_agent(agent["id"], team_id=team["id"])
    manager.delete_team(team["id"])
    assert manager.get_agent(agent["id"])["team_scoped"]
    kit = resolve_agent_tools(
        manager.get_agent(agent["id"]),
        manager=manager,
        engine=None,
        model="",
        mcp_tools=[raw],
    )
    assert "global_mail" not in kit.by_name
    kit.close()
