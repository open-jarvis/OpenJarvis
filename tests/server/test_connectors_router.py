"""Tests for the /v1/connectors API router."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture
def app():
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    from openjarvis.server.connectors_router import create_connectors_router

    _app = FastAPI()
    router = create_connectors_router()
    # The router already carries ``prefix="/v1/connectors"``. The real
    # ``server/app.py`` mounts it with ``include_router(router)`` — adding
    # a second ``prefix="/v1"`` here would produce ``/v1/v1/connectors``
    # and every request would 404.
    _app.include_router(router)
    return TestClient(_app)


def test_list_connectors(app):
    """GET /v1/connectors returns a list that includes the obsidian connector."""
    resp = app.get("/v1/connectors")
    assert resp.status_code == 200
    data = resp.json()
    assert "connectors" in data
    ids = [c["connector_id"] for c in data["connectors"]]
    assert "obsidian" in ids


def test_connector_detail(app):
    """GET /v1/connectors/obsidian returns the expected fields."""
    resp = app.get("/v1/connectors/obsidian")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert "display_name" in data
    assert "auth_type" in data
    assert "connected" in data
    assert "mcp_tools" in data


def test_connector_not_found(app):
    """GET /v1/connectors/nonexistent returns 404."""
    resp = app.get("/v1/connectors/nonexistent")
    assert resp.status_code == 404


def test_connect_obsidian(app, tmp_path):
    """POST /v1/connectors/obsidian/connect with a valid path marks it connected."""
    # Create a minimal vault directory so is_connected() returns True.
    vault = tmp_path / "vault"
    vault.mkdir()

    resp = app.post("/v1/connectors/obsidian/connect", json={"path": str(vault)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["connected"] is True


def test_disconnect(app):
    """POST /v1/connectors/obsidian/disconnect returns 200 with connected=False."""
    resp = app.post("/v1/connectors/obsidian/disconnect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["connected"] is False


def test_disconnect_clears_stale_sync_checkpoint(app) -> None:
    """Disconnecting a connector must reset its sync checkpoint.

    Regression: a user disconnects Obsidian from one vault and reconnects
    it to a different vault. Before this fix, the SyncEngine checkpoint
    (items_synced, cursor, last_sync) was keyed only by connector_id and
    survived disconnect, so the next sync resumed from the OLD vault's
    watermark -- inflating the reported item count with stale data and
    risking skipped items in the new vault whose timestamps predate the
    old watermark.
    """
    from openjarvis.connectors.pipeline import IngestionPipeline
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.connectors.sync_engine import SyncEngine

    with KnowledgeStore() as store:
        with SyncEngine(pipeline=IngestionPipeline(store=store)) as engine:
            engine._save_checkpoint("obsidian", 9, cursor="stale-cursor")
            assert engine.get_checkpoint("obsidian") is not None

    resp = app.post("/v1/connectors/obsidian/disconnect")
    assert resp.status_code == 200

    # A fresh SyncEngine (same default state DB) must see no checkpoint.
    with KnowledgeStore() as store:
        with SyncEngine(pipeline=IngestionPipeline(store=store)) as fresh_engine:
            assert fresh_engine.get_checkpoint("obsidian") is None


def test_disconnect_purges_previously_ingested_content(app) -> None:
    """Disconnecting a connector must purge its previously-ingested chunks.

    Regression: reconnecting Obsidian to a different vault left the OLD
    vault's chunks in the KnowledgeStore forever (disconnect only cleared
    credentials, never indexed content). If the new vault contains a file
    at the same relative path as one in the old vault (e.g. both have a
    "Welcome.md"), the resulting doc_id collides with the orphaned old
    chunk, and the ingestion pipeline's duplicate-doc_id dedup silently
    discards the new content -- the user's real notes never get indexed,
    with no error surfaced anywhere.
    """
    from openjarvis.connectors.store import KnowledgeStore

    with KnowledgeStore() as store:
        store.store(
            content="Stale content from a previously-connected vault",
            source="obsidian",
            doc_type="note",
            doc_id="obsidian:Welcome.md",
            title="Welcome",
            author="",
        )
        assert any(
            r.metadata.get("source") == "obsidian"
            for r in store.retrieve("stale content vault", top_k=10)
        )

    resp = app.post("/v1/connectors/obsidian/disconnect")
    assert resp.status_code == 200

    with KnowledgeStore() as fresh_store:
        assert not any(
            r.metadata.get("source") == "obsidian"
            for r in fresh_store.retrieve("stale content vault", top_k=10)
        )


def test_disconnect_cancels_inflight_sync_before_purge(app) -> None:
    from openjarvis.connectors._stubs import Document, SyncStatus
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.server.connectors_router import _instances

    started = threading.Event()
    released = threading.Event()
    disconnect_called = threading.Event()

    class BlockingConnector:
        connector_id = "obsidian"
        indexed_sources = ("obsidian",)

        def is_connected(self):
            return True

        def sync(self, **kwargs):
            started.set()
            released.wait(timeout=2)
            yield Document(
                doc_id="obsidian:late-write",
                source="obsidian",
                doc_type="note",
                content="must not survive disconnect",
            )

        def disconnect(self):
            disconnect_called.set()

        def sync_status(self):
            return SyncStatus()

    _instances["obsidian"] = BlockingConnector()
    responses = []

    def disconnect_request():
        responses.append(app.post("/v1/connectors/obsidian/disconnect"))

    disconnect_thread = threading.Thread(target=disconnect_request)
    try:
        assert app.post("/v1/connectors/obsidian/sync").status_code == 200
        assert started.wait(timeout=2)
        disconnect_thread.start()

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if app.get("/v1/connectors/obsidian/sync").json()["state"] == "stopping":
                break
            time.sleep(0.01)
        else:
            pytest.fail("disconnect never entered the stopping state")

        # Credentials remain intact until the old writer has stopped.
        assert not disconnect_called.is_set()
        released.set()
        disconnect_thread.join(timeout=3)
        assert not disconnect_thread.is_alive()
        assert responses[0].status_code == 200
        assert disconnect_called.is_set()
        with KnowledgeStore() as store:
            assert not any(
                result.metadata.get("doc_id") == "obsidian:late-write"
                for result in store.retrieve("must survive disconnect", top_k=10)
            )
    finally:
        released.set()
        disconnect_thread.join(timeout=3)
        _instances.pop("obsidian", None)


def test_disconnect_timeout_preserves_source_and_guards_reconnect(
    app,
    monkeypatch,
    tmp_path,
) -> None:
    from openjarvis.connectors._stubs import SyncStatus
    from openjarvis.server import connectors_router
    from openjarvis.server.connectors_router import _instances

    started = threading.Event()
    released = threading.Event()
    finished = threading.Event()
    disconnect_called = threading.Event()

    class StuckConnector:
        connector_id = "obsidian"
        indexed_sources = ("obsidian",)
        auth_type = "filesystem"

        def __init__(self):
            self._connected = True
            self._vault_path = "old-vault"

        def is_connected(self):
            return self._connected

        def sync(self, **kwargs):
            started.set()
            released.wait(timeout=3)
            finished.set()
            if False:
                yield

        def disconnect(self):
            disconnect_called.set()
            self._connected = False

        def sync_status(self):
            return SyncStatus()

    connector = StuckConnector()
    _instances["obsidian"] = connector
    monkeypatch.setattr(connectors_router, "_SYNC_STOP_TIMEOUT_SECONDS", 0.05)
    new_vault = tmp_path / "new-vault"
    new_vault.mkdir()

    try:
        assert app.post("/v1/connectors/obsidian/sync").status_code == 200
        assert started.wait(timeout=2)

        response = app.post("/v1/connectors/obsidian/disconnect")
        assert response.status_code == 409
        assert connector.is_connected()
        assert connector._vault_path == "old-vault"
        assert not disconnect_called.is_set()

        reconnect = app.post(
            "/v1/connectors/obsidian/connect",
            json={"path": str(new_vault)},
        )
        assert reconnect.status_code == 409
        assert connector._vault_path == "old-vault"
        assert app.post("/v1/connectors/obsidian/sync").status_code == 409

        released.set()
        assert finished.wait(timeout=2)
        assert app.get("/v1/connectors/obsidian/sync").json()["state"] == "stopping"
        response = app.post("/v1/connectors/obsidian/disconnect")
        assert response.status_code == 200
        assert disconnect_called.is_set()
        assert not connector.is_connected()
    finally:
        released.set()
        _instances.pop("obsidian", None)


def test_disconnect_prevents_sync_start_racing_checkpoint_read(
    app,
    monkeypatch,
) -> None:
    """Disconnect waits for an in-progress start decision, then purges it."""
    from openjarvis.connectors._stubs import Document, SyncStatus
    from openjarvis.connectors.sync_engine import SyncEngine
    from openjarvis.server.connectors_router import _instances

    baseline_started = threading.Event()
    release_baseline = threading.Event()
    sync_called = threading.Event()
    gate_lock = threading.Lock()
    gate_first_call = True
    original_get_checkpoint = SyncEngine.get_checkpoint

    def gated_get_checkpoint(self, connector_id):
        nonlocal gate_first_call
        with gate_lock:
            should_gate = gate_first_call
            gate_first_call = False
        if should_gate:
            baseline_started.set()
            assert release_baseline.wait(timeout=3)
        return original_get_checkpoint(self, connector_id)

    monkeypatch.setattr(SyncEngine, "get_checkpoint", gated_get_checkpoint)

    class RacingConnector:
        connector_id = "obsidian"
        indexed_sources = ("obsidian",)

        def __init__(self):
            self.connected = True

        def is_connected(self):
            return self.connected

        def sync(self, **kwargs):
            sync_called.set()
            yield Document(
                doc_id="obsidian:post-disconnect",
                source="obsidian",
                doc_type="note",
                content="must never be written",
            )

        def disconnect(self):
            self.connected = False

        def sync_status(self):
            return SyncStatus()

    _instances["obsidian"] = RacingConnector()
    sync_response = []
    disconnect_response = []
    disconnect_done = threading.Event()

    def trigger_sync():
        sync_response.append(app.post("/v1/connectors/obsidian/sync"))

    def disconnect():
        disconnect_response.append(app.post("/v1/connectors/obsidian/disconnect"))
        disconnect_done.set()

    request_thread = threading.Thread(target=trigger_sync)
    disconnect_thread = threading.Thread(target=disconnect)
    try:
        request_thread.start()
        assert baseline_started.wait(timeout=3)

        disconnect_thread.start()
        # The checkpoint snapshot and thread publication are one lifecycle
        # operation. Disconnect must not overtake it and purge too early.
        assert not disconnect_done.wait(timeout=0.1)

        release_baseline.set()
        request_thread.join(timeout=3)
        disconnect_thread.join(timeout=3)
        assert not request_thread.is_alive()
        assert not disconnect_thread.is_alive()
        assert sync_response[0].status_code == 200
        assert sync_response[0].json()["status"] == "started"
        assert disconnect_response[0].status_code == 200

        from openjarvis.connectors.store import KnowledgeStore

        with KnowledgeStore() as store:
            assert not any(
                result.metadata.get("doc_id") == "obsidian:post-disconnect"
                for result in store.retrieve("must never be written", top_k=10)
            )
    finally:
        release_baseline.set()
        request_thread.join(timeout=3)
        disconnect_thread.join(timeout=3)
        _instances.pop("obsidian", None)


def test_disconnect_preserves_source_owned_by_connected_peer(app) -> None:
    from openjarvis.connectors._stubs import SyncStatus
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.server.connectors_router import _instances

    class FakeConnector:
        def __init__(self, connector_id, indexed_sources=()):
            self.connector_id = connector_id
            self.indexed_sources = indexed_sources
            self.connected = True

        def is_connected(self):
            return self.connected

        def disconnect(self):
            self.connected = False

        def sync_status(self):
            return SyncStatus()

    _instances["gmail"] = FakeConnector("gmail")
    _instances["gmail_imap"] = FakeConnector("gmail_imap", ("gmail",))
    try:
        with KnowledgeStore() as store:
            store.store(
                content="shared gmail ownership sentinel",
                source="gmail",
                doc_type="email",
                doc_id="gmail:shared-owner",
            )

        response = app.post("/v1/connectors/gmail_imap/disconnect")
        assert response.status_code == 200

        with KnowledgeStore() as store:
            assert any(
                result.metadata.get("doc_id") == "gmail:shared-owner"
                for result in store.retrieve("ownership sentinel", top_k=10)
            )
            store.delete_by_source("gmail")
    finally:
        _instances.pop("gmail", None)
        _instances.pop("gmail_imap", None)


def test_disconnect_restores_checkpoint_when_purge_fails(app, monkeypatch) -> None:
    from openjarvis.connectors.pipeline import IngestionPipeline
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.connectors.sync_engine import SyncEngine
    from openjarvis.server.connectors_router import _instances

    class FakeObsidian:
        indexed_sources = ("obsidian",)

        def is_connected(self):
            return True

        def disconnect(self):
            pass

    with KnowledgeStore() as store:
        with SyncEngine(pipeline=IngestionPipeline(store=store)) as engine:
            engine._save_checkpoint("obsidian", 17, cursor="keep-me")

    def fail_purge(self, sources):
        raise RuntimeError("simulated purge failure")

    monkeypatch.setattr(KnowledgeStore, "delete_by_sources", fail_purge)
    _instances["obsidian"] = FakeObsidian()
    try:
        response = app.post("/v1/connectors/obsidian/disconnect")
        assert response.status_code == 500
        with KnowledgeStore() as store:
            with SyncEngine(pipeline=IngestionPipeline(store=store)) as engine:
                checkpoint = engine.get_checkpoint("obsidian")
                assert checkpoint is not None
                assert checkpoint["items_synced"] == 17
                assert checkpoint["cursor"] == "keep-me"
                engine.reset_checkpoint("obsidian")
    finally:
        _instances.pop("obsidian", None)


def test_sync_status(app):
    """GET /v1/connectors/obsidian/sync returns a response with a state field."""
    resp = app.get("/v1/connectors/obsidian/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert data["connector_id"] == "obsidian"


def test_trigger_sync(app, tmp_path: Path) -> None:
    """POST /v1/connectors/obsidian/sync triggers an incremental sync.

    The endpoint is intentionally fire-and-forget — it starts the sync in
    a background thread and returns immediately with ``status=started``.
    Sync progress is observable via the separate ``GET .../sync`` endpoint.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Test note\n\nContent here.")
    app.post("/v1/connectors/obsidian/connect", json={"path": str(vault)})
    resp = app.post("/v1/connectors/obsidian/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["status"] in {"started", "already_syncing"}


# ---------------------------------------------------------------------------
# Connect-time credential validation (GH #409): the /connect endpoint must
# reject invalid credentials with HTTP 400 and never persist (or overwrite)
# anything on disk when validation fails.
# ---------------------------------------------------------------------------


def test_connect_slack_bot_token_returns_400(app, tmp_path: Path) -> None:
    """POST connect with an xoxb- token is rejected 400 and writes nothing."""
    from openjarvis.connectors.slack_connector import SlackConnector
    from openjarvis.server.connectors_router import _instances

    creds = tmp_path / "slack.json"
    _instances["slack"] = SlackConnector(credentials_path=str(creds))
    try:
        resp = app.post(
            "/v1/connectors/slack/connect", json={"token": "xoxb-fake-token"}
        )
        assert resp.status_code == 400
        assert "xoxb" in resp.json()["detail"].lower()
        assert not creds.exists()
    finally:
        _instances.pop("slack", None)


def test_connect_granola_invalid_key_returns_400_keeps_existing(
    app, tmp_path: Path
) -> None:
    """A bad Granola key is rejected 400 and the existing credential survives."""
    import json
    from unittest.mock import patch

    from openjarvis.connectors.granola import GranolaConnector, GranolaKeyError
    from openjarvis.server.connectors_router import _instances

    creds = tmp_path / "granola.json"
    creds.write_text(json.dumps({"token": "grl_real_existing_key"}))
    _instances["granola"] = GranolaConnector(credentials_path=str(creds))
    try:
        with patch(
            "openjarvis.connectors.granola._granola_api_validate_key",
            side_effect=GranolaKeyError(
                "Invalid API key. Check your key in Granola Settings → API."
            ),
        ):
            resp = app.post(
                "/v1/connectors/granola/connect",
                json={"code": "fake-key-12345"},
            )
        assert resp.status_code == 400
        assert "Invalid API key" in resp.json()["detail"]
        # The previously-working credential must be untouched.
        assert json.loads(creds.read_text())["token"] == "grl_real_existing_key"
    finally:
        _instances.pop("granola", None)


@pytest.mark.parametrize(
    ("connector_id", "filename", "payload", "expected"),
    [
        (
            "github_notifications",
            "github.json",
            {"token": "ghp_test"},
            {"token": "ghp_test"},
        ),
        ("oura", "oura.json", {"token": "oura_test"}, {"token": "oura_test"}),
        (
            "weather",
            "weather.json",
            {"token": "weather_key", "config": {"location": "Boston,US"}},
            {"api_key": "weather_key", "location": "Boston,US"},
        ),
    ],
)
def test_connect_persists_generic_token_connector_credentials(
    app,
    tmp_path: Path,
    monkeypatch,
    connector_id: str,
    filename: str,
    payload: dict,
    expected: dict,
) -> None:
    """The generic token panel must actually configure each token connector."""

    from openjarvis.connectors.github_notifications import GitHubNotificationsConnector
    from openjarvis.connectors.oura import OuraConnector
    from openjarvis.connectors.weather import WeatherConnector
    from openjarvis.core.registry import ConnectorRegistry
    from openjarvis.server.connectors_router import _instances

    path = tmp_path / filename
    constructors = {
        "github_notifications": lambda: GitHubNotificationsConnector(
            token_path=str(path)
        ),
        "oura": lambda: OuraConnector(token_path=str(path)),
        "weather": lambda: WeatherConnector(token_path=str(path)),
    }
    instance = constructors[connector_id]()
    ConnectorRegistry.register_value(connector_id, type(instance))
    validators = {
        "github_notifications": (
            "openjarvis.connectors.github_notifications._github_api_get",
            [],
        ),
        "oura": ("openjarvis.connectors.oura._oura_api_get", {}),
        "weather": ("openjarvis.connectors.weather._weather_api_get", {}),
    }
    target, result = validators[connector_id]
    monkeypatch.setattr(target, lambda *args, **kwargs: result)
    # The endpoint deliberately starts an asynchronous initial sync.  Replace
    # it with an empty iterator so this endpoint test never reaches a real API.
    instance.sync = lambda **_kwargs: iter(())
    _instances[connector_id] = instance
    try:
        resp = app.post(f"/v1/connectors/{connector_id}/connect", json=payload)
        assert resp.status_code == 200, resp.text
        assert resp.json()["connected"] is True
        assert json.loads(path.read_text()) == expected
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        _instances.pop(connector_id, None)


def test_invalid_token_is_not_persisted_or_synced(app, tmp_path, monkeypatch) -> None:
    """Validation failure preserves an existing credential byte-for-byte."""
    from openjarvis.connectors.github_notifications import (
        GitHubNotificationsConnector,
    )
    from openjarvis.core.registry import ConnectorRegistry
    from openjarvis.server.connectors_router import _instances

    path = tmp_path / "github.json"
    original = '{"token":"known-good"}'
    path.write_text(original, encoding="utf-8")
    instance = GitHubNotificationsConnector(token_path=str(path))
    ConnectorRegistry.register_value("github_notifications", type(instance))
    sync_called = False

    def sync(**kwargs):
        nonlocal sync_called
        sync_called = True
        return iter(())

    instance.sync = sync
    monkeypatch.setattr(
        "openjarvis.connectors.github_notifications._github_api_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("401 Unauthorized")),
    )
    _instances["github_notifications"] = instance
    try:
        response = app.post(
            "/v1/connectors/github_notifications/connect",
            json={"token": "bad-token"},
        )
        assert response.status_code == 400
        assert path.read_text(encoding="utf-8") == original
        assert sync_called is False
    finally:
        _instances.pop("github_notifications", None)


def test_connect_weather_requires_location(app, tmp_path: Path) -> None:
    """Weather must not report connected with an API key it cannot use."""
    from openjarvis.connectors.weather import WeatherConnector
    from openjarvis.server.connectors_router import _instances

    path = tmp_path / "weather.json"
    _instances["weather"] = WeatherConnector(token_path=str(path))
    try:
        resp = app.post("/v1/connectors/weather/connect", json={"token": "weather_key"})
        assert resp.status_code == 400
        assert "location" in resp.json()["detail"].lower()
        assert not path.exists()
    finally:
        _instances.pop("weather", None)


def test_connect_news_rss_requires_and_persists_feeds(app, tmp_path: Path) -> None:
    """A local connector with required setup cannot claim success for ``{}``."""
    from openjarvis.connectors.news_rss import NewsRSSConnector
    from openjarvis.server.connectors_router import _instances

    path = tmp_path / "news_rss.json"
    instance = NewsRSSConnector(config_path=str(path))
    instance.sync = lambda **_kwargs: iter(())
    _instances["news_rss"] = instance
    try:
        assert app.post("/v1/connectors/news_rss/connect", json={}).status_code == 400
        resp = app.post(
            "/v1/connectors/news_rss/connect",
            json={"config": {"feeds": [{"url": "https://example.com/feed.xml"}]}},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["connected"] is True
        assert json.loads(path.read_text())["feeds"] == [
            {"name": "example.com", "url": "https://example.com/feed.xml"}
        ]
    finally:
        _instances.pop("news_rss", None)
