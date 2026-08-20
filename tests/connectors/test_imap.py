"""Tests for the generic IMAP connector and its network boundary."""

from __future__ import annotations

import json
import socket
from imaplib import IMAP4
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.connectors.imap import (
    IMAPConnector,
    _create_pinned_socket,
    resolve_imap_host,
    validate_imap_endpoint,
)
from openjarvis.connectors.oauth import load_tokens
from openjarvis.core.registry import ConnectorRegistry


def _message(
    *,
    subject: bytes = b"Test Email",
    message_id: bytes = b"<test123@test.com>",
) -> bytes:
    return (
        b"From: sender@test.com\r\n"
        b"To: user@example.org\r\n"
        b"Subject: " + subject + b"\r\n"
        b"Date: Mon, 01 Jan 2024 00:00:00 +0000\r\n"
        b"Message-ID: " + message_id + b"\r\n\r\n"
        b"Hello from IMAP test"
    )


def _authenticated_client(uidvalidity: int = 777) -> MagicMock:
    client = MagicMock()
    client.login.return_value = ("OK", [])
    client.select.return_value = ("OK", [])
    client.response.return_value = ("UIDVALIDITY", [str(uidvalidity).encode("ascii")])
    client.logout.return_value = ("OK", [])
    return client


def _sync_client(raw_email: bytes | None = None) -> MagicMock:
    client = _authenticated_client()
    raw_email = raw_email or _message()

    def uid(command: str, *args):
        if command == "SEARCH":
            return "OK", [b"41"]
        if command == "FETCH":
            assert args == (b"41", "(RFC822)")
            return "OK", [(b"41 (RFC822 {1})", raw_email)]
        raise AssertionError(f"Unexpected UID command: {command}")

    client.uid.side_effect = uid
    return client


def _connect(connector: IMAPConnector, client: MagicMock | None = None) -> MagicMock:
    client = client or _authenticated_client()
    with patch.object(connector, "_make_imap_client", return_value=client):
        connector.handle_callback("user@example.org:pass")
    return client


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


def test_callback_validates_before_persisting(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "imap.json")
    conn = IMAPConnector(credentials_path=creds_path)
    client = _authenticated_client()

    with patch.object(conn, "_make_imap_client", return_value=client) as make_client:
        conn.handle_callback("user@example.org:mypassword123")

    make_client.assert_called_once_with("imap.example.org", 993, "tls")
    client.login.assert_called_once_with("user@example.org", "mypassword123")
    client.select.assert_called_once_with("INBOX", readonly=True)
    client.logout.assert_called_once()
    tokens = load_tokens(creds_path)
    assert tokens == {
        "email": "user@example.org",
        "password": "mypassword123",
        "imap_host": "imap.example.org",
        "imap_port": 993,
        "imap_security": "tls",
        "validated": True,
    }
    assert conn.is_connected() is True


def test_failed_login_is_not_persisted_or_connected(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "imap.json")
    conn = IMAPConnector(credentials_path=creds_path)
    client = _authenticated_client()
    client.login.side_effect = IMAP4.error("bad credentials")

    with (
        patch.object(conn, "_make_imap_client", return_value=client),
        pytest.raises(IMAP4.error, match="bad credentials"),
    ):
        conn.handle_callback("user@example.org:wrong")

    assert load_tokens(creds_path) is None
    assert conn.is_connected() is False
    client.logout.assert_called_once()


def test_missing_uidvalidity_is_not_persisted_or_connected(tmp_path: Path) -> None:
    creds_path = str(tmp_path / "imap.json")
    conn = IMAPConnector(credentials_path=creds_path)
    client = _authenticated_client()
    client.response.return_value = ("UIDVALIDITY", [None])

    with (
        patch.object(conn, "_make_imap_client", return_value=client),
        pytest.raises(IMAP4.error, match="UIDVALIDITY"),
    ):
        conn.handle_callback("user@example.org:secret")

    assert load_tokens(creds_path) is None
    assert conn.is_connected() is False
    client.logout.assert_called_once()


