"""Tests for HackerNewsConnector — HN Firebase API."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def test_hackernews_registered():
    """HackerNewsConnector is discoverable via ConnectorRegistry."""
    from openjarvis.connectors.hackernews import HackerNewsConnector

    ConnectorRegistry.register_value("hackernews", HackerNewsConnector)
    assert ConnectorRegistry.contains("hackernews")
    cls = ConnectorRegistry.get("hackernews")
    assert cls.connector_id == "hackernews"
    assert cls.auth_type == "local"


_TOP_STORY_IDS = [101, 102, 103, 104, 105, 106, 107]

_STORY_ITEMS = {
    101: {
        "id": 101,
        "title": "Show HN: A new Rust web framework",
        "score": 350,
        "descendants": 120,
        "url": "https://example.com/rust-framework",
        "by": "rustdev",
        "time": 1743523200,
    },
    102: {
        "id": 102,
        "title": "Why SQLite is the future of edge computing",
        "score": 210,
        "descendants": 85,
        "url": "https://example.com/sqlite-edge",
        "by": "dbfan",
        "time": 1743523300,
    },
    103: {
        "id": 103,
        "title": "Launch HN: AI agent startup",
        "score": 180,
        "descendants": 60,
        "url": "",
        "by": "founder",
        "time": 1743523400,
    },
    104: {
        "id": 104,
        "title": "Understanding memory-mapped files",
        "score": 95,
        "descendants": 30,
        "url": "https://example.com/mmap",
        "by": "sysprog",
        "time": 1743523500,
    },
    105: {
        "id": 105,
        "title": "Open-source LLM benchmarks are broken",
        "score": 420,
        "descendants": 200,
        "url": "https://example.com/llm-benchmarks",
        "by": "mlresearcher",
        "time": 1743523600,
    },
}


@pytest.fixture()
def connector():
    from openjarvis.connectors.hackernews import HackerNewsConnector

    return HackerNewsConnector()


def test_is_connected(connector):
    assert connector.is_connected() is True


def test_sync_yields_top_five(connector):
    """Sync returns Documents for the top 5 stories."""

    def mock_item(item_id):
        return _STORY_ITEMS[item_id]

    with (
        patch(
            "openjarvis.connectors.hackernews._hn_top_story_ids",
            return_value=_TOP_STORY_IDS,
        ),
        patch(
            "openjarvis.connectors.hackernews._hn_item",
            side_effect=mock_item,
        ),
    ):
        docs = list(connector.sync())

    assert len(docs) == 5
    assert all(isinstance(d, Document) for d in docs)

    first = docs[0]
    assert first.source == "hackernews"
    assert first.doc_type == "story"
    assert first.title == "Show HN: A new Rust web framework"
    assert "Score: 350" in first.content
    assert "Comments: 120" in first.content
    assert first.author == "rustdev"
    assert first.url == "https://example.com/rust-framework"

    # Story with empty URL should have url=None
    third = docs[2]
    assert third.url is None


def test_disconnect_is_noop(connector):
    """Disconnect should succeed without error."""
    connector.disconnect()
    assert connector.is_connected() is True
