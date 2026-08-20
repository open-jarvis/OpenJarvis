"""Tests for the persistent fact store (openjarvis.memory.store)."""

from __future__ import annotations

import json
import multiprocessing
import threading
import time

import pytest

from openjarvis.core.registry import FactStoreRegistry
from openjarvis.memory.store import (
    LocalFactStore,
    _cross_process_lock,
    _lock_windows_blocking,
    create_fact_store,
    load_configured_facts,
)


def _add_facts_in_process(
    path: str,
    worker_id: int,
    count: int,
    start: multiprocessing.synchronize.Event,
) -> None:
    start.wait()
    store = LocalFactStore(path)
    for index in range(count):
        store.add(f"process-{worker_id}-{index}")


def _mutate_facts_in_process(
    path: str,
    operation: str,
    ready: multiprocessing.synchronize.Event,
) -> None:
    store = LocalFactStore(path)
    ready.set()
    if operation == "clear":
        store.clear()
    else:
        store.add("new fact")


def test_add_and_list(tmp_path):
    store = LocalFactStore(tmp_path / "facts.jsonl")
    assert store.add("User prefers concise answers") is True
    assert store.add("User lives in Berlin") is True

    facts = store.list()
    assert [f.text for f in facts] == [
        "User prefers concise answers",
        "User lives in Berlin",
    ]
    assert store.count() == 2


def test_add_dedupes_case_insensitive(tmp_path):
    store = LocalFactStore(tmp_path / "facts.jsonl")
    assert store.add("Likes coffee") is True
    assert store.add("likes coffee") is False  # duplicate
    assert store.count() == 1


def test_add_skips_empty(tmp_path):
    store = LocalFactStore(tmp_path / "facts.jsonl")
    assert store.add("") is False
    assert store.add("   ") is False
    assert store.count() == 0


def test_add_many(tmp_path):
    store = LocalFactStore(tmp_path / "facts.jsonl")
    added = store.add_many(["a", "b", "a", "c"])  # one dupe
    assert added == 3
    assert store.count() == 3


def test_max_facts_evicts_oldest(tmp_path):
    store = LocalFactStore(tmp_path / "facts.jsonl", max_facts=2)
    store.add("first")
    store.add("second")
    store.add("third")
    facts = [f.text for f in store.list()]
    assert facts == ["second", "third"]  # oldest dropped


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "facts.jsonl"
    store = LocalFactStore(path)
    store.add("durable fact")

    reloaded = LocalFactStore(path)
    assert [f.text for f in reloaded.list()] == ["durable fact"]


def test_clear(tmp_path):
    path = tmp_path / "facts.jsonl"
    store = LocalFactStore(path)
    store.add("one")
    store.add("two")

    removed = store.clear()
    assert removed == 2
    assert store.count() == 0
    # A fresh instance also sees an empty store.
    assert LocalFactStore(path).count() == 0


def test_external_clear_does_not_resurrect_stale_facts(tmp_path):
    """A running store instance must not re-flush facts cleared elsewhere."""
    path = tmp_path / "facts.jsonl"
    running = LocalFactStore(path)
    cli = LocalFactStore(path)

    running.add("old fact")
    assert cli.clear() == 1

    running.add("new fact")

    assert [f.text for f in LocalFactStore(path).list()] == ["new fact"]


