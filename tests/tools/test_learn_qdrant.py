"""Tests for learn_qdrant tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openjarvis.core.types import ToolResult
from openjarvis.tools.learn_qdrant import LearnQdrantTool


def test_learn_qdrant_requires_text():
    tool = LearnQdrantTool()
    r = tool.execute(text="   ")
    assert r.success is False
    assert "No text" in r.content


def test_learn_qdrant_no_mcp():
    tool = LearnQdrantTool()
    with patch(
        "openjarvis.tools.learn_qdrant._discover_qdrant_store_adapters",
        return_value=[],
    ):
        r = tool.execute(text="hello world " * 50, source="https://example.com")
    assert r.success is False
    assert "qdrant-store" in r.content


def test_learn_qdrant_stores_chunks():
    calls: list[dict] = []

    class FakeStore:
        def execute(self, **kwargs):
            calls.append(kwargs)
            return ToolResult(
                tool_name="qdrant-store",
                content="ok",
                success=True,
            )

    tool = LearnQdrantTool()
    with patch(
        "openjarvis.tools.learn_qdrant._discover_qdrant_store_adapters",
        return_value=[FakeStore()],
    ):
        para = " ".join(f"w{i}" for i in range(60))
        body = para + "\n\n" + para + "\n\n"
        r = tool.execute(text=body, source="test:doc", origin="file_read")

    assert r.success is True
    assert "Stored" in r.content
    assert len(calls) >= 1
    assert all("information" in c for c in calls)
    assert calls[0]["metadata"]["source"] == "test:doc"
    assert calls[0]["metadata"]["origin"] == "file_read"


def test_learn_qdrant_invalid_extra_metadata():
    tool = LearnQdrantTool()
    fake = MagicMock()
    fake.execute.return_value = ToolResult(
        tool_name="qdrant-store",
        content="ok",
        success=True,
    )
    with patch(
        "openjarvis.tools.learn_qdrant._discover_qdrant_store_adapters",
        return_value=[fake],
    ):
        r = tool.execute(text="hello", extra_metadata="not json")
    assert r.success is False
    assert "JSON" in r.content


def test_learn_qdrant_min_chunk_size_allows_short_notes():
    calls: list[dict] = []

    class FakeStore:
        def execute(self, **kwargs):
            calls.append(kwargs)
            return ToolResult(
                tool_name="qdrant-store",
                content="ok",
                success=True,
            )

    tool = LearnQdrantTool()
    with patch(
        "openjarvis.tools.learn_qdrant._discover_qdrant_store_adapters",
        return_value=[FakeStore()],
    ):
        r = tool.execute(
            text="short note for memory",
            source="note",
            min_chunk_size=1,
        )
    assert r.success is True
    assert len(calls) == 1
