"""Tests for AppleMailConnector — local Mail.app ``.emlx`` store connector.

All tests build a fake ``~/Library/Mail/V10`` tree in ``tmp_path``. No real
Mail.app store is required.
"""

from __future__ import annotations

import plistlib
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from openjarvis.connectors._stubs import Document
from openjarvis.core.registry import ConnectorRegistry

_ACCOUNT = "9691CB23-B31E-4A68-8D60-1308897B62EF"


def _epoch(*args: int) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


def _write_emlx(
    path: Path,
    rfc822: bytes,
    *,
    date_received: int | None = None,
    trailer: bool = True,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"{len(rfc822)}\n".encode() + rfc822
    if trailer:
        plist = {"conversation-id": 1, "flags": 0}
        if date_received is not None:
            plist["date-received"] = date_received
        body += plistlib.dumps(plist)
    path.write_bytes(body)


_MSG_ONE = (
    b"From: Vikram <vikram@astro.caltech.edu>\r\n"
    b"To: Jakob Faber <jfaber@caltech.edu>, other@example.com\r\n"
    b"Cc: admin@caltech.edu\r\n"
    b"Subject: DSA reimbursement\r\n"
    b"Message-ID: <one@caltech.edu>\r\n"
    b"Date: Tue, 01 Sep 2026 10:00:00 +0000\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Please submit the receipt for $53.22.\r\n"
)

_MSG_TWO = (
    b"From: gp@astro.caltech.edu\r\n"
    b"To: jfaber@caltech.edu\r\n"
    b"Subject: =?utf-8?q?Missing_receipts_=E2=80=94_reminder?=\r\n"
    b"Message-ID: <two@caltech.edu>\r\n"
    b"In-Reply-To: <one@caltech.edu>\r\n"
    b"Date: Wed, 02 Sep 2026 10:00:00 +0000\r\n"
    b"Content-Type: multipart/alternative; boundary=BOUND\r\n"
    b"\r\n"
    b"--BOUND\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"\r\n"
    b"<p>html only</p>\r\n"
    b"--BOUND\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"plain part wins\r\n"
    b"--BOUND--\r\n"
)

_MSG_PARTIAL = (
    b"From: noreply@example.com\r\n"
    b"To: jfaber@caltech.edu\r\n"
    b"Subject: headers only\r\n"
    b"Date: Thu, 03 Sep 2026 10:00:00 +0000\r\n"
    b"\r\n"
)


@pytest.fixture()
def mail_store(tmp_path: Path) -> Path:
    """Return the fake ``~/Library/Mail`` root with one account and two mailboxes."""
    root = tmp_path / "Mail"
    account = root / "V10" / _ACCOUNT
    billing = account / "Billing & Payments.mbox" / "F858" / "Data" / "0" / "Messages"
    inbox = account / "INBOX.mbox" / "F858" / "Data" / "Messages"

    _write_emlx(billing / "101.emlx", _MSG_ONE, date_received=_epoch(2026, 9, 1, 18, 0))
    _write_emlx(billing / "102.emlx", _MSG_TWO, date_received=_epoch(2026, 9, 2, 18, 0))
    _write_emlx(
        inbox / "103.partial.emlx",
        _MSG_PARTIAL,
        date_received=_epoch(2026, 9, 3, 18, 0),
    )
    # Non-message files that must be ignored.
    (billing.parent / "Attachments").mkdir(parents=True, exist_ok=True)
    (billing.parent / "Attachments" / "101.pdf").write_bytes(b"%PDF")
    (root / "V10" / "MailData").mkdir(parents=True)
    _write_emlx(root / "V10" / "MailData" / "999.emlx", _MSG_ONE)
    return root


@pytest.fixture()
def connector(mail_store: Path):
    from openjarvis.connectors.apple_mail import AppleMailConnector  # noqa: PLC0415

    return AppleMailConnector(mailbox_path=str(mail_store))


def test_registered() -> None:
    # conftest clears every registry between tests; re-import to re-register.
    import importlib  # noqa: PLC0415

    import openjarvis.connectors.apple_mail as apple_mail  # noqa: PLC0415

    importlib.reload(apple_mail)
    assert ConnectorRegistry.get("apple_mail") is apple_mail.AppleMailConnector


def test_not_connected_without_path() -> None:
    from openjarvis.connectors.apple_mail import AppleMailConnector  # noqa: PLC0415

    assert AppleMailConnector().is_connected() is False
    assert AppleMailConnector(mailbox_path="/nonexistent/Mail").is_connected() is False
    assert list(AppleMailConnector().sync()) == []


def test_is_connected_and_disconnect(connector) -> None:
    assert connector.is_connected() is True
    connector.disconnect()
    assert connector.is_connected() is False
    assert connector.mailbox_path == ""


def test_sync_yields_messages(connector) -> None:
    docs: List[Document] = list(connector.sync())
    assert len(docs) == 3
    assert {d.source for d in docs} == {"apple_mail"}
    assert {d.doc_type for d in docs} == {"email"}
    assert connector.sync_status().items_synced == 3
    assert connector.sync_status().items_total == 3


def test_sync_document_fields(connector) -> None:
    docs = {d.doc_id: d for d in connector.sync()}

    one = docs["apple_mail:<one@caltech.edu>"]
    assert one.title == "DSA reimbursement"
    assert one.author == "Vikram <vikram@astro.caltech.edu>"
    assert one.participants == [
        "Jakob Faber <jfaber@caltech.edu>",
        "other@example.com",
        "admin@caltech.edu",
    ]
    assert "$53.22" in one.content
    assert one.timestamp == datetime(2026, 9, 1, 18, 0, tzinfo=timezone.utc)
    assert one.metadata["account_id"] == _ACCOUNT
    assert one.metadata["mailbox"] == "Billing & Payments"
    assert one.metadata["emlx_uid"] == "101"
    assert one.metadata["partial"] is False
    assert one.channel == "Billing & Payments"
    assert one.source_id == "<one@caltech.edu>"

    two = docs["apple_mail:<two@caltech.edu>"]
    assert two.title == "Missing receipts — reminder"
    assert two.content.strip() == "plain part wins"
    assert two.thread_id == "<one@caltech.edu>"


def test_partial_message_falls_back_to_path_id(connector) -> None:
    docs = {d.doc_id: d for d in connector.sync()}
    partial = docs[f"apple_mail:{_ACCOUNT}:INBOX:103"]
    assert partial.title == "headers only"
    assert partial.content == ""
    assert partial.metadata["partial"] is True
    assert partial.metadata["mailbox"] == "INBOX"


def test_since_filter_uses_date_received(connector) -> None:
    since = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
    docs = list(connector.sync(since=since))
    assert {d.title for d in docs} == {"Missing receipts — reminder", "headers only"}

    naive = datetime(2026, 9, 3, 0, 0)
    assert [d.title for d in connector.sync(since=naive)] == ["headers only"]


def test_single_mbox_path(mail_store: Path) -> None:
    from openjarvis.connectors.apple_mail import AppleMailConnector  # noqa: PLC0415

    mbox = mail_store / "V10" / _ACCOUNT / "Billing & Payments.mbox"
    docs = list(AppleMailConnector(mailbox_path=str(mbox)).sync())
    assert len(docs) == 2
    assert {d.metadata["mailbox"] for d in docs} == {"Billing & Payments"}


def test_malformed_emlx_is_skipped(mail_store: Path) -> None:
    from openjarvis.connectors.apple_mail import AppleMailConnector  # noqa: PLC0415

    bad = mail_store / "V10" / _ACCOUNT / "INBOX.mbox" / "bad.emlx"
    bad.write_bytes(b"not-a-size\nFrom: x\r\n\r\n")
    (mail_store / "V10" / _ACCOUNT / "INBOX.mbox" / "empty.emlx").write_bytes(b"")

    docs = list(AppleMailConnector(mailbox_path=str(mail_store)).sync())
    assert len(docs) == 3


def test_date_header_fallback_without_trailer(tmp_path: Path) -> None:
    from openjarvis.connectors.apple_mail import AppleMailConnector  # noqa: PLC0415

    _write_emlx(tmp_path / "loose.emlx", _MSG_ONE, trailer=False)
    docs = list(AppleMailConnector(mailbox_path=str(tmp_path)).sync())
    assert len(docs) == 1
    assert docs[0].timestamp == datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    assert docs[0].metadata["account_id"] == ""
    assert docs[0].metadata["mailbox"] == ""
    assert docs[0].channel is None
