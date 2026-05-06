"""Obsidian-vault memory backend — store/retrieve via the Railway MCP service.

Treats the remote vault as a long-term knowledge store. Memories are
written as individual ``.md`` files under ``Memory/{YYYY-MM-DD}/`` with
YAML frontmatter (``type: memory``, ``source``, ``tags``, ``date``)
that matches the vault's ``_schema.md`` convention. Retrieval uses the
vault's ``search_files`` MCP tool (lexical full-text); for richer
filtering, callers can wrap :meth:`retrieve` and pass ``tag`` /
``path_prefix`` kwargs which are forwarded to ``search_with_filters``.

Selection
---------
The backend is opt-in via ``MEMORY_BACKEND=obsidian_vault`` in
``config.toml``. SQLite remains the always-available default.

Why a separate backend instead of just an ingestion connector
-------------------------------------------------------------
Memory writes must round-trip *now* (the model just produced an insight
worth keeping). An ingestion connector pulls on a schedule, so memory
written via the connector path would lag by one sync cycle. The
:class:`ObsidianRemoteConnector` (see ``connectors/obsidian_remote.py``)
exists for the *read* side — surfacing pre-existing vault notes into
RAG — and is complementary, not a replacement.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openjarvis.core.registry import MemoryRegistry
from openjarvis.integrations.obsidian_vault import (
    ObsidianVaultClient,
    VaultUnavailableError,
    get_default_client,
)
from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, *, max_len: int = 40) -> str:
    base = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (base[:max_len] or "untitled").rstrip("-")


def _frontmatter(metadata: Dict[str, Any]) -> str:
    """Render a minimal YAML frontmatter block (no nested objects)."""
    if not metadata:
        return ""
    lines = ["---"]
    for k, v in metadata.items():
        if isinstance(v, list):
            inner = ", ".join(str(item).replace('"', "'") for item in v)
            lines.append(f"{k}: [{inner}]")
        else:
            sv = str(v).replace("\n", " ").strip()
            lines.append(f"{k}: {sv}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


@MemoryRegistry.register("obsidian_vault")
class ObsidianVaultBackend(MemoryBackend):
    """MemoryBackend that persists to the Railway-hosted Obsidian vault.

    Parameters
    ----------
    client:
        Override for the vault client (used in tests). Defaults to the
        process-wide singleton from
        :func:`openjarvis.integrations.obsidian_vault.get_default_client`.
    """

    backend_id: str = "obsidian_vault"

    def __init__(self, client: Optional[ObsidianVaultClient] = None) -> None:
        self._client = client or get_default_client()

    # ------------------------------------------------------------------
    # MemoryBackend ABC
    # ------------------------------------------------------------------

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Write *content* as a markdown note under ``Memory/{date}/``.

        Returns the vault-relative path of the created note (used as
        the doc id for subsequent :meth:`delete` calls).
        """
        now = datetime.now(timezone.utc)
        date_dir = now.strftime("%Y-%m-%d")
        # Slug from a stable hash so retries don't multiply notes.
        digest = hashlib.sha1(
            (content + (source or "") + now.isoformat()).encode("utf-8")
        ).hexdigest()[:8]
        first_line = next(
            (line.strip() for line in content.splitlines() if line.strip()),
            "memory",
        )
        slug = _slug(first_line)
        path = f"Memory/{date_dir}/{slug}-{digest}.md"

        fm: Dict[str, Any] = {
            "type": "memory",
            "date": now.date().isoformat(),
        }
        if source:
            fm["source"] = source
        if metadata:
            tags = metadata.get("tags")
            if tags:
                fm["tags"] = tags if isinstance(tags, list) else [tags]
            for k, v in metadata.items():
                if k in ("tags",) or v is None:
                    continue
                fm.setdefault(k, v)

        body = f"{_frontmatter(fm)}{content.rstrip()}\n"

        try:
            self._client.write_file(path, body)
        except VaultUnavailableError as exc:
            logger.warning("ObsidianVaultBackend.store failed (%s); doc not persisted", exc)
            raise
        return path

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Lexical search over vault notes, returning the top-k matches.

        ``kwargs`` may include:
            tag: filter by frontmatter or inline ``#tag``
            path_prefix: restrict to a vault subtree (e.g. ``Memory/``)
        """
        if not query.strip() and not kwargs.get("tag"):
            return []

        try:
            if kwargs.get("tag") or kwargs.get("path_prefix"):
                raw = self._client.search_with_filters(
                    content_query=query or None,
                    tag=kwargs.get("tag"),
                    path_prefix=kwargs.get("path_prefix"),
                )
            else:
                raw = self._client.search_files(query, max_results=top_k)
        except VaultUnavailableError as exc:
            logger.warning("ObsidianVaultBackend.retrieve failed (%s); empty result", exc)
            return []

        return _coerce_results(raw, top_k=top_k)

    def delete(self, doc_id: str) -> bool:
        try:
            self._client.delete_file(doc_id)
            return True
        except VaultUnavailableError as exc:
            logger.warning("ObsidianVaultBackend.delete(%s) failed: %s", doc_id, exc)
            return False

    def clear(self) -> None:
        """Refuse to clear — would delete the entire shared vault.

        ``MemoryBackend.clear`` semantics are "remove everything", but
        the Obsidian vault is shared with other agents (super-agent,
        humans). Bulk deletion via this hook would be a footgun.
        Operators who genuinely want to wipe ``Memory/`` should use
        the vault's ``bulk_move_files`` tool with explicit confirmation.
        """
        logger.error(
            "ObsidianVaultBackend.clear() refused — vault is shared. "
            "Use vault tooling to remove Memory/ explicitly."
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_results(raw: Any, *, top_k: int) -> List[RetrievalResult]:
    """Normalize the vault's search response into RetrievalResult objects.

    The vault returns either a JSON-encoded list of dicts (path/snippet/score)
    or a plain text payload. Both shapes are accepted.
    """
    items: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        items = [r for r in raw if isinstance(r, dict)]
    elif isinstance(raw, dict) and "results" in raw:
        items = [r for r in raw["results"] if isinstance(r, dict)]
    elif isinstance(raw, str):
        # Best-effort: split on blank lines and emit one result per chunk.
        chunks = [c.strip() for c in raw.split("\n\n") if c.strip()]
        return [
            RetrievalResult(content=c, score=1.0 - (i * 0.05), source="obsidian_vault")
            for i, c in enumerate(chunks[:top_k])
        ]

    out: List[RetrievalResult] = []
    for entry in items[:top_k]:
        path = entry.get("path") or entry.get("file") or ""
        snippet = (
            entry.get("snippet")
            or entry.get("content")
            or entry.get("text")
            or ""
        )
        score = float(entry.get("score", 0.0)) if entry.get("score") is not None else 0.0
        out.append(
            RetrievalResult(
                content=snippet or path,
                score=score,
                source="obsidian_vault",
                metadata={"path": path, **{k: v for k, v in entry.items() if k not in ("snippet", "content", "text", "score", "path", "file")}},
            )
        )
    return out


__all__ = ["ObsidianVaultBackend"]
