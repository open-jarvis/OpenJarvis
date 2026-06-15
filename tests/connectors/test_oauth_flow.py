"""Tests for OAuth token exchange and Google connector integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def test_exchange_google_token_calls_endpoint() -> None:
    from openjarvis.connectors.oauth import exchange_google_token

    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "access_token": "ya29.test",
        "refresh_token": "1//test",
        "token_type": "Bearer",
        "expires_in": 3600,
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        tokens = exchange_google_token(
            code="4/test-code",
            client_id="test-id.apps.googleusercontent.com",
            client_secret="test-secret",
        )

    assert tokens["access_token"] == "ya29.test"
    assert tokens["refresh_token"] == "1//test"
    mock_post.assert_called_once()


def test_gdrive_handle_callback_persists_creds_no_background_flow(
    tmp_path: Path,
) -> None:
    """A pasted client pair persists creds ONLY — no silent browser thread.

    Regression for issue #512: the previous implementation spawned a daemon
    thread that popped a browser and ran its own localhost:8789 callback
    server. That thread failed silently in the bundled desktop context, so the
    connector never gained an access token. ``handle_callback`` must now only
    save the client_id/secret; the in-process server flow owns the consent
    round-trip. We assert ``open_browser`` is never invoked.
    """
    from openjarvis.connectors.gdrive import GDriveConnector
    from openjarvis.connectors.oauth import load_tokens

    creds = str(tmp_path / "gdrive.json")
    conn = GDriveConnector(credentials_path=creds)

    with patch("openjarvis.core.open_browser") as mock_browser:
        conn.handle_callback("test-id.apps.googleusercontent.com:test-secret")

    mock_browser.assert_not_called()
    tokens = load_tokens(creds)
    assert tokens is not None
    assert tokens["client_id"] == "test-id.apps.googleusercontent.com"
    assert tokens["client_secret"] == "test-secret"
    # No access token yet — that arrives via /oauth/callback.
    assert not tokens.get("access_token")
    assert conn.is_connected() is False


def test_gdrive_is_connected_requires_access_token(tmp_path: Path) -> None:
    from openjarvis.connectors.gdrive import GDriveConnector
    from openjarvis.connectors.oauth import save_tokens

    creds = str(tmp_path / "gdrive.json")
    conn = GDriveConnector(credentials_path=creds)

    # Just client_id is not "connected"
    save_tokens(creds, {"client_id": "test-id"})
    assert conn.is_connected() is False

    # With access_token IS connected
    save_tokens(creds, {"access_token": "ya29.test", "client_id": "test-id"})
    assert conn.is_connected() is True


def test_gcalendar_handle_callback_persists_creds_no_background_flow(
    tmp_path: Path,
) -> None:
    """Sibling connector shares the fix: creds saved, no browser thread (#512)."""
    from openjarvis.connectors.gcalendar import GCalendarConnector
    from openjarvis.connectors.oauth import load_tokens

    creds = str(tmp_path / "gcalendar.json")
    conn = GCalendarConnector(credentials_path=creds)

    with patch("openjarvis.core.open_browser") as mock_browser:
        conn.handle_callback("test-id.apps.googleusercontent.com:test-secret")

    mock_browser.assert_not_called()
    tokens = load_tokens(creds)
    assert tokens is not None
    assert tokens["client_id"] == "test-id.apps.googleusercontent.com"
    assert tokens["client_secret"] == "test-secret"
    assert conn.is_connected() is False


def test_gcontacts_handle_callback_persists_creds_no_background_flow(
    tmp_path: Path,
) -> None:
    """Sibling connector shares the fix: creds saved, no browser thread (#512)."""
    from openjarvis.connectors.gcontacts import GContactsConnector
    from openjarvis.connectors.oauth import load_tokens

    creds = str(tmp_path / "gcontacts.json")
    conn = GContactsConnector(credentials_path=creds)

    with patch("openjarvis.core.open_browser") as mock_browser:
        conn.handle_callback("test-id.apps.googleusercontent.com:test-secret")

    mock_browser.assert_not_called()
    tokens = load_tokens(creds)
    assert tokens is not None
    assert tokens["client_id"] == "test-id.apps.googleusercontent.com"
    assert tokens["client_secret"] == "test-secret"
    assert conn.is_connected() is False


def test_gdrive_handle_callback_raw_token(tmp_path: Path) -> None:
    from openjarvis.connectors.gdrive import GDriveConnector
    from openjarvis.connectors.oauth import load_tokens

    creds = str(tmp_path / "gdrive.json")
    conn = GDriveConnector(credentials_path=creds)

    conn.handle_callback("some-raw-token-value")

    tokens = load_tokens(creds)
    assert tokens is not None
    assert tokens["token"] == "some-raw-token-value"


def test_gdrive_auth_url_returns_credentials_page_without_client_id(
    tmp_path: Path,
) -> None:
    from openjarvis.connectors.gdrive import GDriveConnector

    creds = str(tmp_path / "gdrive.json")
    conn = GDriveConnector(credentials_path=creds)

    url = conn.auth_url()
    assert url == "https://console.cloud.google.com/apis/credentials"


def test_gdrive_auth_url_returns_consent_url_with_client_id(
    tmp_path: Path,
) -> None:
    from openjarvis.connectors.gdrive import GDriveConnector
    from openjarvis.connectors.oauth import save_tokens

    creds = str(tmp_path / "gdrive.json")
    conn = GDriveConnector(credentials_path=creds)

    save_tokens(creds, {"client_id": "test-id.apps.googleusercontent.com"})
    url = conn.auth_url()
    assert "accounts.google.com" in url
    assert "test-id.apps.googleusercontent.com" in url
