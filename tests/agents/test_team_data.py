"""Team agents keep memory, MEMORY.md and knowledge inside their own team."""

from __future__ import annotations

import os
import stat

import pytest

from openjarvis.agents.manager import AgentManager
from openjarvis.agents.team_data import team_data_dir
from openjarvis.agents.tool_resolver import resolve_agent_tools
from openjarvis.core.config import JarvisConfig, MemoryFilesConfig

MEMORY_TOOLS = {"tools": ["memory_store", "memory_search", "memory_manage"]}


@pytest.fixture
def manager(tmp_path):
    value = AgentManager(str(tmp_path / "agents.db"))
    yield value
    value.close()


@pytest.fixture
def app_config(tmp_path):
    config = JarvisConfig()
    config.memory.default_backend = "sqlite"
    config.memory_files = MemoryFilesConfig(
        soul_path=str(tmp_path / "global" / "SOUL.md"),
        memory_path=str(tmp_path / "global" / "MEMORY.md"),
        user_path=str(tmp_path / "global" / "USER.md"),
    )
    return config


@pytest.fixture
def global_backend(tmp_path):
    from openjarvis.tools.storage.sqlite import SQLiteMemory

    backend = SQLiteMemory(db_path=str(tmp_path / "global-memory.db"))
    yield backend
    backend.close()


def toolkit(manager, agent, app_config, global_backend, knowledge=None, tools=None):
    manager.update_agent(agent["id"], config=MEMORY_TOOLS if tools is None else tools)
    return resolve_agent_tools(
        manager.get_agent(agent["id"]),
        engine=None,
        model="",
        memory_backend=global_backend,
        knowledge_db_path=knowledge,
        app_config=app_config,
        manager=manager,
    )


def run(tk, name, **params):
    return tk.by_name[name].execute(**params)


def test_teams_never_share_memory_or_use_global(manager, app_config, global_backend):
    a, b = manager.create_team("Client A"), manager.create_team("Client B")
    agent_a = manager.create_agent("a", team_id=a["id"])
    agent_b = manager.create_agent("b", team_id=b["id"])
    legacy = manager.create_agent("legacy")
    global_backend.store("global launch codename aurora")

    with toolkit(manager, agent_a, app_config, global_backend) as tk:
        assert tk.data_scope.memory_backend is not global_backend
        assert run(tk, "memory_store", content="client A budget is 9000").success
        assert "aurora" not in run(tk, "memory_search", query="aurora").content
    with toolkit(manager, agent_b, app_config, global_backend) as tk:
        assert "9000" not in run(tk, "memory_search", query="budget").content
    with toolkit(manager, agent_a, app_config, global_backend) as tk:
        assert "9000" in run(tk, "memory_search", query="budget").content
    with toolkit(manager, legacy, app_config, global_backend) as tk:
        assert tk.data_scope.memory_backend is global_backend
        assert "9000" not in run(tk, "memory_search", query="budget").content
    team_dir = team_data_dir(manager, a["id"])
    assert (team_dir / "memory.db").is_file()
    if os.name == "posix":
        for path in (team_dir.parent, team_dir):
            assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_memory_file_is_per_team(manager, app_config, global_backend, tmp_path):
    a = manager.create_team("Client A")
    agent = manager.create_agent("a", team_id=a["id"])
    with toolkit(manager, agent, app_config, global_backend) as tk:
        assert run(tk, "memory_manage", action="add", entry="A prefers Arabic")
    team_file = team_data_dir(manager, a["id"]) / "MEMORY.md"
    assert "A prefers Arabic" in team_file.read_text()
    assert not (tmp_path / "global" / "MEMORY.md").exists()
    assert tk.data_scope.memory_files_config.soul_path.endswith("global/SOUL.md")


def test_unassigned_team_scoped_agent_gets_private_storage(
    manager, app_config, global_backend
):
    a = manager.create_team("Client A")
    agent = manager.create_agent("a", team_id=a["id"])
    with toolkit(manager, agent, app_config, global_backend) as tk:
        run(tk, "memory_store", content="client A secret roadmap")
    manager.update_agent(agent["id"], team_id=None)
    with toolkit(manager, agent, app_config, global_backend) as tk:
        assert tk.data_scope.team_scoped
        assert tk.data_scope.memory_backend is not global_backend
        assert "roadmap" not in run(tk, "memory_search", query="roadmap").content
        assert f"_agents/{agent['id']}" in str(tk.data_scope.knowledge_db_path)


def test_knowledge_is_per_team_and_global_store_is_not_used(
    manager, app_config, global_backend, tmp_path
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    global_knowledge = tmp_path / "knowledge.db"
    store = KnowledgeStore(db_path=global_knowledge)
    store.store("global pricing sheet zebra", source="upload", doc_id="g")
    store.close()

    app = FastAPI()
    routers = create_agent_manager_router(manager)
    for router in routers if isinstance(routers, (list, tuple)) else [routers]:
        app.include_router(router)
    client = TestClient(app)
    a, b = manager.create_team("Client A"), manager.create_team("Client B")
    response = client.post(
        f"/v1/managed-agents/teams/{a['id']}/knowledge",
        json={"title": "Brief", "content": "Client A launch date is March"},
    )
    assert response.status_code == 201
    assert client.get(f"/v1/managed-agents/teams/{a['id']}/knowledge").json() == {
        "chunks": 1
    }
    assert client.get(f"/v1/managed-agents/teams/{b['id']}/knowledge").json() == {
        "chunks": 0
    }

    tools = {"tools": ["knowledge_search"]}
    agent_a = manager.create_agent("a", team_id=a["id"])
    agent_b = manager.create_agent("b", team_id=b["id"])
    with toolkit(
        manager, agent_a, app_config, global_backend, global_knowledge, tools
    ) as tk:
        found = run(tk, "knowledge_search", query="launch").content
        assert "March" in found
        assert "zebra" not in run(tk, "knowledge_search", query="zebra").content
    with toolkit(
        manager, agent_b, app_config, global_backend, global_knowledge, tools
    ) as tk:
        result = run(tk, "knowledge_search", query="launch")
        assert "March" not in result.content
    deep = manager.create_agent("deep", agent_type="deep_research", team_id=b["id"])
    with toolkit(manager, deep, app_config, global_backend, global_knowledge, {}) as tk:
        assert "knowledge_search" not in tk.by_name  # Team B has no knowledge yet.


def test_connection_validation_error_does_not_echo_token(manager):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    app = FastAPI()
    routers = create_agent_manager_router(manager)
    for router in routers if isinstance(routers, (list, tuple)) else [routers]:
        app.include_router(router)
    client = TestClient(app)
    team = manager.create_team("Client A")
    url = f"/v1/managed-agents/teams/{team['id']}/connections"
    response = client.post(url, json={"provider": "Gmail", "token": "SECRET-TKN"})
    assert response.status_code == 422
    assert "SECRET-TKN" not in response.text
    assert response.json()["detail"][0]["loc"] == ["name"]
    response = client.post(url, content=b"{not json SECRET-TKN")
    assert response.status_code == 422 and "SECRET-TKN" not in response.text
