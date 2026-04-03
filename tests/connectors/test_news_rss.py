"""Tests for NewsRSSConnector — RSS/Atom feed aggregator."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry


def test_news_rss_registered():
    """NewsRSSConnector is discoverable via ConnectorRegistry."""
    from openjarvis.connectors.news_rss import NewsRSSConnector

    ConnectorRegistry.register_value("news_rss", NewsRSSConnector)
    assert ConnectorRegistry.contains("news_rss")
    cls = ConnectorRegistry.get("news_rss")
    assert cls.connector_id == "news_rss"
    assert cls.auth_type == "local"


_SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <item>
      <title>Article One</title>
      <description>First article about AI advancements in 2026.</description>
      <link>https://example.com/article-one</link>
      <pubDate>Wed, 01 Apr 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Article Two</title>
      <description>Second article about quantum computing breakthroughs.</description>
      <link>https://example.com/article-two</link>
      <pubDate>Wed, 01 Apr 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Article Three</title>
      <description>Third article about open source projects.</description>
      <link>https://example.com/article-three</link>
      <pubDate>Wed, 01 Apr 2026 14:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

_SAMPLE_ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Atom Entry</title>
    <summary>An atom feed entry about distributed systems.</summary>
    <link href="https://example.com/atom-entry" />
    <updated>2026-04-01T15:00:00Z</updated>
  </entry>
</feed>
"""


@pytest.fixture()
def connector(tmp_path):
    """NewsRSSConnector with fake config file."""
    import json

    from openjarvis.connectors.news_rss import NewsRSSConnector

    config_path = tmp_path / "news_rss.json"
    config_path.write_text(
        json.dumps(
            {
                "feeds": [
                    {"name": "Test Feed", "url": "https://example.com/rss.xml"},
                ]
            }
        ),
        encoding="utf-8",
    )
    return NewsRSSConnector(config_path=str(config_path))


def test_is_connected(connector):
    assert connector.is_connected() is True


def test_is_connected_no_file(tmp_path):
    from openjarvis.connectors.news_rss import NewsRSSConnector

    c = NewsRSSConnector(config_path=str(tmp_path / "missing.json"))
    assert c.is_connected() is False


def test_is_connected_empty_feeds(tmp_path):
    from openjarvis.connectors.news_rss import NewsRSSConnector

    config_path = tmp_path / "news_rss.json"
    config_path.write_text('{"feeds": []}', encoding="utf-8")
    c = NewsRSSConnector(config_path=str(config_path))
    assert c.is_connected() is False


def test_sync_rss_feed(connector):
    """Sync parses RSS XML and returns Documents."""
    with patch(
        "openjarvis.connectors.news_rss._fetch_feed",
        return_value=_SAMPLE_RSS,
    ):
        docs = list(connector.sync())

    assert len(docs) == 3
    assert all(isinstance(d, Document) for d in docs)

    first = docs[0]
    assert first.source == "news_rss"
    assert first.doc_type == "article"
    assert first.title == "Article One"
    assert "AI advancements" in first.content
    assert first.url == "https://example.com/article-one"
    assert first.metadata["feed_name"] == "Test Feed"


def test_sync_atom_feed(tmp_path):
    """Sync parses Atom XML and returns Documents."""
    import json

    from openjarvis.connectors.news_rss import NewsRSSConnector

    config_path = tmp_path / "news_rss.json"
    config_path.write_text(
        json.dumps(
            {
                "feeds": [
                    {"name": "Atom Feed", "url": "https://example.com/atom.xml"},
                ]
            }
        ),
        encoding="utf-8",
    )
    c = NewsRSSConnector(config_path=str(config_path))

    with patch(
        "openjarvis.connectors.news_rss._fetch_feed",
        return_value=_SAMPLE_ATOM,
    ):
        docs = list(c.sync())

    assert len(docs) == 1
    assert docs[0].title == "Atom Entry"
    assert "distributed systems" in docs[0].content


def test_sync_filters_by_since(connector):
    """Items older than `since` are excluded when date is parseable."""
    with patch(
        "openjarvis.connectors.news_rss._fetch_feed",
        return_value=_SAMPLE_RSS,
    ):
        # Only items after April 1 12:00 should come through
        docs = list(connector.sync(since=datetime(2026, 4, 1, 11, 0, 0)))

    assert len(docs) == 2
    assert docs[0].title == "Article Two"
    assert docs[1].title == "Article Three"


def test_disconnect(connector):
    connector.disconnect()
    assert connector.is_connected() is False
