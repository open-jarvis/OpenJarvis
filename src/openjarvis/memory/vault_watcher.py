"""Low-CPU polling fallback for incremental Markdown vault indexing."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openjarvis.memory.vault_models import IndexReport
    from openjarvis.memory.vault_service import VaultMemoryService

logger = logging.getLogger(__name__)


class PollingVaultWatcher:
    """Deduplicate filesystem snapshots and synchronize changed vaults.

    The manual reindex API remains authoritative. This watcher is an optional,
    conservative Windows-compatible fallback that uses an interruptible wait,
    content hashes, and one daemon thread rather than a busy loop.
    """

    def __init__(
        self,
        service: VaultMemoryService,
        *,
        interval_seconds: float = 2.0,
        debounce_seconds: float = 0.25,
    ) -> None:
        if interval_seconds < 0.25:
            raise ValueError("poll interval must be at least 0.25 seconds")
        if debounce_seconds < 0:
            raise ValueError("debounce interval cannot be negative")
        self.service = service
        self.interval_seconds = interval_seconds
        self.debounce_seconds = debounce_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_applied: tuple[tuple[str, int, str], ...] | None = None
        self._pending_since: float | None = None
        self.last_error: str | None = None
        self.sync_count = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._last_applied = self._snapshot()
        self._pending_since = None
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="openjarvis-vault-poller",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        self._thread = None

    def poll_once(self, *, force: bool = False) -> IndexReport | None:
        """Synchronize one changed, stable snapshot; unchanged polls are no-ops."""

        observed = self._snapshot()
        if observed == self._last_applied:
            self._pending_since = None
            return None
        now = time.monotonic()
        if self._pending_since is None:
            self._pending_since = now
        if not force and now - self._pending_since < self.debounce_seconds:
            return None
        try:
            report = self.service.sync()
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Vault polling sync failed: %s", self.last_error)
            return None
        self._last_applied = observed
        self._pending_since = None
        self.last_error = None
        self.sync_count += 1
        return report

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.poll_once()

    def _snapshot(self) -> tuple[tuple[str, int, str], ...]:
        root = self.service.index.vault_root
        rows: list[tuple[str, int, str]] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in {".md", ".markdown"}:
                continue
            relative = path.relative_to(root).as_posix()
            try:
                payload = path.read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                rows.append((relative, len(payload), digest))
            except OSError as exc:
                rows.append((relative, -1, f"unreadable:{type(exc).__name__}"))
        return tuple(rows)


__all__ = ["PollingVaultWatcher"]
