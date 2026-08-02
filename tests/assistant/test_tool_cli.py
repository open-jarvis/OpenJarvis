from __future__ import annotations

import pytest

from openjarvis.assistant.tool_cli import (
    _canonical_url,
    browser_research,
    desktop_note,
)


def test_desktop_tool_rejects_path_and_empty_text_before_launch() -> None:
    with pytest.raises(ValueError, match="filename"):
        desktop_note("../outside.txt", "safe")
    with pytest.raises(ValueError, match="text length"):
        desktop_note("inside.txt", "")


def test_browser_tool_rejects_empty_and_oversized_queries_before_launch() -> None:
    with pytest.raises(ValueError, match="query length"):
        browser_research("  ")
    with pytest.raises(ValueError, match="query length"):
        browser_research("x" * 301)


def test_source_urls_drop_fragments_but_preserve_query() -> None:
    assert _canonical_url("https://example.com/page?q=1#instructions") == (
        "https://example.com/page?q=1"
    )
