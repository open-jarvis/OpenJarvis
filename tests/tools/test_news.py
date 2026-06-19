"""Tests for the news tool (network mocked)."""

from __future__ import annotations

from unittest.mock import patch

from openjarvis.tools.news import NewsTool

_RSS = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Top stories</title>
    <item>
      <title>Headline One</title>
      <link>https://news.example/1</link>
      <source url="https://src.example">Example Source</source>
      <pubDate>Fri, 05 Jun 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Headline Two</title>
      <link>https://news.example/2</link>
      <pubDate>Fri, 05 Jun 2026 13:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


class _Resp:
    def __init__(self, content=b"", json_data=None):
        self.content = content
        self._json = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json


class _Client:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, params=None):
        self.calls.append((url, params))
        return self._responses.pop(0)


def test_spec(monkeypatch):
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    tool = NewsTool()
    assert tool.spec.name == "news"
    assert tool.spec.category == "information"
    assert tool.spec.parameters["required"] == []


def test_top_headlines_rss(monkeypatch):
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    client = _Client([_Resp(content=_RSS)])
    with patch("httpx.Client", return_value=client):
        result = NewsTool().execute()
    assert result.success is True
    assert "Top headlines:" in result.content
    assert "Headline One" in result.content
    assert "Headline Two" in result.content
    assert "Example Source" in result.content
    assert result.metadata["engine"] == "google_rss"
    # No query → top RSS feed
    url, _ = client.calls[0]
    assert url.endswith("/rss")


def test_search_rss_with_query(monkeypatch):
    monkeypatch.delenv("NEWSAPI_KEY", raising=False)
    client = _Client([_Resp(content=_RSS)])
    with patch("httpx.Client", return_value=client):
        result = NewsTool().execute(query="space", max_results=1)
    assert result.success is True
    assert "Top news for 'space':" in result.content
    # max_results=1 should trim to a single item
    assert "Headline One" in result.content
    assert "Headline Two" not in result.content
    url, params = client.calls[0]
    assert "search" in url
    assert params["q"] == "space"


def test_newsapi_used_when_key_present(monkeypatch):
    monkeypatch.setenv("NEWSAPI_KEY", "fake-key")
    payload = {
        "articles": [
            {
                "title": "API Headline",
                "source": {"name": "NewsAPI Src"},
                "publishedAt": "2026-06-05T12:00:00Z",
                "url": "https://newsapi.example/a",
            }
        ]
    }
    client = _Client([_Resp(json_data=payload)])
    with patch("httpx.Client", return_value=client):
        result = NewsTool().execute(query="ai")
    assert result.success is True
    assert "API Headline" in result.content
    assert result.metadata["engine"] == "newsapi"
    url, params = client.calls[0]
    assert "newsapi.org" in url
    assert params["apiKey"] == "fake-key"
