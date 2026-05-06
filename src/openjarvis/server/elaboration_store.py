"""Store for pending and completed proactive elaborations.

An elaboration is born when a chat request kicks off the slow Claude-CLI track.
It progresses pending -> complete (claude returned) -> proposed (materially
different) -> accepted | dismissed. Or it can hit discarded (not different) /
failed (claude error / timeout).

This module also owns a tiny pub/sub for the SSE stream — subscribers receive
events when elaborations are proposed or accepted.

Persistence is dual-mode: when `DATABASE_URL` is set in env AND `psycopg` is
installed, every state mutation is mirrored to Postgres so a Railway restart
mid-elaboration doesn't drop pending records. The in-memory dict is kept as
the read path (Postgres writes are lazy/best-effort, never block subscribers).
If `DATABASE_URL` is unset or psycopg is missing, the store falls back to
in-memory only and logs once at boot.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Optional Postgres persistence
# ---------------------------------------------------------------------------

_PG_DSN_ENV = "DATABASE_URL"
_pg_available: Optional[bool] = None  # lazily resolved on first use
_pg_pool = None  # psycopg AsyncConnectionPool, lazily created


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS elaborations (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    original_question TEXT NOT NULL,
    spoken_answer TEXT,
    claude_answer TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS elaborations_status_idx ON elaborations(status);
"""


async def _pg_init() -> bool:
    """Open a pool and ensure the schema. Returns True if Postgres is usable."""
    global _pg_available, _pg_pool
    if _pg_available is not None:
        return _pg_available
    dsn = os.environ.get(_PG_DSN_ENV)
    if not dsn:
        logger.info(
            "Elaboration persistence: %s not set — running in-memory only",
            _PG_DSN_ENV,
        )
        _pg_available = False
        return False
    try:
        from psycopg_pool import AsyncConnectionPool  # type: ignore
    except ImportError:
        logger.info(
            "Elaboration persistence: psycopg not installed — running in-memory only"
        )
        _pg_available = False
        return False
    try:
        _pg_pool = AsyncConnectionPool(conninfo=dsn, min_size=1, max_size=2, open=False)
        await _pg_pool.open()
        async with _pg_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_SCHEMA_SQL)
        logger.info("Elaboration persistence: Postgres ready")
        _pg_available = True
        return True
    except Exception as exc:
        logger.warning(
            "Elaboration persistence: failed to init Postgres (%s) — in-memory only",
            exc,
        )
        _pg_available = False
        return False


async def _pg_upsert(elab: "Elaboration") -> None:
    """Mirror an Elaboration record to Postgres. Best-effort, never raises."""
    if not await _pg_init() or _pg_pool is None:
        return
    try:
        async with _pg_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO elaborations
                        (id, conversation_id, original_question, spoken_answer,
                         claude_answer, status, error, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        spoken_answer = EXCLUDED.spoken_answer,
                        claude_answer = EXCLUDED.claude_answer,
                        status = EXCLUDED.status,
                        error = EXCLUDED.error,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        elab.id,
                        elab.conversation_id,
                        elab.original_question,
                        elab.spoken_answer,
                        elab.claude_answer,
                        elab.status.value,
                        elab.error,
                        elab.created_at,
                        elab.updated_at,
                    ),
                )
    except Exception as exc:
        logger.warning("Elaboration upsert failed for %s: %s", elab.id, exc)


