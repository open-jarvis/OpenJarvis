"""Client for the Railway-hosted obsidian-vault MCP service.

The vault exposes 23 MCP tools over HTTP SSE on port 22360 (default).
:class:`ObsidianVaultClient` wraps the MCP SDK with a sync-friendly
interface and graceful soft-fail when the service is unreachable.
"""

from openjarvis.integrations.obsidian_vault.client import (
    DEFAULT_VAULT_URL,
    ObsidianVaultClient,
    VaultUnavailableError,
    get_default_client,
)

__all__ = [
    "DEFAULT_VAULT_URL",
    "ObsidianVaultClient",
    "VaultUnavailableError",
    "get_default_client",
]
