"""Test that _build_deep_research_tools works correctly."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

try:
    import fastapi  # noqa: F401

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from openjarvis.connectors.store import KnowledgeStore


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_deep_research_agent_gets_tools(tmp_path: Path) -> None:
    """When knowledge.db exists, returns 4 tools."""
    db_path = tmp_path / "knowledge.db"
    store = KnowledgeStore(str(db_path))
    store.store("test content", source="test", doc_type="note")

    from openjarvis.server.agent_manager_routes import _build_deep_research_tools

    tools = _build_deep_research_tools(
        engine=MagicMock(),
        model="test-model",
        knowledge_db_path=str(db_path),
    )

    tool_ids = [t.tool_id for t in tools]
    assert "knowledge_search" in tool_ids
    assert "knowledge_sql" in tool_ids
    assert "scan_chunks" in tool_ids
    assert "think" in tool_ids
    assert len(tools) == 4
    store.close()


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_deep_research_tools_returns_empty_when_no_db() -> None:
    """When knowledge.db doesn't exist, returns empty list."""
    from openjarvis.server.agent_manager_routes import _build_deep_research_tools

    tools = _build_deep_research_tools(
        engine=MagicMock(),
        model="test-model",
        knowledge_db_path="/nonexistent/path/knowledge.db",
    )

    assert tools == []


@pytest.fixture
def registered_tools():
    """Guarantee the tools this module asserts on are in the registry.

    ``_ensure_registries_populated`` only repopulates when the registry is
    *entirely* empty, so a fixture that clears it partially can leave these
    missing depending on test order.
    """
    import importlib

    from openjarvis.core.registry import ToolRegistry

    for mod_name in ("openjarvis.tools.web_search", "openjarvis.tools.think"):
        mod = importlib.import_module(mod_name)
        if not ToolRegistry.contains(mod_name.rsplit(".", 1)[-1]):
            importlib.reload(mod)
    return ToolRegistry


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestResolveToolInstances:
    """A managed agent's configured tools must reach agents that own their loop.

    ``_build_deep_research_tools`` only supplies the knowledge-base tools. A
    deep_research agent configured with ``web_search`` used to receive none of
    it while its system prompt instructed it to search the web, so it answered
    from model memory and invented citations instead.
    """

    def test_configured_tools_are_instantiated(self, registered_tools) -> None:
        from openjarvis.server.agent_manager_routes import _resolve_tool_instances

        tools = _resolve_tool_instances(
            ["web_search", "think"],
            engine=MagicMock(),
            model="test-model",
            app_state=None,
        )

        names = {t.spec.name for t in tools}
        assert "web_search" in names
        assert "think" in names

    def test_unknown_and_empty_configs_are_safe(self) -> None:
        from openjarvis.server.agent_manager_routes import _resolve_tool_instances

        kwargs = {"engine": MagicMock(), "model": "m", "app_state": None}
        assert _resolve_tool_instances(None, **kwargs) == []
        assert _resolve_tool_instances([], **kwargs) == []
        # Unknown names are dropped rather than raising.
        assert _resolve_tool_instances(["no_such_tool_xyz"], **kwargs) == []

    def test_returns_instances_not_specs(self, registered_tools) -> None:
        """DeepResearchAgent takes live tools, unlike the engine's spec dicts."""
        from openjarvis.server.agent_manager_routes import _resolve_tool_instances

        tools = _resolve_tool_instances(
            ["think"],
            engine=MagicMock(),
            model="test-model",
            app_state=None,
        )

        assert tools and not isinstance(tools[0], dict)
        assert callable(getattr(tools[0], "execute", None))

    def test_merges_with_knowledge_tools_without_duplicates(
        self, tmp_path: Path, registered_tools
    ) -> None:
        """The two sources combine; ``think`` is in both and must appear once."""
        from openjarvis.server.agent_manager_routes import (
            _build_deep_research_tools,
            _resolve_tool_instances,
            _tool_instance_name,
        )

        db_path = tmp_path / "knowledge.db"
        store = KnowledgeStore(str(db_path))
        store.store("test content", source="test", doc_type="note")
        try:
            merged = _build_deep_research_tools(
                engine=MagicMock(),
                model="test-model",
                knowledge_db_path=str(db_path),
            )
            seen = {_tool_instance_name(t) for t in merged}
            for tool in _resolve_tool_instances(
                ["web_search", "think"],
                engine=MagicMock(),
                model="test-model",
                app_state=None,
            ):
                name = _tool_instance_name(tool)
                if name and name not in seen:
                    merged.append(tool)
                    seen.add(name)

            names = [_tool_instance_name(t) for t in merged]
            assert "web_search" in names, "web_search must reach the agent"
            assert "knowledge_search" in names, "local KB tools must be kept too"
            assert names.count("think") == 1, "overlapping tool must not duplicate"
        finally:
            store.close()
