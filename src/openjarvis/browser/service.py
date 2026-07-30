"""In-process owner for bounded browser sessions exposed by the local API."""

from __future__ import annotations

import threading

from openjarvis.browser.models import (
    BrowserControlHealth,
    BrowserRecoveryRecord,
    BrowserSession,
)
from openjarvis.browser.process import BrowserProcessManager
from openjarvis.browser.recovery import BrowserRecoveryController


class BrowserSessionService:
    """Track only sessions created by one trusted browser manager."""

    def __init__(
        self,
        manager: BrowserProcessManager,
        recovery: BrowserRecoveryController,
    ) -> None:
        self.manager = manager
        self.recovery = recovery
        self._sessions: dict[str, BrowserSession] = {}
        self._recovery_records: dict[str, list[BrowserRecoveryRecord]] = {}
        self._lock = threading.RLock()

    def create(self) -> BrowserSession:
        with self._lock:
            session = self.manager.create_session()
            self._sessions[session.session_id] = session
        try:
            return self.manager.start(session)
        except Exception:
            # Keep the degraded owned session observable and recoverable.
            raise

    def get(self, session_id: str) -> BrowserSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def list(self) -> tuple[BrowserSession, ...]:
        with self._lock:
            return tuple(self._sessions.values())

    def health(self, session_id: str) -> BrowserControlHealth:
        session = self._require(session_id)
        return self.manager.health(session)

    def health_all(self) -> tuple[BrowserControlHealth, ...]:
        return tuple(self.manager.health(session) for session in self.list())

    def recover(self, session_id: str) -> BrowserRecoveryRecord:
        session = self._require(session_id)
        record = self.recovery.recover(session)
        with self._lock:
            self._recovery_records.setdefault(session_id, []).append(record)
        return record

    def recovery_records(
        self,
        session_id: str,
    ) -> tuple[BrowserRecoveryRecord, ...]:
        self._require(session_id)
        with self._lock:
            return tuple(self._recovery_records.get(session_id, ()))

    def close(self, session_id: str) -> BrowserSession:
        session = self._require(session_id)
        self.manager.close(session)
        return session

    def _require(self, session_id: str) -> BrowserSession:
        session = self.get(session_id)
        if session is None:
            raise KeyError(f"unknown browser session: {session_id}")
        return session


__all__ = ["BrowserSessionService"]