async def _pg_load_recent(limit: int = 100) -> list[dict[str, Any]]:
    """Return recent records from Postgres for in-memory hydration on boot."""
    if not await _pg_init() or _pg_pool is None:
        return []
    try:
        async with _pg_pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT id, conversation_id, original_question, spoken_answer,
                           claude_answer, status, error, created_at, updated_at
                    FROM elaborations
                    WHERE status IN ('pending', 'proposed')
                    ORDER BY created_at DESC LIMIT %s
                    """,
                    (limit,),
                )
                rows = await cur.fetchall()
        cols = [
            "id", "conversation_id", "original_question", "spoken_answer",
            "claude_answer", "status", "error", "created_at", "updated_at",
        ]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as exc:
        logger.warning("Elaboration load failed: %s", exc)
        return []


class ElaborationStatus(str, Enum):
    PENDING = "pending"            # claude task in flight
    DISCARDED = "discarded"        # claude returned but not materially different
    FAILED = "failed"              # claude task failed or timed out
    PROPOSED = "proposed"          # banner shown, awaiting user decision
    ACCEPTED = "accepted"          # user said yes, claude answer surfaced
    DISMISSED = "dismissed"        # user said no


@dataclass
class Elaboration:
    id: str
    conversation_id: Optional[str]
    original_question: str
    spoken_answer: Optional[str]   # filled when the immediate stream finishes
    claude_answer: Optional[str]
    status: ElaborationStatus
    created_at: float
    updated_at: float
    error: Optional[str] = None

    def to_event_dict(self, include_full_answer: bool = False) -> dict[str, Any]:
        """Subset suitable for SSE delivery."""
        d: dict[str, Any] = {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "status": self.status.value,
            "original_question_excerpt": self.original_question[:120],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_full_answer and self.claude_answer is not None:
            d["claude_answer"] = self.claude_answer
        return d


@dataclass
class _Event:
    event: str  # "proposed" | "accepted_full" | "dismissed"
    data: dict[str, Any]


class _ElaborationStore:
    def __init__(self) -> None:
        self._items: dict[str, Elaboration] = {}
        self._subscribers: set[asyncio.Queue[_Event]] = set()
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        original_question: str,
        conversation_id: Optional[str] = None,
    ) -> Elaboration:
        now = time.time()
        elab = Elaboration(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            original_question=original_question,
            spoken_answer=None,
            claude_answer=None,
            status=ElaborationStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._items[elab.id] = elab
        # Fire-and-forget Postgres mirror so SSE subscribers aren't blocked.
        asyncio.create_task(_pg_upsert(elab))
        return elab

    async def update(self, elab_id: str, **fields: Any) -> Optional[Elaboration]:
        async with self._lock:
            elab = self._items.get(elab_id)
            if elab is None:
                return None
            for k, v in fields.items():
                if hasattr(elab, k):
                    setattr(elab, k, v)
            elab.updated_at = time.time()
        asyncio.create_task(_pg_upsert(elab))
        return elab

    async def hydrate_from_postgres(self) -> int:
        """Load pending/proposed elaborations from Postgres into the in-memory
        dict. Called once at boot. Returns count loaded."""
        rows = await _pg_load_recent(limit=200)
        if not rows:
            return 0
        async with self._lock:
            for row in rows:
                if row["id"] in self._items:
                    continue
                try:
                    status = ElaborationStatus(row["status"])
                except ValueError:
                    continue
                self._items[row["id"]] = Elaboration(
                    id=row["id"],
                    conversation_id=row["conversation_id"],
                    original_question=row["original_question"] or "",
                    spoken_answer=row["spoken_answer"],
                    claude_answer=row["claude_answer"],
                    status=status,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    error=row["error"],
                )
        logger.info("Elaboration store hydrated %d records from Postgres", len(rows))
        return len(rows)

    async def get(self, elab_id: str) -> Optional[Elaboration]:
        async with self._lock:
            return self._items.get(elab_id)

    async def set_spoken_answer(self, elab_id: str, text: str) -> None:
        await self.update(elab_id, spoken_answer=text)

    async def mark_proposed(self, elab_id: str, claude_answer: str) -> None:
        elab = await self.update(
            elab_id,
            status=ElaborationStatus.PROPOSED,
            claude_answer=claude_answer,
        )
        if elab is not None:
            await self._broadcast(_Event(event="proposed", data=elab.to_event_dict()))

    async def mark_discarded(self, elab_id: str, claude_answer: str) -> None:
        await self.update(
            elab_id,
            status=ElaborationStatus.DISCARDED,
            claude_answer=claude_answer,
        )

    async def mark_failed(self, elab_id: str, error: str) -> None:
        await self.update(elab_id, status=ElaborationStatus.FAILED, error=error)

    async def accept(self, elab_id: str) -> Optional[Elaboration]:
        elab = await self.update(elab_id, status=ElaborationStatus.ACCEPTED)
        if elab is not None and elab.claude_answer is not None:
            await self._broadcast(
                _Event(
                    event="accepted_full",
                    data=elab.to_event_dict(include_full_answer=True),
                )
            )
        return elab

    async def dismiss(self, elab_id: str) -> Optional[Elaboration]:
        elab = await self.update(elab_id, status=ElaborationStatus.DISMISSED)
        if elab is not None:
            await self._broadcast(
                _Event(event="dismissed", data={"id": elab.id})
            )
        return elab

    # --- SSE pub/sub --------------------------------------------------------

    async def subscribe(self) -> AsyncIterator[_Event]:
        q: asyncio.Queue[_Event] = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers.add(q)
        try:
            while True:
                ev = await q.get()
                yield ev
        finally:
            async with self._lock:
                self._subscribers.discard(q)

    async def _broadcast(self, ev: _Event) -> None:
        async with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                logger.warning("Dropped elaboration event for slow subscriber")


# Module-level singleton — one store per process is the right shape for v1
_store = _ElaborationStore()


def get_store() -> _ElaborationStore:
    return _store


__all__ = [
    "Elaboration",
    "ElaborationStatus",
    "get_store",
]
