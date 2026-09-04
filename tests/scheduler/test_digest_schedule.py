"""Tests for digest schedule integration — CLI and API endpoints."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner

from openjarvis.cli.digest_cmd import digest

# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------


class TestDigestScheduleCLI:
    """Tests for the ``jarvis digest --schedule`` flag."""

    def test_schedule_show_status(self):
        """``--schedule ""`` shows the current schedule from config."""
        mock_cfg = MagicMock()
        mock_cfg.digest.enabled = True
        mock_cfg.digest.schedule = "0 6 * * *"
        mock_cfg.digest.timezone = "America/Los_Angeles"

        runner = CliRunner()
        with patch("openjarvis.cli.digest_cmd.load_config", return_value=mock_cfg):
            result = runner.invoke(digest, ["--schedule", ""])

        assert result.exit_code == 0
        assert "enabled" in result.output
        assert "0 6 * * *" in result.output

    def test_schedule_set_cron(self, tmp_path):
        """``--schedule "0 7 * * *"`` saves the schedule and creates a task."""
        mock_cfg = MagicMock()
        mock_cfg.digest.enabled = False
        mock_cfg.digest.schedule = "0 6 * * *"
        mock_cfg.digest.timezone = "America/Los_Angeles"

        config_path = tmp_path / "config.toml"
        config_path.write_text("")

        runner = CliRunner()
        with (
            patch(
                "openjarvis.cli.digest_cmd.load_config",
                return_value=mock_cfg,
            ),
            patch(
                "openjarvis.cli.digest_cmd.DEFAULT_CONFIG_PATH",
                config_path,
            ),
            patch(
                "openjarvis.cli.digest_cmd._create_scheduler_task",
                return_value="abc123",
            ) as mock_create,
        ):
            result = runner.invoke(digest, ["--schedule", "0 7 * * *"])

        assert result.exit_code == 0
        assert "0 7 * * *" in result.output
        assert "abc123" in result.output
        mock_create.assert_called_once_with("0 7 * * *", "America/Los_Angeles")

        # Verify config was written
        content = config_path.read_text()
        assert "enabled = true" in content
        assert '"0 7 * * *"' in content

    def test_schedule_off(self):
        """``--schedule off`` disables the schedule."""
        mock_cfg = MagicMock()
        mock_cfg.digest.enabled = True
        mock_cfg.digest.schedule = "0 6 * * *"
        mock_cfg.digest.timezone = "America/Los_Angeles"

        runner = CliRunner()
        with (
            patch(
                "openjarvis.cli.digest_cmd.load_config",
                return_value=mock_cfg,
            ),
            patch("openjarvis.cli.digest_cmd._save_digest_schedule") as mock_save,
            patch(
                "openjarvis.cli.digest_cmd._cancel_scheduler_tasks",
                return_value=1,
            ),
        ):
            result = runner.invoke(digest, ["--schedule", "off"])

        assert result.exit_code == 0
        assert "disabled" in result.output.lower()
        mock_save.assert_called_once_with(enabled=False, cron="0 6 * * *")

    def test_scheduler_task_persists_digest_timezone(self, tmp_path):
        from openjarvis.cli import digest_cmd
        from openjarvis.scheduler.store import SchedulerStore

        config_path = tmp_path / "config.toml"
        with patch("openjarvis.cli.digest_cmd.DEFAULT_CONFIG_PATH", config_path):
            task_id = digest_cmd._create_scheduler_task(
                "0 6 * * *",
                "America/Los_Angeles",
            )

        assert task_id is not None
        store = SchedulerStore(tmp_path / "scheduler.db")
        task = store.get_task(task_id)
        store.close()

        assert task is not None
        assert task["metadata"] == {"timezone": "America/Los_Angeles"}
        next_run = datetime.fromisoformat(task["next_run"])
        local_next_run = next_run.astimezone(ZoneInfo("America/Los_Angeles"))
        assert (local_next_run.hour, local_next_run.minute) == (6, 0)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

_skip_no_fastapi = pytest.importorskip("fastapi")


class TestDigestScheduleEndpoints:
    """Tests for GET/POST /api/digest/schedule."""

    @pytest.fixture()
    def client(self):
        """Create a test client with digest routes."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from openjarvis.server.digest_routes import create_digest_router

        app = FastAPI()
        app.include_router(create_digest_router())
        return TestClient(app)

    def test_schedule_endpoint_returns_config(self, client):
        """GET /api/digest/schedule returns enabled and cron from config."""
        mock_cfg = MagicMock()
        mock_cfg.digest.enabled = True
        mock_cfg.digest.schedule = "0 6 * * *"

        with patch(
            "openjarvis.server.digest_routes.load_config",
            return_value=mock_cfg,
        ):
            resp = client.get("/api/digest/schedule")

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["cron"] == "0 6 * * *"

    def test_schedule_endpoint_update(self, client):
        """POST /api/digest/schedule updates the config."""
        mock_cfg = MagicMock()
        mock_cfg.digest.enabled = False
        mock_cfg.digest.schedule = "0 6 * * *"
        mock_cfg.digest.timezone = "America/Los_Angeles"

        with (
            patch(
                "openjarvis.server.digest_routes.load_config",
                return_value=mock_cfg,
            ),
            patch("openjarvis.server.digest_routes._save_digest_schedule") as mock_save,
            patch(
                "openjarvis.server.digest_routes._create_scheduler_task",
                return_value="task123",
            ) as mock_create,
        ):
            resp = client.post(
                "/api/digest/schedule",
                json={"enabled": True, "cron": "30 7 * * 1-5"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["cron"] == "30 7 * * 1-5"
        mock_save.assert_called_once_with(enabled=True, cron="30 7 * * 1-5")
        mock_create.assert_called_once_with(
            "30 7 * * 1-5",
            "America/Los_Angeles",
        )

    def test_schedule_endpoint_disable(self, client):
        """POST /api/digest/schedule with enabled=false cancels tasks."""
        mock_cfg = MagicMock()
        mock_cfg.digest.enabled = True
        mock_cfg.digest.schedule = "0 6 * * *"

        with (
            patch(
                "openjarvis.server.digest_routes.load_config",
                return_value=mock_cfg,
            ),
            patch("openjarvis.server.digest_routes._save_digest_schedule") as mock_save,
            patch(
                "openjarvis.server.digest_routes._cancel_scheduler_tasks",
                return_value=1,
            ) as mock_cancel,
        ):
            resp = client.post(
                "/api/digest/schedule",
                json={"enabled": False},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["cron"] == "0 6 * * *"
        mock_save.assert_called_once_with(enabled=False, cron="0 6 * * *")
        mock_cancel.assert_called_once()
