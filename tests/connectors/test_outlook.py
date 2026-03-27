"""Tests for OutlookConnector — thin subclass of GmailIMAPConnector."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from openjarvis.connectors.oauth import load_tokens
from openjarvis.connectors.outlook import OutlookConnector
from openjarvis.core.registry import ConnectorRegistry


def test_outlook_registered() -> None:
    ConnectorRegistry.register_value("outlook", OutlookConnector)
    assert ConnectorRegistry.contains("outlook")
    cls = ConnectorRegistry.get("outlook")
    assert cls.connector_id == "outlook"
    assert cls.display_name == "Outlook / Microsoft 365"


def test_outlook_uses_correct_imap_host() -> None:
    conn = OutlookConnector()
    assert conn._imap_host == "outlook.office365.com"


def test_outlook_auth_url() -> None:
    conn = OutlookConnector()
    assert "microsoft.com" in conn.auth_url()


def test_outlook_handle_callback(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "outlook.json")
    conn = OutlookConnector(credentials_path=creds_path)
    conn.handle_callback("user@outlook.com:mypassword123")
    tokens = load_tokens(creds_path)
    assert tokens is not None
    assert tokens["email"] == "user@outlook.com"
    assert tokens["password"] == "mypassword123"


def test_outlook_is_connected(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "outlook.json")
    conn = OutlookConnector(credentials_path=creds_path)
    assert conn.is_connected() is False
    conn.handle_callback("user@outlook.com:pass")
    assert conn.is_connected() is True


def test_outlook_sync_source_is_outlook(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "outlook.json")
    conn = OutlookConnector(credentials_path=creds_path)
    conn.handle_callback("user@outlook.com:pass")

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [])
    mock_imap.select.return_value = ("OK", [])
    mock_imap.search.return_value = ("OK", [b"1"])

    raw_email = (
        b"From: sender@test.com\r\n"
        b"To: user@outlook.com\r\n"
        b"Subject: Test Email\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
        b"Message-ID: <test123@test.com>\r\n"
        b"\r\n"
        b"Hello from Outlook test"
    )
    mock_imap.fetch.return_value = ("OK", [(b"1", raw_email)])
    mock_imap.logout.return_value = ("OK", [])

    with patch("openjarvis.connectors.gmail_imap.imaplib") as mock_imaplib:
        mock_imaplib.IMAP4_SSL.return_value = mock_imap
        mock_imaplib.IMAP4 = type(mock_imap)
        docs = list(conn.sync())

    assert len(docs) == 1
    assert docs[0].source == "outlook"
    assert docs[0].doc_id.startswith("outlook:")
    assert docs[0].title == "Test Email"
