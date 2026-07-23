"""Tests for the background memory service (openjarvis.memory.service)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from openjarvis.core.config import StorageConfig
from openjarvis.core.events import EventBus
from openjarvis.memory.service import (
    MemoryService,
    build_memory_service,
    publish_completed_exchange,
)
from openjarvis.memory.store import LocalFactStore


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


class CapturingBackend:
    """MemoryBackend stub that records every store() call."""

    backend_id = "capture"

    def __init__(self, *, raises=None):
        self.stored = []  # list of (content, source, metadata)
        self._raises = raises

    def store(self, content, *, source="", metadata=None):
        if self._raises is not None:
            raise self._raises
        self.stored.append((content, source, metadata))
        return "id-%d" % len(self.stored)


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


# -- Backend mirroring -------------------------------------------------------


def test_mirror_tags_new_facts_untrusted(tmp_path):
    """Newly-stored auto facts are mirrored to the backend as untrusted."""
    backend = CapturingBackend()
    extractor = FakeExtractor(["User lives in Berlin"])
    svc = _service(tmp_path, extractor, backend=backend)
    svc.start()
    try:
        svc.submit("Where do I live?", "Berlin.")
        assert _wait_until(lambda: len(backend.stored) == 1)
    finally:
        svc.stop()
    content, source, metadata = backend.stored[0]
    assert content == "User lives in Berlin"
    assert source == "auto"
    assert metadata == {"trust": "untrusted"}


def test_mirror_skips_duplicate_facts(tmp_path):
    """Only newly-stored facts are mirrored — duplicates are not re-sent."""
    backend = CapturingBackend()
    extractor = FakeExtractor(["User likes tea"])
    svc = _service(tmp_path, extractor, backend=backend)
    svc.start()
    try:
        svc.submit("first", "a")
        assert _wait_until(lambda: len(backend.stored) == 1)
        # Same fact again: the store dedupes, so nothing new is mirrored.
        svc.submit("second", "b")
        assert _wait_until(lambda: len(extractor.calls) == 2)
        # Give the worker a beat; the count must stay at 1.
        assert not _wait_until(lambda: len(backend.stored) > 1, timeout=0.3)
    finally:
        svc.stop()
    assert len(backend.stored) == 1


def test_mirror_failure_does_not_break_extraction(tmp_path):
    """A backend that raises on store must not stop facts being persisted."""
    backend = CapturingBackend(raises=RuntimeError("backend down"))
    extractor = FakeExtractor(["User has a cat"])
    svc = _service(tmp_path, extractor, backend=backend)
    svc.start()
    try:
        svc.submit("x", "y")
        # The fact still lands in the local store despite the mirror failing.
        assert _wait_until(lambda: svc.fact_count() == 1)
        assert svc.is_running is True
    finally:
        svc.stop()


def test_no_backend_is_a_noop(tmp_path):
    """With no backend, extraction still works and nothing is mirrored."""
    extractor = FakeExtractor(["User plays guitar"])
    svc = _service(tmp_path, extractor)  # backend defaults to None
    svc.start()
    try:
        svc.submit("x", "y")
        assert _wait_until(lambda: svc.fact_count() == 1)
    finally:
        svc.stop()


def test_mirror_to_sqlite_untrusted_fact_is_dropped_at_recall(tmp_path):
    """End-to-end: an auto fact mirrored to a real sqlite backend is tagged
    untrusted, so the recall path drops it before it reaches the model."""
    try:
        from openjarvis.tools.storage.sqlite import SQLiteMemory
    except Exception as exc:  # pragma: no cover - import guard
        pytest.skip(f"sqlite backend import failed: {exc}")

    from openjarvis.core.types import Message, Role
    from openjarvis.tools.storage.context import ContextConfig, inject_context

    try:
        backend = SQLiteMemory(str(tmp_path / "memory.db"))
    except Exception as exc:
        pytest.skip(f"sqlite backend unavailable: {exc}")

    extractor = FakeExtractor(["User lives in Berlin"])
    svc = _service(tmp_path, extractor, backend=backend)
    svc.start()
    try:
        svc.submit("Where do I live?", "Berlin.")
        assert _wait_until(lambda: backend.count() == 1)
    finally:
        svc.stop()

    messages = [Message(role=Role.USER, content="where do I live?")]

    # Default "drop" policy: the untrusted mirrored fact must NOT surface.
    dropped = inject_context("Berlin", messages, backend)
    assert dropped is messages

    # "annotate" policy: it surfaces, but only behind the unverified caveat.
    from openjarvis.tools.storage.context import _UNTRUSTED_ANNOTATION

    cfg = ContextConfig(untrusted_policy="annotate")
    annotated = inject_context("Berlin", messages, backend, config=cfg)
    assert len(annotated) == 2
    assert _UNTRUSTED_ANNOTATION in annotated[0].content
    assert "Berlin" in annotated[0].content