def test_unvalidated_legacy_credentials_are_not_connected(tmp_path: Path) -> None:
    creds_path = tmp_path / "imap.json"
    creds_path.write_text(
        json.dumps({"email": "user@example.org", "password": "old"}),
        encoding="utf-8",
    )
    assert IMAPConnector(credentials_path=str(creds_path)).is_connected() is False


def test_direct_credentials_do_not_inherit_stored_host_or_validation(
    tmp_path: Path,
) -> None:
    creds_path = tmp_path / "imap.json"
    creds_path.write_text(
        json.dumps(
            {
                "email": "old@example.org",
                "password": "old",
                "imap_host": "old.example.org",
                "imap_port": 1143,
                "imap_security": "starttls",
                "validated": True,
            }
        ),
        encoding="utf-8",
    )
    conn = IMAPConnector(
        email_address="new@gmail.com",
        app_password="new",
        credentials_path=str(creds_path),
    )

    assert conn.is_connected() is False
    assert conn._resolve_connection()[2:5] == ("imap.gmail.com", 993, "tls")


def test_explicit_starttls_settings_are_validated_and_persisted(
    tmp_path: Path,
) -> None:
    conn = IMAPConnector(credentials_path=str(tmp_path / "imap.json"))
    client = _authenticated_client()

    with patch.object(conn, "_make_imap_client", return_value=client) as make_client:
        conn.connect_with_credentials(
            "user@custom.example",
            "secret",
            imap_host="mail.custom.example",
            imap_port=1143,
            imap_security="STARTTLS",
        )

    make_client.assert_called_once_with("mail.custom.example", 1143, "starttls")
    tokens = load_tokens(conn._credentials_path)
    assert tokens is not None
    assert tokens["imap_host"] == "mail.custom.example"
    assert tokens["imap_port"] == 1143
    assert tokens["imap_security"] == "starttls"


@pytest.mark.parametrize(
    ("port", "security", "message"),
    [
        (0, "tls", "port"),
        (65536, "tls", "port"),
        (993, "plaintext", "security"),
    ],
)
def test_invalid_transport_settings_fail_before_connecting(
    port: int, security: str, message: str, tmp_path: Path
) -> None:
    conn = IMAPConnector(credentials_path=str(tmp_path / "imap.json"))
    with (
        patch.object(conn, "_make_imap_client") as make_client,
        pytest.raises(ValueError, match=message),
    ):
        conn.connect_with_credentials(
            "user@example.org",
            "secret",
            imap_port=port,
            imap_security=security,
        )
    make_client.assert_not_called()


@pytest.mark.parametrize(
    ("host", "address"),
    [
        ("localhost", None),
        ("metadata.google.internal", None),
        ("mail.local", None),
        ("127.0.0.1", "127.0.0.1"),
        ("10.0.0.8", "10.0.0.8"),
        ("169.254.169.254", "169.254.169.254"),
        ("::1", "::1"),
        ("100.64.0.1", "100.64.0.1"),
        ("224.0.0.1", "224.0.0.1"),
        ("239.255.255.250", "239.255.255.250"),
        ("ff02::1", "ff02::1"),
        ("::ffff:224.0.0.1", "::ffff:224.0.0.1"),
        ("0.0.0.0", "0.0.0.0"),
        ("::", "::"),
        ("240.0.0.1", "240.0.0.1"),
    ],
)
def test_endpoint_policy_rejects_local_and_nonpublic_hosts(
    host: str, address: str | None
) -> None:
    if address is None:
        with pytest.raises(ValueError, match="Private|local"):
            validate_imap_endpoint(host, 993)
        return
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 993, 0, 0) if family == socket.AF_INET6 else (address, 993)
    with (
        patch(
            "openjarvis.connectors.imap.socket.getaddrinfo",
            return_value=[(family, socket.SOCK_STREAM, 6, "", sockaddr)],
        ),
        pytest.raises(ValueError, match="non-public"),
    ):
        validate_imap_endpoint(host, 993)


def test_endpoint_policy_rejects_mixed_public_private_dns() -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 993)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 993)),
    ]
    with (
        patch("openjarvis.connectors.imap.socket.getaddrinfo", return_value=answers),
        pytest.raises(ValueError, match="non-public"),
    ):
        validate_imap_endpoint("mail.example.com", 993)


