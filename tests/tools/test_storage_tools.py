"""Tests for storage MCP tools — MemoryStoreTool, MemoryRetrieveTool, etc."""

from __future__ import annotations

import os
import tempfile

import pytest

from openjarvis.mcp.server import MCPServer
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult
from openjarvis.tools.storage_tools import (
    MemoryIndexTool,
    MemoryRetrieveTool,
    MemorySearchTool,
    MemoryStoreTool,
)


class _InMemoryBackend(MemoryBackend):
    """Simple in-memory backend for testing storage tools."""

    backend_id = "test_memory"

    def __init__(self):
        self._data = {}
        self._counter = 0

    def store(self, content, *, source="", metadata=None):
        self._counter += 1
        doc_id = f"doc-{self._counter}"
        self._data[doc_id] = {"content": content, "source": source}
        return doc_id

    def retrieve(self, query, *, top_k=5, **kwargs):
        results = []
        for doc in self._data.values():
            if query.lower() in doc["content"].lower():
                results.append(
                    RetrievalResult(
                        content=doc["content"],
                        score=0.9,
                        source=doc["source"],
                    )
                )
        return results[:top_k]

    def delete(self, doc_id):
        if doc_id in self._data:
            del self._data[doc_id]
            return True
        return False

    def clear(self):
        self._data.clear()


@pytest.fixture
def backend():
    return _InMemoryBackend()


class TestMemoryStoreTool:
    def test_spec(self):
        tool = MemoryStoreTool()
        assert tool.spec.name == "memory_store"
        assert tool.spec.category == "storage"

    def test_store_success(self, backend):
        tool = MemoryStoreTool(backend)
        result = tool.execute(content="Hello world", source="test")
        assert result.success is True
        assert "doc-1" in result.content

    def test_store_no_backend(self):
        tool = MemoryStoreTool()
        result = tool.execute(content="Hello")
        assert result.success is False
        assert "No memory backend" in result.content

    def test_store_no_content(self, backend):
        tool = MemoryStoreTool(backend)
        result = tool.execute()
        assert result.success is False
        assert "No content" in result.content

    def test_tool_id(self):
        assert MemoryStoreTool.tool_id == "memory_store"


class TestMemoryRetrieveTool:
    def test_spec(self):
        tool = MemoryRetrieveTool()
        assert tool.spec.name == "memory_retrieve"

    def test_retrieve_success(self, backend):
        backend.store("Python is great", source="test")
        tool = MemoryRetrieveTool(backend)
        result = tool.execute(query="Python")
        assert result.success is True
        assert "Python is great" in result.content
        assert "0.90" in result.content

    def test_retrieve_no_results(self, backend):
        tool = MemoryRetrieveTool(backend)
        result = tool.execute(query="nonexistent")
        assert result.success is True
        assert "No results" in result.content

    def test_retrieve_no_backend(self):
        tool = MemoryRetrieveTool()
        result = tool.execute(query="test")
        assert result.success is False

    def test_retrieve_no_query(self, backend):
        tool = MemoryRetrieveTool(backend)
        result = tool.execute()
        assert result.success is False
        assert "No query" in result.content

    def test_retrieve_top_k(self, backend):
        for i in range(10):
            backend.store(f"document {i} about testing", source="test")
        tool = MemoryRetrieveTool(backend)
        result = tool.execute(query="testing", top_k=3)
        assert result.success is True
        # Should only have 3 entries separated by ---
        assert result.content.count("---") == 2


class TestMemorySearchTool:
    def test_spec(self):
        tool = MemorySearchTool()
        assert tool.spec.name == "memory_search"

    def test_search_success(self, backend):
        backend.store("Machine learning basics", source="ml.txt")
        tool = MemorySearchTool(backend)
        result = tool.execute(query="machine")
        assert result.success is True
        assert "Machine learning basics" in result.content
        assert "ml.txt" in result.content

    def test_search_no_results(self, backend):
        tool = MemorySearchTool(backend)
        result = tool.execute(query="xyz")
        assert result.success is True
        assert "No results" in result.content

    def test_search_numbered_output(self, backend):
        backend.store("First doc about AI", source="a.txt")
        backend.store("Second doc about AI", source="b.txt")
        tool = MemorySearchTool(backend)
        result = tool.execute(query="AI")
        assert result.success is True
        assert "1." in result.content
        assert "2." in result.content


class TestMemoryIndexTool:
    def test_spec(self):
        tool = MemoryIndexTool()
        assert tool.spec.name == "memory_index"

    def test_index_no_backend(self):
        tool = MemoryIndexTool()
        result = tool.execute(path="/tmp/test")
        assert result.success is False

    def test_index_no_path(self, backend):
        tool = MemoryIndexTool(backend)
        result = tool.execute()
        assert result.success is False
        assert "No path" in result.content

    def test_index_nonexistent_path(self, backend):
        tool = MemoryIndexTool(backend)
        result = tool.execute(path="/nonexistent/path/to/nothing")
        assert result.success is False
        assert "does not exist" in result.content

    def test_index_file(self, backend):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
        ) as f:
            f.write("This is test content for indexing.")
            f.flush()
            path = f.name
        try:
            tool = MemoryIndexTool(backend)
            result = tool.execute(path=path, chunk_size=512, chunk_overlap=64)
            assert result.success is True
            assert "Indexed" in result.content
        finally:
            os.unlink(path)


class TestStorageToolsRegistration:
    def test_storage_tools_importable(self):
        """All storage tools are importable and instantiable."""
        from openjarvis.tools.storage_tools import (
            MemoryIndexTool,
            MemoryRetrieveTool,
            MemorySearchTool,
            MemoryStoreTool,
        )

        # All instantiate without error (backend=None)
        assert MemoryStoreTool().spec.name == "memory_store"
        assert MemoryRetrieveTool().spec.name == "memory_retrieve"
        assert MemorySearchTool().spec.name == "memory_search"
        assert MemoryIndexTool().spec.name == "memory_index"

    def test_auto_discover_finds_storage_tools(self):
        """MCPServer auto-discovery finds storage tools."""
        server = MCPServer()
        from openjarvis.mcp.protocol import MCPRequest

        req = MCPRequest(method="tools/list", id=1)
        resp = server.handle(req)
        names = {t["name"] for t in resp.result["tools"]}
        assert "memory_store" in names
        assert "memory_retrieve" in names
