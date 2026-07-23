"""Persistent memory service: async fact extraction integrated into core.

``MemoryService`` runs fact extraction on a dedicated background thread so it
never blocks ``jarvis serve`` request handling or the ``jarvis chat`` REPL.
Callers hand off an exchange via :meth:`submit`, which enqueues the work and
returns immediately — the slow model call and disk write happen out of band.
The worker swallows every per-job error (including ``BrokenPipeError`` when a
client disconnects mid-extraction), so a flaky extraction model can never take
down the host process.

The service is started and stopped as part of the OpenJarvis lifecycle (see
``cli/serve.py`` and ``cli/chat_cmd.py``) and is configured through the
``[memory]`` section of ``config.toml``.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, List, Optional

from openjarvis.core.events import Event, EventBus, EventType
from openjarvis.memory.extractor import FactExtractor
from openjarvis.memory.store import Fact, FactStore, create_fact_store
from openjarvis.tools.storage._stubs import MemoryBackend

logger = logging.getLogger(__name__)

# Sentinel pushed onto the queue to wake the worker for shutdown.
_STOP = object()


class MemoryService:
    """Background long-term-memory extraction and persistence service."""

    def __init__(
        self,
        store: FactStore,
        extractor: FactExtractor,
        *,
        event_bus: EventBus | None = None,
        backend: Optional[MemoryBackend] = None,
        max_queue: int = 256,
    ) -> None:
        self._store = store
        self._extractor = extractor
        self._event_bus = event_bus
        self._backend = backend
        self._subscribed = False
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=max(1, max_queue))
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Start the background worker thread (idempotent)."""
        if self._running.is_set():
            return
        self._running.set()
        self._subscribe_events()
        self._thread = threading.Thread(
            target=self._loop,
            name="memory-service",
            daemon=True,
        )
        self._thread.start()
        logger.debug("Memory service started")

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the worker to drain and stop, then join it (idempotent)."""
        if not self._running.is_set():
            return
        self._running.clear()
        try:
            self._queue.put_nowait(_STOP)
        except queue.Full:
            pass  # worker will notice the cleared flag on its next loop
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        self._unsubscribe_events()
        logger.debug("Memory service stopped")

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    # -- submission ---------------------------------------------------------

    def submit(self, user_text: str, assistant_text: str = "") -> bool:
        """Queue an exchange for extraction. Non-blocking; never raises.

        Returns True if the job was enqueued, False if the service is not
        running or the queue is full (in which case the exchange is dropped
        rather than blocking the caller — extraction is best-effort).
        """
        if not self._running.is_set():
            return False
        if not user_text or not user_text.strip():
            return False
        try:
            self._queue.put_nowait((user_text, assistant_text))
            return True
        except queue.Full:
            logger.debug("Memory service queue full; dropping exchange")
            return False

    def _subscribe_events(self) -> None:
        """Subscribe to lifecycle events that feed automatic memory."""
        if self._event_bus is None or self._subscribed:
            return
        self._event_bus.subscribe(
            EventType.CHAT_EXCHANGE_COMPLETED,
            self._on_completed_exchange,
        )
        self._subscribed = True

    def _unsubscribe_events(self) -> None:
        """Unsubscribe from lifecycle events (idempotent)."""
        if self._event_bus is None or not self._subscribed:
            return
        self._event_bus.unsubscribe(
            EventType.CHAT_EXCHANGE_COMPLETED,
            self._on_completed_exchange,
        )
        self._subscribed = False

    def _on_completed_exchange(self, event: Event) -> None:
        """Queue a completed chat exchange published on the event bus."""
        data = event.data or {}
        self.submit(
            str(data.get("user_text", "") or ""),
            str(data.get("assistant_text", "") or ""),
        )

    # -- worker -------------------------------------------------------------

    def _loop(self) -> None:
        while True:
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                if not self._running.is_set():
                    break
                continue
            if job is _STOP:
                self._queue.task_done()
                break
            try:
                self._process(job)
            except Exception:  # noqa: BLE001 — a bad job must not kill the worker
                logger.debug("Memory extraction job failed", exc_info=True)
            finally:
                self._queue.task_done()
            if not self._running.is_set() and self._queue.empty():
                break

    def _process(self, job: Any) -> None:
        user_text, assistant_text = job
        facts = self._extractor.extract(user_text, assistant_text)
        if not facts:
            return
        # Add one at a time (semantically identical to add_many, which is a
        # plain base-class loop over add()) so we learn *which* facts were
        # newly stored — add() returns True only for a non-duplicate. That
        # subset is exactly what we mirror into the model-facing backend, so
        # duplicates never accumulate in the recall index.
        new_facts = [f for f in facts if self._store.add(f, source="auto")]
        if new_facts:
            logger.debug("Memory service stored %d new fact(s)", len(new_facts))
            self._mirror_to_backend(new_facts)

    def _mirror_to_backend(self, facts: List[str]) -> None:
        """Mirror newly-stored auto facts into the model-facing backend.

        Auto-extracted facts originate from raw conversation text that may
        contain untrusted target output, so every mirrored entry is tagged
        ``trust="untrusted"`` in its metadata. The recall path
        (``inject_context``) reads that tag and drops or annotates untrusted
        results before they reach the model — that filter is what makes the
        tag load-bearing.

        Best-effort: a backend that is absent, unavailable, or that raises on
        ``store`` must never take down extraction. Failures are swallowed at
        debug level, exactly like the rest of this service.

        Note: this only closes the loop for a *persistent* shared backend
        (the default ``sqlite``, on disk at ``memory.db_path``). In-memory
        per-instance backends (e.g. ``bm25``) do not share state with the
        recall path's freshly-constructed backend, so mirrored facts will not
        surface there — a known limitation, not a silent failure.
        """
        if self._backend is None:
            return
        for text in facts:
            try:
                self._backend.store(
                    text,
                    source="auto",
                    metadata={"trust": "untrusted"},
                )
            except Exception:  # noqa: BLE001 — mirroring is best-effort
                logger.debug("Memory backend mirror failed", exc_info=True)

    # -- store passthroughs -------------------------------------------------

    def list_facts(self) -> List[Fact]:
        return self._store.list()

    def clear_facts(self) -> int:
        return self._store.clear()

    def fact_count(self) -> int:
        return self._store.count()


def build_memory_service(
    config: Any,
    engine: Any,
    default_model: str = "",
    *,
    event_bus: EventBus | None = None,
) -> Optional[MemoryService]:
    """Build a :class:`MemoryService` from config, or ``None`` if disabled.

    Reads the ``[memory]`` section (``config.memory`` / ``config.tools.storage``)
    for ``enabled``, ``backend``, ``extraction_model``, ``max_facts`` and
    ``facts_path``.  Returns ``None`` when memory is disabled or no engine /
    extraction model is available, so callers can simply do::

        svc = build_memory_service(config, engine, model)
        if svc is not None:
            svc.start()
    """
    mem = getattr(config, "memory", None)
    if mem is None or not getattr(mem, "enabled", False):
        return None
    if engine is None:
        return None

    model = getattr(mem, "extraction_model", "") or default_model
    if not model:
        logger.debug("Memory service disabled: no extraction model available")
        return None

    store = create_fact_store(
        getattr(mem, "backend", "local"),
        path=getattr(mem, "facts_path", None),
        max_facts=getattr(mem, "max_facts", 1000),
    )
    extractor = FactExtractor(engine, model)

    # Model-facing recall backend to mirror auto facts into. Reuse the CLI's
    # canonical constructor (lazy import: it lives in the heavy `cli.ask`
    # module) so the mirror writes to exactly the same backend / sqlite
    # db_path the recall path reads from. Best-effort — a None backend just
    # disables mirroring, leaving extraction untouched.
    backend = None
    try:
        from openjarvis.cli.ask import _get_memory_backend

        backend = _get_memory_backend(config)
    except Exception:  # noqa: BLE001 — mirroring is optional
        logger.debug("Memory mirror backend unavailable", exc_info=True)

    return MemoryService(store, extractor, event_bus=event_bus, backend=backend)


def publish_completed_exchange(
    bus: EventBus | None,
    user_text: str,
    assistant_text: str = "",
    *,
    source: str = "",
) -> bool:
    """Publish a completed chat exchange for lifecycle subscribers."""
    if bus is None or not user_text or not user_text.strip():
        return False
    bus.publish(
        EventType.CHAT_EXCHANGE_COMPLETED,
        {
            "user_text": user_text,
            "assistant_text": assistant_text or "",
            "source": source,
        },
    )
    return True


__all__ = ["MemoryService", "build_memory_service", "publish_completed_exchange"]
