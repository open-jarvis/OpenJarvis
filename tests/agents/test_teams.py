"""Persistence and compatibility tests for organizational agent teams."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.agents.manager import _CREATE_AGENTS, AgentManager
from openjarvis.server.agent_manager_routes import create_agent_manager_router


@pytest.fixture
def manager(tmp_path):
    manager = AgentManager(str(tmp_path / "agents.db"))
    yield manager
    manager.close()


@pytest.fixture
def client(manager):
    app = FastAPI()
    for router in create_agent_manager_router(manager):
        app.include_router(router)
    return TestClient(app)


def test_migrates_legacy_database_and_persists_membership(tmp_path):
    path = str(tmp_path / "legacy.db")
    with sqlite3.connect(path) as connection:
        connection.execute(_CREATE_AGENTS)
        connection.execute(
            "INSERT INTO managed_agents "
            "(id,name,agent_type,config_json,status,created_at,updated_at) "
            "VALUES ('legacy','Existing','monitor_operative','{}','idle',1,1)"
        )
    manager = AgentManager(path)
    assert manager.get_agent("legacy")["team_id"] is None
    team = manager.create_team("سوفت باك")
    manager.update_agent("legacy", team_id=team["id"])
    manager.close()
    manager = AgentManager(path)
    assert manager.get_agent("legacy")["team_id"] == team["id"]
    assert manager.list_teams()[0]["name"] == "سوفت باك"
    manager.close()


def test_rename_delete_preserve_agents_tasks_messages_config(manager):
    team = manager.create_team("Client")
    agent = manager.create_agent(
        "Planner", config={"instruction": "Keep me"}, team_id=team["id"]
    )
    task = manager.create_task(agent["id"], "Campaign")
    manager.send_message(agent["id"], "Existing conversation")
    assert manager.rename_team(team["id"], "New name")["id"] == team["id"]
    assert manager.get_agent(agent["id"])["team_id"] == team["id"]
    manager.delete_team(team["id"])
    kept = manager.get_agent(agent["id"])
    assert kept["team_id"] is None
    assert kept["config"]["instruction"] == "Keep me"
    assert manager.list_tasks(agent["id"])[0]["id"] == task["id"]
    assert manager.list_messages(agent["id"])
    assert manager.list_teams() == []


def test_filters_and_rejects_unknown_team(manager):
    team = manager.create_team("A")
    assigned = manager.create_agent("A", team_id=team["id"])
    unassigned = manager.create_agent("B")
    assert len(manager.list_agents()) == 2
    assert [a["id"] for a in manager.list_agents(team_id=team["id"])] == [
        assigned["id"]
    ]
    assert [a["id"] for a in manager.list_agents(team_id="")] == [unassigned["id"]]
    with pytest.raises(ValueError, match="Team not found"):
        manager.create_agent("Invalid", team_id="missing")
    with pytest.raises(ValueError, match="Team not found"):
        manager.update_agent(assigned["id"], team_id="missing")
    assert manager.get_agent(assigned["id"])["team_id"] == team["id"]


def test_team_name_validation(manager):
    manager.create_team("  Client  ")
    with pytest.raises(ValueError, match="already exists"):
        manager.create_team("client")
    for name in (" ", "x" * 121):
        with pytest.raises(ValueError):
            manager.create_team(name)
    with pytest.raises(KeyError):
        manager.rename_team("missing", "Name")
    with pytest.raises(KeyError):
        manager.delete_team("missing")


def test_team_api_and_agent_membership(client):
    assert client.get("/v1/managed-agents/teams").json() == {"teams": []}
    response = client.post("/v1/managed-agents/teams", json={"name": "شركة"})
    assert response.status_code == 201
    team = response.json()
    response = client.post(
        "/v1/managed-agents", json={"name": "Copy", "team_id": team["id"]}
    )
    assert response.status_code == 200
    agent = response.json()
    assert agent["team_id"] == team["id"]
    endpoint = f"/v1/managed-agents/{agent['id']}"
    assert (
        client.patch(endpoint, json={"name": "Renamed"}).json()["team_id"] == team["id"]
    )
    assert client.patch(endpoint, json={"team_id": "missing"}).status_code == 400
    assert client.patch(endpoint, json={"team_id": None}).json()["team_id"] is None
    assert client.patch(endpoint, json={"team_id": team["id"]}).status_code == 200
    assert (
        len(
            client.get("/v1/managed-agents", params={"team_id": team["id"]}).json()[
                "agents"
            ]
        )
        == 1
    )
    assert (
        client.get("/v1/managed-agents", params={"team_id": ""}).json()["agents"] == []
    )
    assert (
        client.patch(
            f"/v1/managed-agents/teams/{team['id']}", json={"name": "New"}
        ).status_code
        == 200
    )
    assert client.delete(f"/v1/managed-agents/teams/{team['id']}").status_code == 200
    assert client.get(endpoint).json()["team_id"] is None


def test_api_validation_and_template_membership(client):
    assert (
        client.post("/v1/managed-agents/teams", json={"name": " "}).status_code == 400
    )
    team = client.post("/v1/managed-agents/teams", json={"name": "A"}).json()
    assert (
        client.post("/v1/managed-agents/teams", json={"name": "a"}).status_code == 400
    )
    assert (
        client.patch("/v1/managed-agents/teams/missing", json={"name": "B"}).status_code
        == 404
    )
    assert client.delete("/v1/managed-agents/teams/missing").status_code == 404
    for template in (None, "research_monitor"):
        payload = {"name": "Agent", "team_id": "missing"}
        if template:
            payload["template_id"] = template
        assert client.post("/v1/managed-agents", json=payload).status_code == 400
    agent = client.post(
        "/v1/managed-agents",
        json={
            "name": "Research",
            "template_id": "research_monitor",
            "team_id": team["id"],
        },
    ).json()
    assert agent["team_id"] == team["id"]
    assert "team_id" not in agent["config"]
