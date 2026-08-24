"""Tests for the MixedbreadMemory backend.

The backend is a thin adapter over the ``mixedbread`` SDK, so these
tests exercise the adapter contract against a fake client — argument
mapping, lazy store resolution, result shaping, and error translation —
without any network access. They are skipped when the optional
``mixedbread`` dependency is not installed (``uv sync --extra
memory-mixedbread``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

pytest.importorskip("mixedbread")

import httpx  # noqa: E402
from mixedbread import ConflictError, NotFoundError  # noqa: E402

from openjarvis.core.registry import MemoryRegistry  # noqa: E402
from openjarvis.tools.storage.mixedbread_backend import (  # noqa: E402
    DEFAULT_STORE_NAME,
    MixedbreadMemory,
)


def _not_found() -> NotFoundError:
    request = httpx.Request("GET", "https://api.mixedbread.test")
    return NotFoundError(
        "not found",
        response=httpx.Response(404, request=request),
        body=None,
    )


def _chunk(
    text: Optional[str] = "chunk text",
    *,
    score: float = 0.9,
    filename: str = "openjarvis-abc.md",
    file_id: str = "file_1",
    chunk_index: int = 0,
    metadata: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        score=score,
        filename=filename,
        file_id=file_id,
        chunk_index=chunk_index,
        metadata=metadata,
    )


class FakeStoreFiles:
    def __init__(self, parent: "FakeStores") -> None:
        self._parent = parent
        self.upload_calls: List[Dict[str, Any]] = []
        self.poll_calls: List[Dict[str, Any]] = []
        self.deleted: List[str] = []
        self.missing_file_ids: set[str] = set()

    def upload(self, **kwargs: Any) -> SimpleNamespace:
        self.upload_calls.append(kwargs)
        return SimpleNamespace(id=f"file_{len(self.upload_calls)}")

    def upload_and_poll(self, **kwargs: Any) -> SimpleNamespace:
        self.poll_calls.append(kwargs)
        return SimpleNamespace(id=f"polled_{len(self.poll_calls)}")

    def delete(self, file_identifier: str, *, store_identifier: str) -> None:
        if file_identifier in self.missing_file_ids:
            raise _not_found()
        self.deleted.append(file_identifier)


class FakeStores:
    def __init__(self, *, existing: bool = False) -> None:
        self.files = FakeStoreFiles(self)
        self.existing = existing
        self.created: List[Dict[str, Any]] = []
        self.deleted: List[str] = []
        self.search_calls: List[Dict[str, Any]] = []
        self.search_results: List[SimpleNamespace] = []

    def retrieve(self, store_identifier: str) -> SimpleNamespace:
        if not self.existing:
            raise _not_found()
        return SimpleNamespace(id="store_existing")

    def create(self, *, name: str) -> SimpleNamespace:
        self.created.append({"name": name})
        return SimpleNamespace(id="store_created")

    def delete(self, store_identifier: str) -> None:
        if not self.existing and not self.created:
            raise _not_found()
        self.deleted.append(store_identifier)

    def search(self, **kwargs: Any) -> SimpleNamespace:
        self.search_calls.append(kwargs)
        return SimpleNamespace(data=self.search_results)


class FakeClient:
    def __init__(self, *, existing_store: bool = False) -> None:
        self.stores = FakeStores(existing=existing_store)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_registry_registration_and_db_path() -> None:
    """Importing the module registers the backend under ``mixedbread``.

    The autouse ``_clean_registries`` fixture wipes ``MemoryRegistry``
    before each test, so re-execute the module to re-register — the same
    thing ``openjarvis.tools.storage`` does at import time.  SystemBuilder
    and the CLI pass ``db_path=`` to every backend, so the remote backend
    must swallow it rather than crash.
    """
    import importlib

    from openjarvis.tools.storage import mixedbread_backend

    importlib.reload(mixedbread_backend)
    assert MemoryRegistry.contains("mixedbread")

    backend = MemoryRegistry.create(
        "mixedbread", client=FakeClient(), db_path="/tmp/ignored.db"
    )
    assert backend.backend_id == "mixedbread"


def test_requires_api_key_without_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MXBAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="MXBAI_API_KEY"):
        MixedbreadMemory()


def test_store_creates_store_lazily_and_uploads() -> None:
    client = FakeClient()
    backend = MixedbreadMemory(client=client)

    doc_id = backend.store("hello world", source="notes.txt", metadata={"a": 1})

    assert client.stores.created == [{"name": DEFAULT_STORE_NAME}]
    assert doc_id == "file_1"
    (call,) = client.stores.files.upload_calls
    assert call["store_identifier"] == "store_created"
    filename, payload = call["file"]
    assert filename.endswith(".md")
    assert payload == b"hello world"
    assert call["metadata"] == {"a": 1, "source": "notes.txt"}


def test_store_reuses_existing_store() -> None:
    client = FakeClient(existing_store=True)
    backend = MixedbreadMemory(client=client)

    backend.store("one")
    backend.store("two")

    assert client.stores.created == []
    calls = client.stores.files.upload_calls
    assert [c["store_identifier"] for c in calls] == ["store_existing"] * 2


def test_wait_for_indexing_uses_polling_upload() -> None:
    client = FakeClient(existing_store=True)
    backend = MixedbreadMemory(client=client, wait_for_indexing=True)

    doc_id = backend.store("hello")

    assert doc_id == "polled_1"
    assert client.stores.files.upload_calls == []


def test_retrieve_maps_chunks_to_results() -> None:
    client = FakeClient(existing_store=True)
    client.stores.search_results = [
        _chunk(metadata={"source": "notes.txt", "a": 1}),
        _chunk(text=None),  # image/audio chunk — no text body, skipped
        _chunk(text="second", score=0.5, metadata="not-a-dict"),
    ]
    backend = MixedbreadMemory(client=client)

    results = backend.retrieve("what is in my notes?", top_k=5)

    assert [r.content for r in results] == ["chunk text", "second"]
    first, second = results
    assert first.score == pytest.approx(0.9)
    assert first.source == "notes.txt"
    assert first.metadata["a"] == 1
    assert first.metadata["file_id"] == "file_1"
    assert first.metadata["chunk_index"] == 0
    # Non-dict file metadata falls back to the filename as source.
    assert second.source == "openjarvis-abc.md"

    (call,) = client.stores.search_calls
    assert call["query"] == "what is in my notes?"
    assert call["store_identifiers"] == ["store_existing"]
    assert call["top_k"] == 5
    assert call["search_options"] == {"agentic": True, "return_metadata": True}


def test_retrieve_truncates_to_top_k() -> None:
    client = FakeClient(existing_store=True)
    client.stores.search_results = [_chunk(text=f"c{i}") for i in range(4)]
    backend = MixedbreadMemory(client=client)

    results = backend.retrieve("query", top_k=2)

    assert [r.content for r in results] == ["c0", "c1"]


def test_agentic_flag_propagates() -> None:
    client = FakeClient(existing_store=True)
    backend = MixedbreadMemory(client=client, agentic=False)

    backend.retrieve("query")

    (call,) = client.stores.search_calls
    assert call["search_options"]["agentic"] is False


def test_retrieve_blank_query_makes_no_api_call() -> None:
    client = FakeClient(existing_store=True)
    backend = MixedbreadMemory(client=client)

    assert backend.retrieve("   ") == []
    assert client.stores.search_calls == []


def test_delete_translates_not_found() -> None:
    client = FakeClient(existing_store=True)
    client.stores.files.missing_file_ids = {"gone"}
    backend = MixedbreadMemory(client=client)

    assert backend.delete("file_1") is True
    assert backend.delete("gone") is False
    assert client.stores.files.deleted == ["file_1"]


def test_clear_deletes_store_and_resets_resolution() -> None:
    client = FakeClient(existing_store=True)
    backend = MixedbreadMemory(client=client)
    backend.store("hello")

    backend.clear()

    assert client.stores.deleted == ["store_existing"]
    # Next use must re-resolve (and here re-create) the store.
    backend.store("again")
    assert client.stores.files.upload_calls[-1]["store_identifier"] == (
        "store_existing"
    )


def test_clear_on_missing_store_is_a_noop() -> None:
    client = FakeClient()
    backend = MixedbreadMemory(client=client)

    backend.clear()

    assert client.stores.deleted == []


def test_close_only_closes_an_owned_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from openjarvis.tools.storage import mixedbread_backend as module

    owned = FakeClient()
    monkeypatch.setattr(module, "Mixedbread", lambda api_key: owned)
    backend = module.MixedbreadMemory(api_key="test")

    backend.close()
    backend.close()
    assert owned.close_calls == 1

    injected = FakeClient()
    module.MixedbreadMemory(client=injected).close()
    assert injected.close_calls == 0


def test_concurrent_first_use_creates_one_store() -> None:
    """Regression: unlocked ``_ensure_store`` let every concurrent first
    call see the store missing and create its own duplicate."""
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    client = FakeClient()
    lock = threading.Lock()
    counts = {"create": 0}
    original_retrieve = client.stores.retrieve
    original_create = client.stores.create

    def slow_retrieve(store_identifier: str) -> SimpleNamespace:
        time.sleep(0.01)  # widen the check-then-act window
        return original_retrieve(store_identifier)

    def counting_create(*, name: str) -> SimpleNamespace:
        with lock:
            counts["create"] += 1
        return original_create(name=name)

    client.stores.retrieve = slow_retrieve  # type: ignore[method-assign]
    client.stores.create = counting_create  # type: ignore[method-assign]
    backend = MixedbreadMemory(client=client)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda i: backend.store(f"doc {i}"), range(16)))

    assert counts["create"] == 1
    assert len(client.stores.files.upload_calls) == 16


def test_create_conflict_falls_back_to_retrieve() -> None:
    """A concurrent *process* can create the store between our retrieve
    and create; the resulting 409 must resolve to the winner's store."""
    client = FakeClient()

    def conflicting_create(*, name: str) -> SimpleNamespace:
        client.stores.existing = True  # the other process's store now exists
        request = httpx.Request("POST", "https://api.mixedbread.test")
        raise ConflictError(
            "conflict",
            response=httpx.Response(409, request=request),
            body=None,
        )

    client.stores.create = conflicting_create  # type: ignore[method-assign]
    backend = MixedbreadMemory(client=client)

    doc_id = backend.store("hello")

    assert doc_id == "file_1"
    (call,) = client.stores.files.upload_calls
    assert call["store_identifier"] == "store_existing"
