"""Base types for data source connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from openjarvis.tools._stubs import ToolSpec


@dataclass(slots=True)
class Attachment:
    """A file attached to a document (email attachment, shared file, etc.)."""

    filename: str
    mime_type: str
    size_bytes: int
    sha256: str = ""
    content: bytes = field(default=b"", repr=False)


@dataclass(slots=True)
class Document:
    """Universal schema for data from any connector.

    All connectors normalize their output to this format before ingestion.
    """

    doc_id: str
    source: str
    doc_type: str
    content: str
    title: str = ""
    author: str = ""
    participants: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    thread_id: Optional[str] = None
    url: Optional[str] = None
    attachments: List[Attachment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SyncStatus:
    """Progress of a connector's sync operation."""

    state: str = "idle"
    items_synced: int = 0
    items_total: int = 0
    last_sync: Optional[datetime] = None
    cursor: Optional[str] = None
    error: Optional[str] = None


class BaseConnector(ABC):
    """Abstract base for data source connectors.

    Each connector knows how to authenticate with a service, bulk-sync
    its data as ``Document`` objects, and optionally expose MCP tools
    for real-time agent queries.
    """

    connector_id: str
    display_name: str
    auth_type: str  # "oauth" | "local" | "bridge" | "filesystem"

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the connector has valid credentials."""

    @abstractmethod
    def disconnect(self) -> None:
        """Revoke credentials and clean up."""

    @abstractmethod
    def sync(
        self, *, since: Optional[datetime] = None, cursor: Optional[str] = None
    ) -> Iterator[Document]:
        """Yield documents from the data source.

        If *since* is given, only return items created/modified after that time.
        If *cursor* is given, resume from a previous checkpoint.
        """

    @abstractmethod
    def sync_status(self) -> SyncStatus:
        """Return current sync progress."""

    def auth_url(self) -> str:
        """Generate an OAuth consent URL.  Only relevant for auth_type='oauth'."""
        raise NotImplementedError(f"{self.connector_id} does not use OAuth")

    def handle_callback(self, code: str) -> None:
        """Handle the OAuth callback.  Only relevant for auth_type='oauth'."""
        raise NotImplementedError(f"{self.connector_id} does not use OAuth")

    def mcp_tools(self) -> List[ToolSpec]:
        """Return MCP tool specs for real-time agent queries.  Optional."""
        return []
