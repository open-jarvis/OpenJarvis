"""Regression coverage for background connector writes during test teardown."""

from __future__ import annotations

import hashlib
import threading
from types import SimpleNamespace

import pytest


def test_delayed_sync_finishes_before_database_paths_are_restored(
    tmp_path, monkeypatch
):
    """A worker delayed before opening its DB must never use restored defaults."""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from friday_ai.connectors import embeddings, sync_engine
    from friday_ai.connectors.pipeline import IngestionPipeline
    from friday_ai.connectors.store import KnowledgeStore
    from friday_ai.core import config
    from friday_ai.server import connectors_router
    from tests.server.conftest import _finish_connector_syncs, _isolate_connector_dbs

    baseline = tmp_path / "restored-home"
    isolated = tmp_path / "isolated-home"
    isolated.mkdir()
    monkeypatch.setattr(config, "DEFAULT_CONFIG_DIR", baseline)
    monkeypatch.setattr(sync_engine, "DEFAULT_CONFIG_DIR", baseline)
    monkeypatch.setattr(embeddings, "default_embedder", lambda: None)
    monkeypatch.setattr(connectors_router, "_instances", {})
    with KnowledgeStore() as store:
        store.store(content="Existing user note", source="obsidian")
        with sync_engine.SyncEngine(IngestionPipeline(store=store)) as engine:
            engine._save_checkpoint("obsidian", 7, cursor="original")
    before = {
        name: hashlib.sha256((baseline / name).read_bytes()).digest()
        for name in ("knowledge.db", "sync_state.db")
    }

    started = threading.Event()
    release = threading.Event()
    joining = threading.Event()
    finished = threading.Event()
    errors = []
    real_init = KnowledgeStore.__init__
    real_join = threading.Thread.join

    def delayed_init(self, *args, **kwargs):
        if "_run_sync" in threading.current_thread().name:
            started.set()
            if not release.wait(10):
                raise TimeoutError("test did not release its sync worker")
        real_init(self, *args, **kwargs)

    def observed_join(self, *args, **kwargs):
        if "_run_sync" in self.name:
            joining.set()
        return real_join(self, *args, **kwargs)

    monkeypatch.setattr(KnowledgeStore, "__init__", delayed_init)
    monkeypatch.setattr(threading.Thread, "join", observed_join)
    isolation = _isolate_connector_dbs.__wrapped__(
        SimpleNamespace(mktemp=lambda _name: isolated)
    )
    next(isolation)
    with pytest.MonkeyPatch.context() as worker_patch:
        cleanup = _finish_connector_syncs.__wrapped__(worker_patch)
        next(cleanup)

        def teardown():
            try:
                cleanup.close()
                isolation.close()
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        teardown_thread = threading.Thread(target=teardown)
        try:
            vault = tmp_path / "vault"
            vault.mkdir()
            (vault / "fixture.md").write_text("Fixture content must stay isolated.")
            app = FastAPI()
            app.include_router(connectors_router.create_connectors_router())
            client = TestClient(app)
            response = client.post(
                "/v1/connectors/obsidian/connect", json={"path": str(vault)}
            )
            assert response.status_code == 200
            assert started.wait(5)

            teardown_thread.start()
            assert joining.wait(5)
            assert not finished.is_set()
            assert config.DEFAULT_CONFIG_DIR == isolated
            assert sync_engine.DEFAULT_CONFIG_DIR == isolated
        finally:
            release.set()
            if teardown_thread.ident is not None:
                teardown_thread.join(timeout=10)
            else:
                cleanup.close()
                isolation.close()

        assert not teardown_thread.is_alive()
        assert not errors
        assert finished.is_set()
        assert config.DEFAULT_CONFIG_DIR == baseline
        assert sync_engine.DEFAULT_CONFIG_DIR == baseline

    assert before == {
        name: hashlib.sha256((baseline / name).read_bytes()).digest() for name in before
    }
    with KnowledgeStore(db_path=isolated / "knowledge.db") as store:
        assert store.retrieve("Fixture content", top_k=10)
    with KnowledgeStore(db_path=isolated / "knowledge.db") as store:
        with sync_engine.SyncEngine(
            IngestionPipeline(store=store), state_db=str(isolated / "sync_state.db")
        ) as engine:
            assert engine.get_checkpoint("obsidian")["items_synced"] > 0