def test_endpoint_policy_returns_only_checked_public_addresses() -> None:
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 993)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 993)),
        (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            6,
            "",
            ("2606:2800:220:1:248:1893:25c8:1946", 993, 0, 0),
        ),
    ]
    with patch("openjarvis.connectors.imap.socket.getaddrinfo", return_value=answers):
        assert validate_imap_endpoint("MAIL.Example.COM.", 993) == (
            "mail.example.com",
            ("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
        )


def test_endpoint_policy_fails_closed_on_dns_error() -> None:
    with (
        patch(
            "openjarvis.connectors.imap.socket.getaddrinfo",
            side_effect=socket.gaierror("no result"),
        ),
        pytest.raises(ValueError, match="Unable to resolve"),
    ):
        validate_imap_endpoint("mail.example.com", 993)


def test_pinned_socket_connects_to_checked_ip_not_hostname() -> None:
    sentinel = object()
    with patch(
        "openjarvis.connectors.imap.socket.create_connection",
        return_value=sentinel,
    ) as create_connection:
        assert _create_pinned_socket("93.184.216.34", 993, 30) is sentinel
    create_connection.assert_called_once_with(("93.184.216.34", 993), 30)


def test_starttls_is_required_before_login() -> None:
    conn = IMAPConnector()
    client = _authenticated_client()
    client.starttls.return_value = ("OK", [])
    with (
        patch(
            "openjarvis.connectors.imap.validate_imap_endpoint",
            return_value=("mail.example.com", ("93.184.216.34",)),
        ),
        patch("openjarvis.connectors.imap._PinnedIMAP4", return_value=client),
    ):
        assert conn._make_imap_client("mail.example.com", 143, "starttls") is client
    client.starttls.assert_called_once()


def test_implicit_tls_uses_checked_ip_and_original_hostname() -> None:
    conn = IMAPConnector()
    client = _authenticated_client()
    context = MagicMock()
    with (
        patch(
            "openjarvis.connectors.imap.validate_imap_endpoint",
            return_value=("mail.example.com", ("93.184.216.34",)),
        ),
        patch(
            "openjarvis.connectors.imap.ssl.create_default_context",
            return_value=context,
        ),
        patch(
            "openjarvis.connectors.imap._PinnedIMAP4SSL",
            return_value=client,
        ) as pinned_tls,
    ):
        assert conn._make_imap_client("mail.example.com", 993, "tls") is client

    pinned_tls.assert_called_once_with(
        "mail.example.com",
        993,
        "93.184.216.34",
        ssl_context=context,
        timeout=30,
    )


def test_sync_uses_uids_and_generic_document_identity(tmp_path: Path) -> None:
    conn = IMAPConnector(
        email_address="user@example.org",
        app_password="secret",
        credentials_path=str(tmp_path / "imap.json"),
    )
    client = _sync_client()

    with patch.object(conn, "_make_imap_client", return_value=client):
        docs = list(conn.sync())

    assert client.uid.call_args_list[0].args == ("SEARCH", None, "ALL")
    assert client.uid.call_args_list[1].args == ("FETCH", b"41", "(RFC822)")
    client.search.assert_not_called()
    client.fetch.assert_not_called()
    assert len(docs) == 1
    assert docs[0].source == "imap"
    assert docs[0].doc_id == "imap:<test123@test.com>"
    assert docs[0].metadata["imap_uid"] == "41"
    assert docs[0].metadata["imap_uidvalidity"] == "777"
    assert docs[0].title == "Test Email"
    assert docs[0].url == ""
    client.logout.assert_called_once()


def test_missing_message_id_falls_back_to_uid() -> None:
    conn = IMAPConnector(email_address="user@example.org", app_password="secret")
    raw = _message(message_id=b"")
    client = _sync_client(raw)
    with patch.object(conn, "_make_imap_client", return_value=client):
        docs = list(conn.sync())
    assert docs[0].doc_id == "imap:777:41"


def test_generator_close_logs_out() -> None:
    conn = IMAPConnector(
        email_address="user@example.org",
        app_password="secret",
        max_messages=1,
    )
    client = _sync_client()

    with patch.object(conn, "_make_imap_client", return_value=client):
        generator = conn.sync()
        next(generator)
        generator.close()

    client.logout.assert_called_once()


def test_sync_failed_login_closes_socket_and_marks_disconnected() -> None:
    conn = IMAPConnector(email_address="user@example.org", app_password="bad")
    client = _authenticated_client()
    client.login.side_effect = IMAP4.error("bad credentials")

    with patch.object(conn, "_make_imap_client", return_value=client):
        assert list(conn.sync()) == []

    assert conn.is_connected() is False
    client.logout.assert_called_once()


def test_generic_imap_does_not_advertise_gmail_tools() -> None:
    assert IMAPConnector().mcp_tools() == []


def test_sync_handles_raw_8bit_headers() -> None:
    conn = IMAPConnector(email_address="user@example.org", app_password="pass")
    raw_email = _message(subject=b"caf\xe9 meeting")
    client = _sync_client(raw_email)

    with patch.object(conn, "_make_imap_client", return_value=client):
        docs = list(conn.sync())

    assert len(docs) == 1
    document = docs[0]
    assert isinstance(document.author, str)
    assert isinstance(document.title, str)
    assert all(isinstance(participant, str) for participant in document.participants)
    json.dumps(
        {
            "author": document.author,
            "title": document.title,
            "participants": document.participants,
            **document.metadata,
        }
    )


def test_sync_reconnects_by_uid_on_dropped_connection() -> None:
    conn = IMAPConnector(email_address="user@example.org", app_password="pass")
    first = _authenticated_client()

    def first_uid(command: str, *args):
        if command == "SEARCH":
            return "OK", [b"41"]
        raise OSError("[SSL: BAD_LENGTH] bad length")

    first.uid.side_effect = first_uid
    second = _authenticated_client()

    def second_uid(command: str, *args):
        assert command == "FETCH"
        assert args == (b"41", "(RFC822)")
        return "OK", [(b"41 (RFC822 {1})", _message())]

    second.uid.side_effect = second_uid

    with patch.object(conn, "_make_imap_client", side_effect=[first, second]):
        docs = list(conn.sync())

    assert len(docs) == 1
    assert docs[0].metadata["imap_uid"] == "41"
    assert docs[0].metadata["imap_uidvalidity"] == "777"
    first.logout.assert_called_once()
    second.logout.assert_called_once()


def test_sync_stops_if_uidvalidity_changes_during_reconnect() -> None:
    conn = IMAPConnector(email_address="user@example.org", app_password="pass")
    first = _authenticated_client(uidvalidity=777)

    def first_uid(command: str, *args):
        if command == "SEARCH":
            return "OK", [b"41"]
        raise OSError("connection dropped")

    first.uid.side_effect = first_uid
    second = _authenticated_client(uidvalidity=888)

    with patch.object(conn, "_make_imap_client", side_effect=[first, second]):
        assert list(conn.sync()) == []

    second.uid.assert_not_called()
    first.logout.assert_called_once()
    second.logout.assert_called_once()


def test_server_rejects_private_custom_host_without_saving_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fastapi = pytest.importorskip("fastapi")
    testclient = pytest.importorskip("fastapi.testclient")
    from openjarvis.server import connectors_router

    class HermeticIMAPConnector(IMAPConnector):
        def __init__(self) -> None:
            super().__init__(credentials_path=str(tmp_path / "imap.json"))

    ConnectorRegistry.register_value("imap", HermeticIMAPConnector)
    connectors_router._instances.clear()
    monkeypatch.setattr(
        "openjarvis.connectors.imap.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 1993))
        ],
    )
    app = fastapi.FastAPI()
    app.include_router(connectors_router.create_connectors_router())

    try:
        response = testclient.TestClient(app).post(
            "/v1/connectors/imap/connect",
            json={
                "email": "user@example.org",
                "password": "secret",
                "host": "mail.attacker.example",
                "port": 1993,
                "security": "tls",
            },
        )
    finally:
        ConnectorRegistry.clear()
        connectors_router._instances.clear()

    assert response.status_code == 400
    assert "non-public" in response.json()["detail"]
    assert not (tmp_path / "imap.json").exists()
