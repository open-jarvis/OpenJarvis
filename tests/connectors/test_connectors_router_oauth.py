"""Regression tests for the connectors-router OAuth flow (issue #512).

These tests reproduce the three coupled defects that prevented Google Drive
(and its Google siblings) from ever completing OAuth and appearing in Data
Sources, and assert the fixed behaviour:

(A/B) ``POST /connect`` with a pasted ``client_id:client_secret`` pair must
      persist the client credentials and return an ``oauth_required`` directive
      pointing at ``/oauth/start`` — NOT silently spawn a background browser
      thread and report a perpetual ``pending`` state.
(C-1) ``GET /oauth/start`` must return a redirect to the provider's consent
      page (regression: HTTP 422 because ``request: Request`` was mis-bound as
      a query param under ``from __future__ import annotations`` + a local
      ``Request`` import).
(C-2) ``GET /oauth/callback`` must read ``request.base_url`` and exchange the
      code for tokens without crashing (regression: ``request`` defaulted to
      ``None`` → ``AttributeError``), persisting the access token to every
      Google credential file and flipping ``is_connected()`` to True.

All tests are hermetic: the connectors directory, the shared Google
credentials path, and every Google connector's default credentials path are
redirected to ``tmp_path`` so the suite neither depends on nor pollutes
``~/.openjarvis/connectors`` (a real source of spurious failures — see the
verifier note on ``resolve_google_credentials`` silently substituting the
shared file when the caller-supplied path does not yet exist on disk).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="requires the 'server' extra")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

_CLIENT_PAIR = "myid-123.apps.googleusercontent.com:GOCSPX-secret"
_CLIENT_ID = "myid-123.apps.googleusercontent.com"

_ALL_GOOGLE_FILES = (
    "google.json",
    "gdrive.json",
    "gcalendar.json",
    "gcontacts.json",
    "gmail.json",
    "google_tasks.json",
)


@pytest.fixture()
def hermetic_connectors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect all Google credential paths into *tmp_path*.

    Ensures connector instances created by the router's ``_get_or_create``
    resolve to the same directory the OAuth callback writes to, and that the
    test leaves ``~/.openjarvis`` untouched.

    Why this is more than a one-line monkeypatch: the autouse registry-clear
    fixture causes ``_ensure_connectors_registered()`` to ``importlib.reload``
    each connector module on the first router call, which re-executes the
    module body. To survive that reload we patch ``DEFAULT_CONFIG_DIR`` at its
    *source* (``openjarvis.core.config``) — every connector re-derives
    ``_DEFAULT_CREDENTIALS_PATH`` from it on reload, so the tmp dir sticks.
    We also pre-register + pre-reload the connectors inside the fixture so the
    reload happens while the patch is live, then reset module state on
    teardown so a later test that imports these modules fresh is unaffected.
    """
    import importlib
    import sys

    import openjarvis.connectors.oauth as oauth_mod
    import openjarvis.core.config as config_mod
    import openjarvis.server.connectors_router as router_mod
    from openjarvis.core.registry import ConnectorRegistry

    conn_dir = tmp_path / "connectors"
    conn_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(oauth_mod, "_CONNECTORS_DIR", conn_dir)
    monkeypatch.setattr(
        oauth_mod, "_SHARED_GOOGLE_CREDENTIALS_PATH", str(conn_dir / "google.json")
    )

    # Force the connector modules to re-derive their default paths from the
    # patched DEFAULT_CONFIG_DIR now, before any request, and register them so
    # the router's lazy reload-on-empty-registry path is a no-op.
    google_mods = [
        "openjarvis.connectors.gdrive",
        "openjarvis.connectors.gcalendar",
        "openjarvis.connectors.gcontacts",
        "openjarvis.connectors.gmail",
        "openjarvis.connectors.google_tasks",
    ]
    for name in google_mods:
        if name in sys.modules:
            importlib.reload(sys.modules[name])

    router_mod._instances.clear()
    yield conn_dir
    router_mod._instances.clear()
    ConnectorRegistry.clear()
    # Restore the connector modules to their real (unpatched) default paths so
    # subsequent tests in the same process see ~/.openjarvis again.
    for name in google_mods:
        if name in sys.modules:
            importlib.reload(sys.modules[name])


