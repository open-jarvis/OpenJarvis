"""Tests for the Strato mail connector."""

from __future__ import annotations

from email.message import EmailMessage
from unittest.mock import patch

from openjarvis.core.registry import ConnectorRegistry


class _FakeIMAP:
    def __init__(self, raw_message: bytes) -> None:
        self.raw_message = raw_message
        self.logged_out = False

    def login(self, user: str, password: str) -> None:
        assert user == "andre@example.com"
        assert password == "secret"

    def select(self, mailbox: str, readonly: bool = False):
        assert mailbox == "INBOX"
        assert readonly is True
        return "OK", []

    def search(self, charset, criterion: str):
        assert criterion in {"ALL", "SINCE 01-Apr-2026"}
        return "OK", [b"1 2"]

    def fetch(self, msg_id: bytes, query: str):
        assert query == "(RFC822)"
        return "OK", [(b"RFC822", self.raw_message)]

    def logout(self) -> None:
        self.logged_out = True


def _message_bytes() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "andre@example.com"
    msg["Subject"] = "Team Update"
    msg["Date"] = "Wed, 1 Apr 2026 10:00:00 +0000"
    msg["Message-ID"] = "<msg-1@example.com>"
    msg.set_content("Standup ist um 15 Uhr.")
    return msg.as_bytes()


def test_strato_mail_registered():
    from openjarvis.connectors.strato_mail import StratoMailConnector

    ConnectorRegistry.register_value("strato_mail", StratoMailConnector)
    assert ConnectorRegistry.contains("strato_mail")


def test_strato_mail_sync_yields_documents():
    from openjarvis.connectors.strato_mail import StratoMailConnector

    fake = _FakeIMAP(_message_bytes())
    connector = StratoMailConnector(
        email_address="andre@example.com",
        password="secret",
        imap_host="imap.strato.de",
        max_messages=1,
    )

    with patch("openjarvis.connectors.strato_mail.imaplib.IMAP4_SSL") as imap_cls:
        imap_cls.return_value = fake
        docs = list(connector.sync())

    assert len(docs) == 1
    assert docs[0].source == "strato_mail"
    assert docs[0].title == "Team Update"
    assert docs[0].author == "Alice <alice@example.com>"
    assert "15 Uhr" in docs[0].content
    assert fake.logged_out is True
