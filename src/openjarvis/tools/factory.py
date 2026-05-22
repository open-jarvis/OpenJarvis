"""Shared tool-instantiation helper.

The dispatch lives here so that every code path which builds tools from
their string names (``cli/ask.py``, ``server/agent_manager_routes.py``,
future call sites) injects the same dependencies. Without a shared
helper, paths drift — a tool that works under ``jarvis ask`` returns
``"No memory backend configured."`` under the managed-agent streaming
endpoint, because the latter forgot to inject the backend (see #395).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry

logger = logging.getLogger(__name__)


MEMORY_TOOLS = frozenset(
    {"retrieval", "memory_store", "memory_search", "memory_index", "memory_retrieve"}
)
CHANNEL_TOOLS = frozenset({"channel_send", "channel_list", "channel_status"})


def instantiate_tool(
    name: str,
    *,
    app_config: Any,
    engine: Any = None,
    model_name: str = "",
    channel: Any = None,
) -> Optional[Any]:
    """Instantiate a tool by name with the right dependencies injected.

    Returns ``None`` if the name is unknown to ``ToolRegistry``. Warns
    (but still instantiates) when a memory/channel tool is requested
    without a backend/channel — the tool will load and every call will
    return its own ``"No X configured."`` error, which is the failure
    mode we want surfaced loudly rather than silently dropped.
    """
    if not ToolRegistry.contains(name):
        return None

    tool_cls = ToolRegistry.get(name)

    if name in MEMORY_TOOLS:
        from openjarvis.cli.ask import _get_memory_backend

        backend = _get_memory_backend(app_config)
        if backend is None:
            logger.warning(
                "Tool %r was requested but no memory backend is available "
                "(default=%r). The tool will load but return no results.",
                name,
                getattr(app_config.memory, "default_backend", "?"),
            )
        return tool_cls(backend=backend)

    if name in CHANNEL_TOOLS:
        if channel is None:
            logger.warning(
                "Tool %r was requested but no channel was injected. "
                "Every call will return 'No channel backend configured'.",
                name,
            )
        return tool_cls(channel=channel)

    if name == "llm":
        return tool_cls(engine=engine, model=model_name)

    return tool_cls()