@pytest.fixture()
def client(hermetic_connectors: Path) -> Iterator[TestClient]:
    from openjarvis.server.connectors_router import create_connectors_router

    app = FastAPI()
    app.include_router(create_connectors_router())
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Defect A/B — POST /connect must not silently spawn a background OAuth thread
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "connector_id", ["gdrive", "gcalendar", "gcontacts", "gmail", "google_tasks"]
)
def test_connect_client_pair_returns_oauth_required_no_browser(
    client: TestClient, hermetic_connectors: Path, connector_id: str
) -> None:
    """Pasting client_id:secret persists creds + asks the UI to run the flow.

    Covers every Google connector that shares the OAuth provider, proving the
    sibling connectors are fixed too (not just gdrive).
    """
    with patch("openjarvis.core.open_browser") as mock_browser:
        resp = client.post(
            f"/v1/connectors/{connector_id}/connect", json={"code": _CLIENT_PAIR}
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "oauth_required"
    assert body["oauth_start"] == f"/v1/connectors/{connector_id}/oauth/start"
    assert body["connected"] is False
    # No fire-and-forget browser thread (the root cause of "nothing happens").
    mock_browser.assert_not_called()

    # Client credentials persisted to EVERY Google credential file so a single
    # consent covers all Google connectors.
    for filename in _ALL_GOOGLE_FILES:
        path = hermetic_connectors / filename
        assert path.exists(), f"{filename} not written"
        assert json.loads(path.read_text())["client_id"] == _CLIENT_ID


def test_connect_malformed_client_pair_raises_400(
    client: TestClient,
) -> None:
    """A blank secret surfaces an actionable 400 — not a silent pending state."""
    resp = client.post(
        "/v1/connectors/gdrive/connect",
        json={"code": "myid-123.apps.googleusercontent.com:"},
    )
    assert resp.status_code == 400
    assert "CLIENT_ID:CLIENT_SECRET" in resp.json()["detail"]


def test_connect_raw_token_still_handled(
    client: TestClient, hermetic_connectors: Path
) -> None:
    """A raw token (not a client pair) still flows through handle_callback."""
    resp = client.post(
        "/v1/connectors/gdrive/connect", json={"token": "ya29.raw-access-token"}
    )
    assert resp.status_code == 200, resp.text
    saved = json.loads((hermetic_connectors / "gdrive.json").read_text())
    assert saved.get("token") == "ya29.raw-access-token"


# ---------------------------------------------------------------------------
# Defect C-1 — GET /oauth/start must redirect (was HTTP 422)
# ---------------------------------------------------------------------------


def test_oauth_start_redirects_to_consent(
    client: TestClient,
) -> None:
    # First save client creds via the connect call.
    client.post("/v1/connectors/gdrive/connect", json={"code": _CLIENT_PAIR})

    resp = client.get("/v1/connectors/gdrive/oauth/start", follow_redirects=False)
    # FastAPI's RedirectResponse defaults to 307; any 3xx is a pass (was 422).
    assert resp.status_code in (302, 307), resp.text
    location = resp.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert _CLIENT_ID in location
    # redirect_uri must point back at OUR in-process callback.
    assert "oauth%2Fcallback" in location or "oauth/callback" in location


def test_oauth_start_without_creds_returns_400(client: TestClient) -> None:
    resp = client.get("/v1/connectors/gdrive/oauth/start", follow_redirects=False)
    assert resp.status_code == 400
    assert "client credentials" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Defect C-2 — GET /oauth/callback must exchange + persist (was 500 on None)
# ---------------------------------------------------------------------------


def test_oauth_callback_exchanges_and_connects(
    client: TestClient, hermetic_connectors: Path
) -> None:
    import openjarvis.connectors.oauth as oauth_mod

    client.post("/v1/connectors/gdrive/connect", json={"code": _CLIENT_PAIR})

    fake_tokens = {
        "access_token": "ya29.REAL",
        "refresh_token": "1//REAL",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    with patch.object(oauth_mod, "_exchange_token", return_value=fake_tokens) as ex:
        resp = client.get("/v1/connectors/gdrive/oauth/callback?code=authcode123")

    assert resp.status_code == 200, resp.text
    assert "Connected!" in resp.text
    ex.assert_called_once()

    # Access token written to ALL Google credential files.
    for filename in _ALL_GOOGLE_FILES:
        saved = json.loads((hermetic_connectors / filename).read_text())
        assert saved["access_token"] == "ya29.REAL"
        assert saved["refresh_token"] == "1//REAL"

    # The connector now reports connected, and GET /connectors agrees.
    from openjarvis.connectors.gdrive import GDriveConnector

    assert GDriveConnector().is_connected() is True

    listing = client.get("/v1/connectors").json()["connectors"]
    gdrive = next(c for c in listing if c["connector_id"] == "gdrive")
    assert gdrive["connected"] is True


def test_oauth_callback_error_param_renders_failure(client: TestClient) -> None:
    resp = client.get("/v1/connectors/gdrive/oauth/callback?error=access_denied")
    assert resp.status_code == 400
    assert "access_denied" in resp.text


def test_oauth_callback_exchange_failure_renders_error(
    client: TestClient,
) -> None:
    import openjarvis.connectors.oauth as oauth_mod

    client.post("/v1/connectors/gdrive/connect", json={"code": _CLIENT_PAIR})

    def _boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise RuntimeError("token endpoint 400")

    with patch.object(oauth_mod, "_exchange_token", side_effect=_boom):
        resp = client.get("/v1/connectors/gdrive/oauth/callback?code=bad")

    assert resp.status_code == 500
    assert "Token Exchange Failed" in resp.text
