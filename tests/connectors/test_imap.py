"""Tests for IMAPConnector — generic IMAP connector with domain-resolved hosts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from openjarvis.connectors.imap import IMAPConnector, resolve_imap_host
from openjarvis.connectors.oauth import load_tokens
from openjarvis.core.registry import ConnectorRegistry


def test_imap_registered() -> None:
    ConnectorRegistry.register_value("imap", IMAPConnector)
    assert ConnectorRegistry.contains("imap")
    cls = ConnectorRegistry.get("imap")
    assert cls.connector_id == "imap"
    assert cls.display_name == "Email (IMAP)"


def test_resolve_known_provider_host() -> None:
    assert resolve_imap_host("user@gmail.com") == "imap.gmail.com"
    assert resolve_imap_host("user@outlook.com") == "outlook.office365.com"
    assert resolve_imap_host("user@fastmail.com") == "imap.fastmail.com"


def test_resolve_unknown_domain_falls_back() -> None:
    assert resolve_imap_host("user@example.org") == "imap.example.org"
    assert resolve_imap_host("not-an-email") == ""


def test_imap_handle_callback(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "imap.json")
    conn = IMAPConnector(credentials_path=creds_path)
    conn.handle_callback("user@example.org:mypassword123")
    tokens = load_tokens(creds_path)
    assert tokens is not None
    assert tokens["email"] == "user@example.org"
    assert tokens["password"] == "mypassword123"
    assert tokens["imap_host"] == "imap.example.org"


def test_imap_is_connected(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "imap.json")
    conn = IMAPConnector(credentials_path=creds_path)
    assert conn.is_connected() is False
    conn.handle_callback("user@example.org:pass")
    assert conn.is_connected() is True


def test_imap_sync_uses_resolved_host_and_source(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "imap.json")
    conn = IMAPConnector(credentials_path=creds_path)
    conn.handle_callback("user@example.org:pass")

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [])
    mock_imap.select.return_value = ("OK", [])
    mock_imap.search.return_value = ("OK", [b"1"])

    raw_email = (
        b"From: sender@test.com\r\n"
        b"To: user@example.org\r\n"
        b"Subject: Test Email\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
        b"Message-ID: <test123@test.com>\r\n"
        b"\r\n"
        b"Hello from IMAP test"
    )
    mock_imap.fetch.return_value = ("OK", [(b"1", raw_email)])
    mock_imap.logout.return_value = ("OK", [])

    with patch("openjarvis.connectors.gmail_imap.imaplib") as mock_imaplib:
        mock_imaplib.IMAP4_SSL.return_value = mock_imap
        mock_imaplib.IMAP4 = type(mock_imap)
        docs = list(conn.sync())

    mock_imaplib.IMAP4_SSL.assert_called_once_with("imap.example.org")
    assert len(docs) == 1
    assert docs[0].source == "imap"
    assert docs[0].doc_id.startswith("imap:")
    assert docs[0].title == "Test Email"


def test_imap_sync_handles_raw_8bit_headers(tmp_path: Path) -> None:
    import json

    creds_path = str(tmp_path / "imap.json")
    conn = IMAPConnector(credentials_path=creds_path)
    conn.handle_callback("user@example.org:pass")

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [])
    mock_imap.select.return_value = ("OK", [])
    mock_imap.search.return_value = ("OK", [b"1"])
    # Raw 8-bit (non-RFC2047) bytes in From/To/Subject -> Header objects.
    raw_email = (
        b"From: Jos\xe9 <jose@test.com>\r\n"
        b"To: caf\xe9 <user@example.org>\r\n"
        b"Subject: caf\xe9 meeting\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
        b"Message-ID: <test123@test.com>\r\n"
        b"\r\n"
        b"body"
    )
    mock_imap.fetch.return_value = ("OK", [(b"1", raw_email)])
    mock_imap.logout.return_value = ("OK", [])

    with patch("openjarvis.connectors.gmail_imap.imaplib") as mock_imaplib:
        mock_imaplib.IMAP4_SSL.return_value = mock_imap
        mock_imaplib.IMAP4 = type(mock_imap)
        docs = list(conn.sync())

    assert len(docs) == 1
    d = docs[0]
    assert isinstance(d.author, str)
    assert isinstance(d.title, str)
    assert all(isinstance(p, str) for p in d.participants)
    # The fields must be JSON-serializable (the bug was a Header reaching json.dumps).
    json.dumps(
        {
            "author": d.author,
            "title": d.title,
            "participants": d.participants,
            **d.metadata,
        }
    )


def test_imap_sync_reconnects_on_dropped_connection(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "imap.json")
    conn = IMAPConnector(credentials_path=creds_path)
    conn.handle_callback("user@example.org:pass")

    raw_email = (
        b"From: a@test.com\r\nTo: user@example.org\r\nSubject: Hi\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
        b"Message-ID: <m1@test.com>\r\n\r\nbody"
    )

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [])
    mock_imap.select.return_value = ("OK", [])
    mock_imap.search.return_value = ("OK", [b"1"])
    # First fetch drops the TLS connection; after reconnect it succeeds.
    mock_imap.fetch.side_effect = [
        OSError("[SSL: BAD_LENGTH] bad length"),
        ("OK", [(b"1", raw_email)]),
    ]
    mock_imap.logout.return_value = ("OK", [])

    with patch("openjarvis.connectors.gmail_imap.imaplib") as mock_imaplib:
        mock_imaplib.IMAP4_SSL.return_value = mock_imap
        docs = list(conn.sync())

    # Reconnected (opened the connection twice) and still indexed the message.
    assert mock_imaplib.IMAP4_SSL.call_count >= 2
    assert len(docs) == 1
    assert docs[0].doc_id.startswith("imap:")
