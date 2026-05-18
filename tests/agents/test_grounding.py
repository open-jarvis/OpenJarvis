"""Tests for web grounding heuristics."""

from __future__ import annotations

from openjarvis.agents.grounding import query_needs_web_search


def test_news_queries_need_web() -> None:
    assert query_needs_web_search("znajdź mi wiadomości ze świata")
    assert query_needs_web_search("latest world news please")
    assert query_needs_web_search("za pomocą web-search znajdź wiadomości")


def test_meta_questions_skip_web() -> None:
    assert not query_needs_web_search("czy używasz web-search?")


def test_plain_chat_skips_web() -> None:
    assert not query_needs_web_search("napisz funkcję sortowania w Pythonie")
