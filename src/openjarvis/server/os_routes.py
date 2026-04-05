"""OS-level API routes: /os/brief and /os/inbox.

These endpoints aggregate data from the digest store and connector
channels.  The critical fix in this module is that **every SQLAlchemy
``Query`` object is materialised** (via ``.all()``, ``.first()``, or
``str()``) before it reaches psycopg2.  Passing an unmaterialised
``Query`` to the database driver causes::

    psycopg2.ProgrammingError: can't adapt type 'Query'

or::

    AttributeError: 'Query' object has no attribute 'lower'
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)


def _safe_materialise(query_or_value: Any) -> Any:
    """Materialise a SQLAlchemy Query object if one is passed.

    Returns the value unchanged when it is not a Query.  This helper
    guards every boundary where a query result is handed to code that
    expects plain Python objects (e.g. serialisation, psycopg2 params).
    """
    # Detect SQLAlchemy Query without importing it at module level
    # (sqlalchemy is an optional dependency).
    cls_name = type(query_or_value).__name__
    if cls_name == "Query":
        # .all() materialises the query into a plain list
        if hasattr(query_or_value, "all"):
            return query_or_value.all()
        # Fallback: convert to string (e.g. for sub-select usage)
        return str(query_or_value)
    return query_or_value


def create_os_router() -> APIRouter:
    """Create the ``/os`` API router for brief and inbox endpoints."""
    router = APIRouter(prefix="/os", tags=["os"])

    # -----------------------------------------------------------------
    # GET /os/brief — morning brief generation
    # -----------------------------------------------------------------

    @router.get("/brief")
    async def os_brief(request: Request) -> Dict[str, Any]:
        """Return the current morning brief.

        Pulls the latest digest from the ``DigestStore`` and enriches it
        with connector-sourced calendar, email, and task summaries when
        available.
        """
        # 1. Latest digest text -----------------------------------------
        digest_text: Optional[str] = None
        digest_meta: Dict[str, Any] = {}
        try:
            from openjarvis.agents.digest_store import DigestStore

            store = DigestStore()
            artifact = store.get_latest()
            if artifact is not None:
                digest_text = artifact.text
                digest_meta = {
                    "generated_at": artifact.generated_at.isoformat(),
                    "model_used": artifact.model_used,
                    "sources_used": artifact.sources_used,
                    "quality_score": artifact.quality_score,
                }
            store.close()
        except Exception as exc:
            logger.debug("DigestStore unavailable: %s", exc)

        # 2. Calendar events (optional connector) -----------------------
        calendar_items: List[Dict[str, Any]] = []
        try:
            config = getattr(request.app.state, "config", None)
            if config is not None:
                from openjarvis.core.registry import ConnectorRegistry

                gcal = ConnectorRegistry.get("gcalendar")
                if gcal is not None:
                    raw = gcal.fetch(hours_back=0, hours_forward=24)
                    # FIX: materialise in case connector returns a Query
                    raw = _safe_materialise(raw)
                    if isinstance(raw, list):
                        calendar_items = raw
        except Exception as exc:
            logger.debug("Calendar fetch skipped: %s", exc)

        # 3. Unread message counts (optional) ---------------------------
        unread_counts: Dict[str, int] = {}
        try:
            config = getattr(request.app.state, "config", None)
            if config is not None:
                from openjarvis.core.registry import ConnectorRegistry

                for channel in ("gmail", "slack"):
                    conn = ConnectorRegistry.get(channel)
                    if conn is None:
                        continue
                    raw = conn.fetch(hours_back=24)
                    # FIX: materialise before taking len()
                    raw = _safe_materialise(raw)
                    if isinstance(raw, list):
                        unread_counts[channel] = len(raw)
        except Exception as exc:
            logger.debug("Message count fetch skipped: %s", exc)

        # 4. Pending tasks (optional) -----------------------------------
        pending_tasks: List[str] = []
        try:
            config = getattr(request.app.state, "config", None)
            if config is not None:
                from openjarvis.core.registry import ConnectorRegistry

                tasks_conn = ConnectorRegistry.get("google_tasks")
                if tasks_conn is not None:
                    raw = tasks_conn.fetch(hours_back=48)
                    # FIX: materialise query
                    raw = _safe_materialise(raw)
                    if isinstance(raw, list):
                        pending_tasks = [
                            t.get("title", str(t)) if isinstance(t, dict) else str(t)
                            for t in raw
                        ]
        except Exception as exc:
            logger.debug("Tasks fetch skipped: %s", exc)

        return {
            "brief": digest_text,
            "digest_meta": digest_meta,
            "calendar": calendar_items,
            "unread_counts": unread_counts,
            "pending_tasks": pending_tasks,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # -----------------------------------------------------------------
    # GET /os/inbox — unified inbox query
    # -----------------------------------------------------------------

    @router.get("/inbox")
    async def os_inbox(request: Request) -> Dict[str, Any]:
        """Return a unified inbox view across all messaging connectors.

        Aggregates messages from configured channels (Gmail, Slack,
        iMessage, GitHub notifications, …) into a single priority-
        sorted list.
        """
        items: List[Dict[str, Any]] = []
        errors: List[str] = []

        channel_names = [
            "gmail",
            "slack",
            "imessage",
            "github_notifications",
        ]

        for channel in channel_names:
            try:
                from openjarvis.core.registry import ConnectorRegistry

                conn = ConnectorRegistry.get(channel)
                if conn is None:
                    continue

                raw = conn.fetch(hours_back=24)

                # -------------------------------------------------------
                # FIX: Materialise SQLAlchemy Query objects.
                #
                # Some connectors (particularly those backed by a
                # PostgreSQL session) return a ``sqlalchemy.orm.Query``
                # instead of a plain list.  Passing that Query to
                # psycopg2 (e.g. for pagination or further filtering)
                # raises:
                #
                #   ProgrammingError: can't adapt type 'Query'
                #
                # Calling ``.all()`` forces execution and returns a
                # regular Python list that psycopg2 can handle.
                # -------------------------------------------------------
                raw = _safe_materialise(raw)

                if isinstance(raw, list):
                    for msg in raw:
                        if isinstance(msg, dict):
                            msg.setdefault("channel", channel)
                            items.append(msg)
                        else:
                            items.append({
                                "channel": channel,
                                "content": str(msg),
                            })

            except Exception as exc:
                logger.warning("Inbox fetch failed for %s: %s", channel, exc)
                errors.append(f"{channel}: {exc}")

        # Sort by timestamp (newest first) if available
        def _sort_key(item: Dict[str, Any]) -> str:
            return item.get("timestamp", item.get("date", ""))

        items.sort(key=_sort_key, reverse=True)

        return {
            "items": items,
            "total": len(items),
            "channels_queried": channel_names,
            "errors": errors,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    return router


__all__ = ["create_os_router"]
