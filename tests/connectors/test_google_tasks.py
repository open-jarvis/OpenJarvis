"""Tests for GoogleTasksConnector — Google Tasks API v1."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from openjarvis.core.registry import ConnectorRegistry


def test_google_tasks_registered():
    from openjarvis.connectors.google_tasks import GoogleTasksConnector

    ConnectorRegistry.register_value("google_tasks", GoogleTasksConnector)
    assert ConnectorRegistry.contains("google_tasks")
    cls = ConnectorRegistry.get("google_tasks")
    assert cls.connector_id == "google_tasks"
    assert cls.display_name == "Google Tasks"
    assert cls.auth_type == "oauth"


_TASK_LISTS_RESPONSE = {"items": [{"id": "list1", "title": "My Tasks"}]}

_TASKS_RESPONSE = {
    "items": [
        {
            "id": "task1",
            "title": "Review PR #42",
            "notes": "Check the auth middleware changes",
            "status": "needsAction",
            "due": "2026-04-01T00:00:00.000Z",
            "updated": "2026-03-31T20:00:00.000Z",
            "selfLink": "https://tasks.googleapis.com/tasks/v1/lists/list1/tasks/task1",
        },
        {
            "id": "task2",
            "title": "Submit expense report",
            "notes": "",
            "status": "completed",
            "due": "2026-03-31T00:00:00.000Z",
            "completed": "2026-03-31T15:00:00.000Z",
            "updated": "2026-03-31T15:00:00.000Z",
            "selfLink": "https://tasks.googleapis.com/tasks/v1/lists/list1/tasks/task2",
        },
    ]
}


@pytest.fixture()
def connector(tmp_path):
    from openjarvis.connectors.google_tasks import GoogleTasksConnector

    creds = tmp_path / "google_tasks.json"
    creds.write_text('{"token": "fake-token"}', encoding="utf-8")
    return GoogleTasksConnector(credentials_path=str(creds))


def test_sync_yields_tasks(connector):
    with patch(
        "openjarvis.connectors.google_tasks._tasks_api_get",
        side_effect=[_TASK_LISTS_RESPONSE, _TASKS_RESPONSE],
    ):
        docs = list(connector.sync(since=datetime(2026, 3, 31)))

    assert len(docs) == 2
    assert docs[0].source == "google_tasks"
    assert docs[0].doc_type == "task"
    assert docs[0].title == "Review PR #42"
    assert docs[0].metadata["status"] == "needsAction"
    assert docs[1].metadata["status"] == "completed"
