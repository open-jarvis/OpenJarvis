"""Shared tool wiring for Deep Research agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from openjarvis.core.config import DEFAULT_CONFIG_DIR

DEEP_RESEARCH_TOOL_IDS: Final[frozenset[str]] = frozenset(
    {"knowledge_search", "knowledge_sql", "scan_chunks", "think"}
)


def build_deep_research_tools(
    engine: Any,
    model: str,
    knowledge_db_path: str = "",
) -> list:
    """Build the standard Deep Research tool set from a KnowledgeStore.

    Returns an empty list when the knowledge DB does not exist.
    """
    if not knowledge_db_path:
        knowledge_db_path = str(DEFAULT_CONFIG_DIR / "knowledge.db")

    if not Path(knowledge_db_path).exists():
        return []

    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    store = KnowledgeStore(knowledge_db_path)
    retriever = TwoStageRetriever(store)
    return [
        KnowledgeSearchTool(retriever=retriever),
        KnowledgeSQLTool(store=store),
        ScanChunksTool(store=store, engine=engine, model=model),
        ThinkTool(),
    ]


__all__ = ["DEEP_RESEARCH_TOOL_IDS", "build_deep_research_tools"]
