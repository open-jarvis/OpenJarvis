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


def test_gdrive_handle_callback_triggers_oauth(tmp_path: Path) -> None:
    from openjarvis.connectors.gdrive import GDriveConnector

    creds = str(tmp_path / "gdrive.json")
    conn = GDriveConnector(credentials_path=creds)

    with patch("openjarvis.connectors.gdrive.run_oauth_flow") as mock_flow:
        mock_flow.return_value = {"access_token": "ya29.test"}
        conn.handle_callback("test-id.apps.googleusercontent.com:test-secret")

    mock_flow.assert_called_once()
    call_kwargs = mock_flow.call_args
    assert "test-id.apps.googleusercontent.com" in str(call_kwargs)


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


def test_gcalendar_handle_callback_triggers_oauth(tmp_path: Path) -> None:
    from openjarvis.connectors.gcalendar import GCalendarConnector

    creds = str(tmp_path / "gcalendar.json")
    conn = GCalendarConnector(credentials_path=creds)

    with patch("openjarvis.connectors.gcalendar.run_oauth_flow") as mock_flow:
        mock_flow.return_value = {"access_token": "ya29.test"}
        conn.handle_callback("test-id.apps.googleusercontent.com:test-secret")

    mock_flow.assert_called_once()


def test_gcontacts_handle_callback_triggers_oauth(tmp_path: Path) -> None:
    from openjarvis.connectors.gcontacts import GContactsConnector

    creds = str(tmp_path / "gcontacts.json")
    conn = GContactsConnector(credentials_path=creds)

    with patch("openjarvis.connectors.gcontacts.run_oauth_flow") as mock_flow:
        mock_flow.return_value = {"access_token": "ya29.test"}
        conn.handle_callback("test-id.apps.googleusercontent.com:test-secret")

    mock_flow.assert_called_once()


def test_gdrive_handle_callback_fallback_on_failure(tmp_path: Path) -> None:
    from openjarvis.connectors.gdrive import GDriveConnector
    from openjarvis.connectors.oauth import load_tokens

    creds = str(tmp_path / "gdrive.json")
    conn = GDriveConnector(credentials_path=creds)

    with patch("openjarvis.connectors.gdrive.run_oauth_flow") as mock_flow:
        mock_flow.side_effect = RuntimeError("OAuth failed")
        conn.handle_callback("test-id.apps.googleusercontent.com:test-secret")

    # Should have saved client_id and client_secret as fallback
    tokens = load_tokens(creds)
    assert tokens is not None
    assert tokens["client_id"] == "test-id.apps.googleusercontent.com"
    assert tokens["client_secret"] == "test-secret"


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
