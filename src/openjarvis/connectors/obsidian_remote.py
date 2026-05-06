"""Remote Obsidian-vault connector — pulls notes from the Railway MCP service.

Complements the local-filesystem :class:`~openjarvis.connectors.obsidian.ObsidianConnector`
by ingesting notes from the shared Railway-hosted vault into
``KnowledgeStore`` so RAG queries can hit them alongside Gmail, Notion,
Slack, etc.

Selection: prefer this connector when ``OBSIDIAN_VAULT_URL`` is set;
the local connector remains the default for users with a vault on disk.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterator, List, Optional

from openjarvis.connectors._stubs import BaseConnector, Document, SyncStatus
from openjarvis.core.registry import ConnectorRegistry
from openjarvis.integrations.obsidian_vault import (
    DEFAULT_VAULT_URL,
    ObsidianVaultClient,
    VaultUnavailableError,
    get_default_client,
)
from openjarvis.tools._stubs import ToolSpec

logger = logging.getLogger(__name__)


def _coerce_paths(raw: Any) -> List[str]:
    """Extract a list of vault-relative paths from list_directory output."""
    if isinstance(raw, list):
        out: List[str] = []
        for item in raw:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                p = item.get("path") or item.get("file") or item.get("name")
                if p:
                    out.append(str(p))
        return out
    if isinstance(raw, dict):
        files = raw.get("files") or raw.get("paths") or []
        return [str(p) for p in files if p]
    if isinstance(raw, str):
        return [line.strip() for line in raw.splitlines() if line.strip()]
    return []


@ConnectorRegistry.register("obsidian_remote")
class ObsidianRemoteConnector(BaseConnector):
    """Read notes from the obsidian-vault MCP service into the knowledge pipeline."""

    connector_id = "obsidian_remote"
    display_name = "Obsidian Vault (Railway)"
    auth_type = "bridge"

    def __init__(
        self,
        client: Optional[ObsidianVaultClient] = None,
        *,
        url: Optional[str] = None,
    ) -> None:
        self._client = client or (
            ObsidianVaultClient(url=url) if url else get_default_client()
        )
        self._url = url or os.environ.get("OBSIDIAN_VAULT_URL", DEFAULT_VAULT_URL)
        self._items_synced = 0
        self._items_total = 0

    # ------------------------------------------------------------------
    # BaseConnector
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        try:
            return self._client.is_healthy()
        except Exception:  # pragma: no cover — defensive
            return False

    def disconnect(self) -> None:
        # Stateless client; nothing to revoke.
        pass

    def sync(
        self,
        *,
        since: Optional[datetime] = None,
        cursor: Optional[str] = None,  # noqa: ARG002 — unused, ABC compatibility
    ) -> Iterator[Document]:
        try:
            raw = self._client.list_directory("")
        except VaultUnavailableError as exc:
            logger.warning("ObsidianRemoteConnector unreachable (%s); empty sync", exc)
            self._items_total = 0
            self._items_synced = 0
            return

        paths = [p for p in _coerce_paths(raw) if p.endswith(".md")]
        self._items_total = len(paths)

        synced = 0
        for path in paths:
            try:
                content = self._client.read_file(path)
            except VaultUnavailableError as exc:
                logger.info("Skipping %s: %s", path, exc)
                continue
            if not content:
                continue

            # Best-effort: use vault metadata for timestamp when available.
            try:
                meta_raw = self._client.get_note_metadata(path)
            except VaultUnavailableError:
                meta_raw = None
            metadata: dict[str, Any] = {}
            if isinstance(meta_raw, dict):
                metadata = {k: v for k, v in meta_raw.items() if v is not None}

            ts: datetime
            mtime_raw = metadata.get("mtime") or metadata.get("modified")
            if isinstance(mtime_raw, (int, float)):
                ts = datetime.fromtimestamp(mtime_raw, tz=timezone.utc)
            else:
                ts = datetime.now(timezone.utc)

            if since is not None and ts < since:
                continue

            title = (
                metadata.get("title")
                or path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            )

            yield Document(
                doc_id=f"obsidian_remote:{path}",
                source="obsidian_vault",
                doc_type="note",
                content=content,
                title=str(title),
                timestamp=ts,
                url=f"{self._url}/notes/{path}",
                metadata=metadata,
            )
            synced += 1

        self._items_synced = synced

    def sync_status(self) -> SyncStatus:
        return SyncStatus(
            state="idle",
            items_synced=self._items_synced,
            items_total=self._items_total,
        )

    # ------------------------------------------------------------------
    # Optional MCP tool surface — kept minimal; the rich tools live in
    # openjarvis.tools.obsidian_vault_tools.
    # ------------------------------------------------------------------

    def mcp_tools(self) -> List[ToolSpec]:
        return [
            ToolSpec(
                name="obsidian_vault_search",
                description=(
                    "Search the shared Obsidian vault on Railway. "
                    "Returns paths and snippets."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer", "default": 20},
                    },
                    "required": ["query"],
                },
                category="memory",
            )
        ]


__all__ = ["ObsidianRemoteConnector"]