def test_concurrent_instances_do_not_lose_writes(tmp_path):
    """Regression for #755: independent store instances (simulating two
    processes) racing on the same file must not lose writes.

    ``threading.Lock`` only serializes within one process/instance, so it
    does nothing to protect the read (load) -> modify -> write (flush)
    cycle across separate ``LocalFactStore`` instances, and a fixed temp
    filename lets concurrent flushes interleave into the same temp file
    before either ``os.replace()`` runs. Hammer the same file from several
    instances at once and confirm every write survives.
    """
    path = tmp_path / "facts.jsonl"
    n_workers = 8
    n_per_worker = 15

    def worker(worker_id: int) -> None:
        store = LocalFactStore(path)
        for j in range(n_per_worker):
            store.add(f"fact-{worker_id}-{j}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive(), "worker thread hung"

    final = LocalFactStore(path)
    assert final.count() == n_workers * n_per_worker


def test_multiprocess_instances_do_not_lose_writes(tmp_path):
    """Separate spawned interpreters must serialize their update cycles."""
    path = tmp_path / "multiprocess-facts.jsonl"
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    n_workers = 4
    n_per_worker = 10
    processes = [
        context.Process(
            target=_add_facts_in_process,
            args=(str(path), worker_id, n_per_worker, start),
        )
        for worker_id in range(n_workers)
    ]

    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0

    assert LocalFactStore(path).count() == n_workers * n_per_worker


def test_multiprocess_clear_and_add_are_serialized(tmp_path):
    """A clear racing an add must not corrupt or resurrect pre-clear facts."""
    path = tmp_path / "clear-race.jsonl"
    LocalFactStore(path).add("old fact")
    context = multiprocessing.get_context("spawn")
    clear_ready = context.Event()
    add_ready = context.Event()
    clear_process = context.Process(
        target=_mutate_facts_in_process,
        args=(str(path), "clear", clear_ready),
    )
    add_process = context.Process(
        target=_mutate_facts_in_process,
        args=(str(path), "add", add_ready),
    )

    # Hold the actual OS lock until both processes are contending for it.
    # Releasing it lets the operations run in either valid serialized order.
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _cross_process_lock(lock_path):
        clear_process.start()
        add_process.start()
        assert clear_ready.wait(timeout=10)
        assert add_ready.wait(timeout=10)
        time.sleep(0.1)
        assert clear_process.is_alive()
        assert add_process.is_alive()

    clear_process.join(timeout=20)
    add_process.join(timeout=20)
    assert clear_process.exitcode == 0
    assert add_process.exitcode == 0

    final_texts = [fact.text for fact in LocalFactStore(path).list()]
    assert "old fact" not in final_texts
    assert final_texts in ([], ["new fact"])


def test_windows_lock_retries_transient_contention(tmp_path):
    """Simulate the Windows CRT's lock violation before eventual success."""

    class ContendedWindowsLock:
        LK_NBLCK = 1

        def __init__(self) -> None:
            self.calls = 0

        def locking(self, _fd: int, mode: int, nbytes: int) -> None:
            assert mode == self.LK_NBLCK
            assert nbytes == 1
            self.calls += 1
            if self.calls < 4:
                raise OSError(13, "permission denied")

    locking_api = ContendedWindowsLock()
    lock_path = tmp_path / "simulated-windows.lock"
    with lock_path.open("w+b") as lock_file:
        lock_file.write(b"\0")
        lock_file.flush()
        _lock_windows_blocking(
            lock_file,
            locking_api=locking_api,
            retry_interval=0,
        )

    assert locking_api.calls == 4


def test_windows_lock_does_not_hide_unexpected_errors(tmp_path):
    class BrokenWindowsLock:
        LK_NBLCK = 1

        @staticmethod
        def locking(_fd: int, _mode: int, _nbytes: int) -> None:
            raise OSError(22, "invalid argument")

    lock_path = tmp_path / "broken-windows.lock"
    with lock_path.open("w+b") as lock_file:
        lock_file.write(b"\0")
        lock_file.flush()
        with pytest.raises(OSError, match="invalid argument"):
            _lock_windows_blocking(
                lock_file,
                locking_api=BrokenWindowsLock(),
                retry_interval=0,
            )


def test_load_skips_malformed_lines(tmp_path):
    path = tmp_path / "facts.jsonl"
    path.write_text(
        '{"text": "good fact"}\n'
        "this is not json\n"
        '{"text": ""}\n'  # empty text ignored
        '{"text": "another good"}\n',
        encoding="utf-8",
    )
    store = LocalFactStore(path)
    assert [f.text for f in store.list()] == ["good fact", "another good"]


def test_jsonl_round_trip_is_valid_json(tmp_path):
    path = tmp_path / "facts.jsonl"
    store = LocalFactStore(path)
    store.add("fact one", source="auto")

    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["text"] == "fact one"
    assert obj["source"] == "auto"
    assert "created_at" in obj


def test_create_fact_store_local(tmp_path):
    store = create_fact_store("local", path=tmp_path / "f.jsonl", max_facts=5)
    assert isinstance(store, LocalFactStore)


def test_create_fact_store_uses_fact_store_registry(tmp_path):
    class CustomFactStore(LocalFactStore):
        pass

    FactStoreRegistry.register_value("custom", CustomFactStore)

    store = create_fact_store("custom", path=tmp_path / "f.jsonl", max_facts=5)

    assert isinstance(store, CustomFactStore)


def test_create_fact_store_default_path_uses_openjarvis_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))

    store = create_fact_store("local")

    assert isinstance(store, LocalFactStore)
    assert store.path == tmp_path / "memory_facts.jsonl"


def test_create_fact_store_unknown_backend(tmp_path):
    with pytest.raises(ValueError):
        create_fact_store("cloud", path=tmp_path / "f.jsonl")


def test_load_configured_facts_reads_enabled_store(tmp_path):
    from types import SimpleNamespace

    path = tmp_path / "facts.jsonl"
    LocalFactStore(path).add("User likes jazz", source="auto")
    config = SimpleNamespace(
        memory=SimpleNamespace(
            enabled=True,
            backend="local",
            facts_path=str(path),
            max_facts=1000,
        )
    )

    assert [fact.text for fact in load_configured_facts(config)] == ["User likes jazz"]


def test_load_configured_facts_skips_disabled_memory():
    from types import SimpleNamespace

    config = SimpleNamespace(memory=SimpleNamespace(enabled=False))

    assert load_configured_facts(config) == []
