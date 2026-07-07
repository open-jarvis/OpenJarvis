"""Tests for the background memory service (openjarvis.memory.service)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from openjarvis.core.config import StorageConfig
from openjarvis.core.events import EventBus
from openjarvis.memory.service import (
    MemoryService,
    build_memory_service,
    publish_completed_exchange,
)
from openjarvis.memory.store import LocalFactStore


def _make_retrieval_backend(tmp_path):
    """Real SQLiteMemory retrieval backend on a temp DB.

    conftest wipes registries between tests, so register manually (mirrors
    tests/memory/test_sqlite.py).
    """
    from openjarvis.core.registry import MemoryRegistry
    from openjarvis.tools.storage.sqlite import SQLiteMemory

    if not MemoryRegistry.contains("sqlite"):
        MemoryRegistry.register_value("sqlite", SQLiteMemory)
    return SQLiteMemory(db_path=tmp_path / "retrieval.db")


def _wait_until(predicate, timeout=2.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class FakeExtractor:
    """Extractor stub with controllable output, blocking and failures."""

    def __init__(self, facts=None, *, raises=None, gate=None):
        self._facts = facts or []
        self._raises = raises
        self._gate = gate  # optional threading.Event to block on
        self.calls = []

    def extract(self, user_text, assistant_text=""):
        self.calls.append((user_text, assistant_text))
        if self._gate is not None:
            self._gate.wait(timeout=2.0)
        if self._raises is not None:
            raise self._raises
        return list(self._facts)


def _service(tmp_path, extractor, **kwargs):
    store = LocalFactStore(tmp_path / "facts.jsonl")
    return MemoryService(store, extractor, **kwargs)


def test_start_stop_lifecycle(tmp_path):
    svc = _service(tmp_path, FakeExtractor())
    assert svc.is_running is False
    svc.start()
    assert svc.is_running is True
    svc.start()  # idempotent
    assert svc.is_running is True
    svc.stop()
    assert svc.is_running is False
    svc.stop()  # idempotent


def test_submit_extracts_and_stores(tmp_path):
    extractor = FakeExtractor(["User likes hiking"])
    svc = _service(tmp_path, extractor)
    svc.start()
    try:
        assert svc.submit("I love hiking", "Nice!") is True
        assert _wait_until(lambda: svc.fact_count() == 1)
        assert [f.text for f in svc.list_facts()] == ["User likes hiking"]
    finally:
        svc.stop()


def test_completed_exchange_event_extracts_and_stores(tmp_path):
    bus = EventBus(record_history=True)
    extractor = FakeExtractor(["User likes jazz"])
    store = LocalFactStore(tmp_path / "facts.jsonl")
    svc = MemoryService(store, extractor, event_bus=bus)
    svc.start()
    try:
        assert publish_completed_exchange(
            bus,
            "I like jazz",
            "Noted.",
            source="test",
        )
        assert _wait_until(lambda: svc.fact_count() == 1)
        assert extractor.calls == [("I like jazz", "Noted.")]
    finally:
        svc.stop()


def test_completed_exchange_event_unsubscribes_on_stop(tmp_path):
    bus = EventBus(record_history=True)
    extractor = FakeExtractor(["User likes jazz"])
    store = LocalFactStore(tmp_path / "facts.jsonl")
    svc = MemoryService(store, extractor, event_bus=bus)
    svc.start()
    svc.stop()

    publish_completed_exchange(bus, "I like jazz", "Noted.", source="test")

    assert extractor.calls == []


def test_submit_when_not_running_is_dropped(tmp_path):
    extractor = FakeExtractor(["x"])
    svc = _service(tmp_path, extractor)
    assert svc.submit("hi", "there") is False
    assert extractor.calls == []


def test_submit_empty_user_text_dropped(tmp_path):
    extractor = FakeExtractor(["x"])
    svc = _service(tmp_path, extractor)
    svc.start()
    try:
        assert svc.submit("   ", "y") is False
    finally:
        svc.stop()


def test_worker_survives_extractor_broken_pipe(tmp_path):
    """A BrokenPipeError in one job must not kill the worker."""
    extractor = FakeExtractor(raises=BrokenPipeError("client gone"))
    svc = _service(tmp_path, extractor)
    svc.start()
    try:
        svc.submit("first", "a")
        assert _wait_until(lambda: len(extractor.calls) == 1)
        # Service is still alive and accepting work.
        assert svc.is_running is True
        assert svc.submit("second", "b") is True
        assert _wait_until(lambda: len(extractor.calls) == 2)
    finally:
        svc.stop()


def test_worker_survives_generic_exception(tmp_path):
    extractor = FakeExtractor(raises=RuntimeError("boom"))
    svc = _service(tmp_path, extractor)
    svc.start()
    try:
        svc.submit("x", "y")
        assert _wait_until(lambda: len(extractor.calls) == 1)
        assert svc.is_running is True
    finally:
        svc.stop()


def test_submit_returns_false_when_queue_full(tmp_path):
    """Backpressure: a full queue drops work instead of blocking the caller."""
    gate = threading.Event()
    extractor = FakeExtractor(["fact"], gate=gate)
    svc = _service(tmp_path, extractor, max_queue=1)
    svc.start()
    try:
        # First submit is pulled by the worker and blocks on the gate.
        assert svc.submit("job1", "a") is True
        assert _wait_until(lambda: len(extractor.calls) == 1)
        # Fill the (size-1) queue, then the next submit must be dropped.
        assert svc.submit("job2", "b") is True
        dropped = svc.submit("job3", "c")
        assert dropped is False
    finally:
        gate.set()
        svc.stop()


def test_process_indexes_new_facts_into_retrieval_backend(tmp_path):
    """Extracted facts must land in the retrieval store so inference can recall
    them — otherwise auto-memory is write-only (facts visible in `memory list`
    but never surfaced by `ask`)."""
    backend = _make_retrieval_backend(tmp_path)
    extractor = FakeExtractor(["The user's dog is named Biscuit"])
    store = LocalFactStore(tmp_path / "facts.jsonl")
    svc = MemoryService(store, extractor, retrieval_backend=backend)

    svc._process(("My dog is Biscuit", "Nice!"))

    results = backend.retrieve("dog", top_k=5)
    assert results, "new fact should be retrievable from the backend"
    assert any("Biscuit" in r.content for r in results)


def test_process_does_not_reindex_duplicate_facts(tmp_path):
    """A fact already in the store must not be indexed again — re-indexing would
    accumulate duplicate documents in the retrieval store on every restart."""
    backend = _make_retrieval_backend(tmp_path)
    extractor = FakeExtractor(["The user's dog is named Biscuit"])
    store = LocalFactStore(tmp_path / "facts.jsonl")
    svc = MemoryService(store, extractor, retrieval_backend=backend)

    svc._process(("My dog is Biscuit", "Nice!"))
    svc._process(("My dog is Biscuit", "Nice!"))

    assert backend.count() == 1


def test_process_without_retrieval_backend_still_stores(tmp_path):
    """No retrieval backend wired → facts are still persisted, no crash."""
    extractor = FakeExtractor(["User likes hiking"])
    store = LocalFactStore(tmp_path / "facts.jsonl")
    svc = MemoryService(store, extractor)  # retrieval_backend omitted

    svc._process(("I love hiking", "Nice!"))

    assert [f.text for f in store.list()] == ["User likes hiking"]


def test_process_survives_retrieval_backend_failure(tmp_path):
    """Indexing is best-effort: a backend that raises must not prevent the fact
    from being stored, nor propagate out of the worker."""

    class ExplodingBackend:
        def store(self, *a, **k):
            raise RuntimeError("backend down")

    extractor = FakeExtractor(["User likes hiking"])
    store = LocalFactStore(tmp_path / "facts.jsonl")
    svc = MemoryService(store, extractor, retrieval_backend=ExplodingBackend())

    svc._process(("I love hiking", "Nice!"))  # must not raise

    assert [f.text for f in store.list()] == ["User likes hiking"]


def test_build_memory_service_wires_retrieval_backend(tmp_path):
    """When memory is enabled, the built service gets a retrieval backend so
    the fact→retrieval bridge is active by default."""
    # conftest wipes registries; re-register sqlite (as the module does at
    # import time in real runtime) so the backend can be constructed.
    from openjarvis.core.registry import MemoryRegistry
    from openjarvis.tools.storage.sqlite import SQLiteMemory

    if not MemoryRegistry.contains("sqlite"):
        MemoryRegistry.register_value("sqlite", SQLiteMemory)
    cfg = SimpleNamespace(
        memory=StorageConfig(
            enabled=True,
            extraction_model="qwen3:14b",
            facts_path=str(tmp_path / "facts.jsonl"),
            db_path=str(tmp_path / "memory.db"),
            default_backend="sqlite",
            max_facts=10,
        )
    )
    svc = build_memory_service(cfg, object(), "fallback-model")
    assert isinstance(svc, MemoryService)
    assert svc._retrieval_backend is not None


def test_build_memory_service_disabled_returns_none(tmp_path):
    cfg = SimpleNamespace(memory=StorageConfig(enabled=False))
    assert build_memory_service(cfg, object(), "model") is None


def test_build_memory_service_no_engine_returns_none(tmp_path):
    cfg = SimpleNamespace(memory=StorageConfig(enabled=True))
    assert build_memory_service(cfg, None, "model") is None


def test_build_memory_service_no_model_returns_none(tmp_path):
    cfg = SimpleNamespace(memory=StorageConfig(enabled=True, extraction_model=""))
    assert build_memory_service(cfg, object(), "") is None


def test_build_memory_service_enabled(tmp_path):
    cfg = SimpleNamespace(
        memory=StorageConfig(
            enabled=True,
            extraction_model="qwen3:14b",
            facts_path=str(tmp_path / "facts.jsonl"),
            max_facts=10,
        )
    )
    svc = build_memory_service(cfg, object(), "fallback-model")
    assert isinstance(svc, MemoryService)


def test_build_memory_service_falls_back_to_default_model(tmp_path):
    cfg = SimpleNamespace(
        memory=StorageConfig(
            enabled=True,
            extraction_model="",
            facts_path=str(tmp_path / "facts.jsonl"),
        )
    )
    svc = build_memory_service(cfg, object(), "active-model")
    assert isinstance(svc, MemoryService)
