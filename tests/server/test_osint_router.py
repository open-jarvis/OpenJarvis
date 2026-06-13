"""Tests for OSINT router endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def sample_index():
    """Minimal OSINT tool index for testing."""
    return [
        {
            "name": "Amass",
            "category": "Domain & IP OSINT",
            "description": "Subdomain enumeration",
            "url": "https://github.com/owasp-amass/amass",
            "install_command": "go install -v github.com/owasp-amass/amass/v3/...@master",
            "tags": ["subdomain", "enumeration"],
        },
        {
            "name": "theHarvester",
            "category": "Email OSINT Tools",
            "description": "Email harvesting",
            "url": "https://github.com/laramies/theHarvester",
            "install_command": "pip install theHarvester",
            "tags": ["email", "harvesting"],
        },
        {
            "name": "Shodan",
            "category": "IoT Search Engine",
            "description": "Search engine for Internet-connected devices",
            "url": "https://www.shodan.io",
            "install_command": "",
            "tags": ["iot", "search"],
        },
        {
            "name": "NmapQuick",
            "category": "Network Scanner",
            "description": "Quick port scan",
            "url": "",
            "install_command": "nmap -F {target}",
            "tags": ["port-scan"],
        },
    ]


class TestOsintRouter:
    """Tests for /v1/osint routes."""

    @pytest.fixture
    def client(self, sample_index):
        """FastAPI TestClient with mocked index."""
        pytest.importorskip("fastapi")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from openjarvis.server.osint_router import router

        app = FastAPI()
        app.include_router(router)

        with patch("openjarvis.tools.osint_arsenal.search_tool._index", sample_index):
            yield TestClient(app)

    def test_search_with_query(self, client):
        """Search returns scored results for a query."""
        resp = client.post("/v1/osint/search", json={"query": "subdomain"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert any("Amass" in r["name"] for r in data["results"])

    def test_search_category_only(self, client):
        """Category filter without query returns all tools in that category."""
        resp = client.post("/v1/osint/search", json={"query": "", "category": "Email OSINT Tools"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["name"] == "theHarvester"

    def test_categories_list(self, client):
        """GET /categories returns unique categories."""
        resp = client.get("/v1/osint/categories")
        assert resp.status_code == 200
        data = resp.json()
        assert "categories" in data
        assert "Domain & IP OSINT" in data["categories"]
        assert "Email OSINT Tools" in data["categories"]

    def test_get_tool_detail_found(self, client):
        """GET /tool/{name} returns tool details."""
        resp = client.get("/v1/osint/tool/Amass")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Amass"
        assert "subdomain" in data["description"].lower()

    def test_get_tool_detail_not_found(self, client):
        """GET /tool/{name} returns 404 for unknown tool."""
        resp = client.get("/v1/osint/tool/NonExistent")
        assert resp.status_code == 404

    def test_exec_web_tool(self, client):
        """Exec for a web tool returns URL metadata."""
        with patch("openjarvis.tools.shell_exec.ShellExecTool") as mock_shell:
            mock_shell.return_value.execute.return_value = MagicMock(
                content="Executed", success=True, metadata={}
            )
            resp = client.post("/v1/osint/exec", json={"tool_name": "Shodan", "target": "example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool"] == "Shodan"
        assert data["type"] == "web"
        assert "shodan.io" in data["output"]

    def test_exec_cli_tool(self, client):
        """Exec for a CLI tool with a run command triggers shell execution."""
        with patch("openjarvis.tools.shell_exec.ShellExecTool") as mock_shell:
            mock_shell.return_value.execute.return_value = MagicMock(
                content="stdout here", success=True, metadata={"exit_code": 0}
            )
            resp = client.post("/v1/osint/exec", json={"tool_name": "NmapQuick", "target": "example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool"] == "NmapQuick"
        assert data["type"] == "cli"
        assert "stdout here" in data["output"]

    def test_watchdog_export_json(self, client):
        """Export Watchdog results as JSON."""
        mock_result = {
            "target": "example.com",
            "timestamp": "2026-06-13T12:00:00Z",
            "modules": ["dns"],
            "results": {"dns": {"records": {"A": ["93.184.216.34"]}}},
            "summary": {"reachable": True, "privacy_protected": False, "seizure_detected": False, "errors": 0},
        }
        with patch("openjarvis.tools.fbi_watchdog.core.run_scan", return_value=mock_result):
            resp = client.post("/v1/osint/watch/export", json={"target": "example.com", "modules": ["dns"], "format": "json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "json"
        assert data["data"]["target"] == "example.com"
        assert data["filename"].endswith(".json")

    def test_watchdog_export_csv(self, client):
        """Export Watchdog results as CSV."""
        mock_result = {
            "target": "example.com",
            "timestamp": "2026-06-13T12:00:00Z",
            "modules": ["dns"],
            "results": {"dns": {"records": {"A": ["93.184.216.34"]}}},
            "summary": {"reachable": True, "privacy_protected": False, "seizure_detected": False, "errors": 0},
        }
        with patch("openjarvis.tools.fbi_watchdog.core.run_scan", return_value=mock_result):
            resp = client.post("/v1/osint/watch/export", json={"target": "example.com", "modules": ["dns"], "format": "csv"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["format"] == "csv"
        assert "module,key,value" in data["data"]
        assert data["filename"].endswith(".csv")
