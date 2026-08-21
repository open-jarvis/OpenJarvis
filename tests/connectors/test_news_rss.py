"""Tests for NewsRSSConnector — RSS/Atom feed aggregator."""

from __future__ import annotations

import os
import socket
import stat
from datetime import datetime
from unittest.mock import MagicMock, patch

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


def test_configure_rejects_private_network_feed(tmp_path):
    from openjarvis.connectors.news_rss import NewsRSSConnector

    connector = NewsRSSConnector(config_path=str(tmp_path / "feeds.json"))
    with pytest.raises(ValueError, match="not allowed"):
        connector.configure([{"url": "http://127.0.0.1:8080/private.xml"}])
    assert not (tmp_path / "feeds.json").exists()


def test_fetch_feed_rechecks_redirect_target():
    from openjarvis.connectors.news_rss import _fetch_feed

    redirect = MagicMock()
    redirect.status_code = 302
    redirect.headers = {"location": "http://169.254.169.254/latest/meta-data"}

    with (
        patch(
            "openjarvis.connectors.news_rss._validate_feed_url",
            side_effect=[MagicMock(), ValueError("RSS feed URL is not allowed")],
        ),
        patch(
            "openjarvis.connectors.news_rss._request_feed",
            return_value=redirect,
        ) as request_feed,
        pytest.raises(ValueError, match="not allowed"),
    ):
        _fetch_feed("https://example.com/feed.xml")

    request_feed.assert_called_once()


def test_fetch_feed_pins_the_verified_address_against_dns_rebinding():
    from openjarvis.connectors.news_rss import _fetch_feed

    public_answer = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("93.184.216.34", 80),
        )
    ]
    rebound_private_answer = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("127.0.0.1", 80),
        )
    ]
    calls: list[dict[str, object]] = []

    class _Response:
        status = 200

        def read(self, _limit):
            return _SAMPLE_RSS.encode()

        def getheaders(self):
            return [("Content-Type", "application/rss+xml; charset=utf-8")]

    class _Connection:
        def __init__(self, host, port, *, pinned_ip, timeout):
            calls.append(
                {
                    "host": host,
                    "port": port,
                    "pinned_ip": pinned_ip,
                    "timeout": timeout,
                }
            )

        def request(self, method, target, *, headers):
            calls[-1].update(method=method, target=target, headers=headers)

        def getresponse(self):
            return _Response()

        def close(self):
            pass

    with (
        patch("openjarvis.security.ssrf.check_ssrf", return_value=None),
        patch(
            "openjarvis.connectors.news_rss.socket.getaddrinfo",
            side_effect=[public_answer, rebound_private_answer],
        ) as resolve,
        patch(
            "openjarvis.connectors.news_rss._PinnedHTTPConnection",
            _Connection,
        ),
    ):
        xml = _fetch_feed("http://feeds.example/rss.xml")

    assert "Test Feed" in xml
    assert resolve.call_count == 1
    assert calls[0]["host"] == "feeds.example"
    assert calls[0]["pinned_ip"] == "93.184.216.34"
    assert calls[0]["headers"]["Host"] == "feeds.example"


def test_fetch_feed_rejects_private_answer_after_initial_ssrf_check():
    from openjarvis.connectors.news_rss import _fetch_feed

    private_answer = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("127.0.0.1", 80),
        )
    ]
    with (
        patch("openjarvis.security.ssrf.check_ssrf", return_value=None),
        patch(
            "openjarvis.connectors.news_rss.socket.getaddrinfo",
            return_value=private_answer,
        ),
        patch("openjarvis.connectors.news_rss._PinnedHTTPConnection") as connection,
        pytest.raises(ValueError, match="non-public IP"),
    ):
        _fetch_feed("http://feeds.example/rss.xml")

    connection.assert_not_called()


def test_https_connection_uses_url_hostname_for_tls_sni():
    from openjarvis.connectors.news_rss import _PinnedHTTPSConnection

    raw_socket = MagicMock()
    tls_socket = MagicMock()
    ssl_context = MagicMock()
    ssl_context.wrap_socket.return_value = tls_socket

    with patch(
        "openjarvis.connectors.news_rss.socket.create_connection",
        return_value=raw_socket,
    ) as create_connection:
        connection = _PinnedHTTPSConnection(
            "feeds.example",
            443,
            pinned_ip="93.184.216.34",
            timeout=30.0,
            context=ssl_context,
        )
        connection.connect()

    create_connection.assert_called_once_with(
        ("93.184.216.34", 443),
        30.0,
        None,
    )
    ssl_context.wrap_socket.assert_called_once_with(
        raw_socket,
        server_hostname="feeds.example",
    )
    assert connection.sock is tls_socket


def test_configure_writes_private_atomic_config(tmp_path):
    from openjarvis.connectors.news_rss import NewsRSSConnector

    path = tmp_path / "feeds.json"
    connector = NewsRSSConnector(config_path=str(path))
    with (
        patch("openjarvis.security.ssrf.check_ssrf", return_value=None),
        patch(
            "openjarvis.connectors.news_rss._resolve_host_addresses",
            return_value=("93.184.216.34",),
        ),
    ):
        connector.configure([{"url": "https://example.com/feed.xml"}])

    assert connector.is_connected()
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
