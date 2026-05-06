"""In-memory store for pending and completed proactive elaborations.

An elaboration is born when a chat request kicks off the slow Claude-CLI track.
It progresses pending -> complete (claude returned) -> proposed (materially
different) -> accepted | dismissed. Or it can hit discarded (not different) /
failed (claude error / timeout).

This module also owns a tiny pub/sub for the SSE stream — subscribers receive
events when elaborations are proposed or accepted.

v1: in-memory. v2: persist to Postgres via DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)


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
            return elab

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
