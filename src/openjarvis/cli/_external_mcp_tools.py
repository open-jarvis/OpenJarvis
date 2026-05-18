"""Attach external MCP tools (HTTP/stdio) for CLI agents (chat, ask).

Mirrors :meth:`openjarvis.system.builder.SystemBuilder._discover_external_mcp`
so ``[tools.mcp].servers`` works outside ``jarvis serve`` / SystemBuilder.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any, List, Optional, Set

logger = logging.getLogger(__name__)


def discover_external_mcp_tools(
    config: Any,
    *,
    allowed_tool_names: Optional[Set[str]] = None,
    status: Optional[Callable[[str], None]] = None,
) -> List[Any]:
    """Return :class:`~openjarvis.tools.mcp_adapter.MCPToolAdapter` instances.

    Parameters
    ----------
    config:
        Loaded :class:`~openjarvis.core.config.JarvisConfig`.
    allowed_tool_names:
        If not ``None``, only MCP tools whose ``spec.name`` is in this set are
        kept (same idea as ``SystemBuilder._resolve_tools``). If ``None``,
        every discovered MCP tool is returned.
    status:
        Optional callback for human-readable progress (e.g. CLI ``print``).
        Invoked before and after each MCP server handshake.
    """
    if not getattr(config.tools.mcp, "enabled", True):
        return []
    raw = getattr(config.tools.mcp, "servers", "") or ""
    if not raw.strip():
        return []

    try:
        server_list = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Invalid tools.mcp.servers JSON: %s", exc)
        return []

    if not isinstance(server_list, list):
        return []

    from openjarvis.mcp.client import MCPClient
    from openjarvis.mcp.transport import StdioTransport, StreamableHTTPTransport
    from openjarvis.tools.mcp_adapter import MCPToolProvider

    out: list = []
    for server_cfg in server_list:
        cfg = json.loads(server_cfg) if isinstance(server_cfg, str) else server_cfg
        name = cfg.get("name", "<unnamed>")
        url = cfg.get("url")
        command = cfg.get("command", "")
        args = cfg.get("args", [])

        try:
            if url:
                transport = StreamableHTTPTransport(url=url)
            elif command:
                extra_env = cfg.get("env") or {}
                if isinstance(extra_env, dict):
                    env_map = {str(k): str(v) for k, v in extra_env.items()}
                else:
                    env_map = {}
                transport = StdioTransport(
                    command=[command] + args,
                    env=env_map or None,
                )
            else:
                logger.warning(
                    "MCP server '%s' has neither 'url' nor 'command' — skipping",
                    name,
                )
                continue

            t0 = time.monotonic()
            if status:
                status(f"MCP server '{name}': connecting …")

            client = MCPClient(transport)
            client.initialize()
            provider = MCPToolProvider(client)
            discovered = provider.discover()

            include_tools = set(cfg.get("include_tools", []))
            exclude_tools = set(cfg.get("exclude_tools", []))
            if include_tools:
                discovered = [t for t in discovered if t.spec.name in include_tools]
            if exclude_tools:
                discovered = [t for t in discovered if t.spec.name not in exclude_tools]

            if allowed_tool_names is not None:
                discovered = [
                    t for t in discovered if t.spec.name in allowed_tool_names
                ]

            out.extend(discovered)
            logger.info(
                "CLI: attached %d MCP tool(s) from server '%s'",
                len(discovered),
                name,
            )
            if status:
                elapsed = time.monotonic() - t0
                status(
                    f"MCP server '{name}': {len(discovered)} tool(s) in {elapsed:.1f}s",
                )
        except Exception as exc:
            logger.warning("CLI: MCP server '%s' failed: %s", name, exc)
            if status:
                elapsed = time.monotonic() - t0
                status(
                    f"MCP server '{name}': failed after {elapsed:.1f}s — {exc!s}",
                )

    return out


__all__ = ["discover_external_mcp_tools"]
