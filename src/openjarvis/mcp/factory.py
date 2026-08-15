"""One place that turns an MCP server config into a live client.

Discovery, the tool adapter and the executor stay on the native path; only
the client implementation is swappable. A deployment that needs different
client behaviour -- cancelling an in-flight call when a realtime turn is
interrupted, for instance -- registers an implementation here instead of
forking the three discovery call sites.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_IMPLEMENTATIONS: Dict[str, Callable[[dict], Any]] = {}


def register_mcp_client_impl(key: str, builder: Callable[[dict], Any]) -> None:
    """Register an MCP client implementation under *key*.

    A server config selects it with ``{"client": "<key>"}``. Configs that name
    no implementation get the default transport-backed ``MCPClient``.
    """
    _IMPLEMENTATIONS[key] = builder


def _default_client(cfg: dict) -> Optional[Any]:
    from openjarvis.mcp.client import MCPClient
    from openjarvis.mcp.transport import StdioTransport, StreamableHTTPTransport

    name = cfg.get("name", "<unnamed>")
    url = cfg.get("url")
    # Bearer token from config — needed by authenticated MCP servers
    # like Home Assistant. None / empty string skips the header. #461.
    token = cfg.get("token")
    command = cfg.get("command", "")
    args = cfg.get("args", [])

    if url:
        transport = StreamableHTTPTransport(url=url, token=token)
    elif command:
        transport = StdioTransport(command=[command] + args)
    else:
        logger.warning(
            "MCP server '%s' has neither 'url' nor 'command' — skipping",
            name,
        )
        return None

    return MCPClient(transport)


def create_mcp_client(cfg: dict) -> Optional[Any]:
    """Build the client for one MCP server config.

    Returns ``None`` when the config names neither ``url`` nor ``command``,
    which the caller treats as "skip this server". Raises ``ValueError`` when
    ``client`` names an implementation nobody registered -- silently falling
    back would run the server on transport semantics it did not ask for.
    """
    key = cfg.get("client")
    if not key:
        return _default_client(cfg)
    if key not in _IMPLEMENTATIONS:
        raise ValueError(
            f"MCP server {cfg.get('name', '<unnamed>')!r} requests client "
            f"implementation {key!r}, which is not registered"
        )
    return _IMPLEMENTATIONS[key](cfg)


__all__ = ["create_mcp_client", "register_mcp_client_impl"]
