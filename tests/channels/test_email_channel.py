"""Tests for the EmailChannel adapter."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.channels.email_channel import EmailChannel
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry
from tests.channels.channel_test_helpers import make_common_channel_tests


@pytest.fixture(autouse=True)
def _register_email():
    """Re-register after any registry clear."""
    if not ChannelRegistry.contains("email"):
        ChannelRegistry.register_value("email", EmailChannel)


TestCommonChannel = make_common_channel_tests(
    EmailChannel,
    "email",
    constructor_kwargs={
        "smtp_host": "smtp.example.com",
        "username": "user@example.com",
    },
)


class TestInit:
    def test_defaults(self):
        ch = EmailChannel()
        assert ch._smtp_host == ""
        assert ch._smtp_port == 587
        assert ch._imap_host == ""
        assert ch._imap_port == 993
        assert ch._username == ""
        assert ch._password == ""
        assert ch._use_tls is True
        assert ch._status == ChannelStatus.DISCONNECTED

    def test_constructor_params(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            smtp_port=465,
            imap_host="imap.example.com",
            imap_port=143,
            username="user@example.com",
            password="pass123",
            use_tls=False,
        )
        assert ch._smtp_host == "smtp.example.com"
        assert ch._smtp_port == 465
        assert ch._imap_host == "imap.example.com"
        assert ch._imap_port == 143
        assert ch._username == "user@example.com"
        assert ch._password == "pass123"
        assert ch._use_tls is False

    def test_env_var_fallback(self):
        with patch.dict(
            os.environ,
            {
                "EMAIL_USERNAME": "env@example.com",
                "EMAIL_PASSWORD": "env-pass",
            },
        ):
            ch = EmailChannel()
            assert ch._username == "env@example.com"
            assert ch._password == "env-pass"

    def test_constructor_overrides_env(self):
        with patch.dict(os.environ, {"EMAIL_USERNAME": "env@example.com"}):
            ch = EmailChannel(username="explicit@example.com")
            assert ch._username == "explicit@example.com"


class TestSend:
    def test_send_success_tls(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass123",
        )

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_smtp) as mock_cls:
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            result = ch.send("recipient@example.com", "Hello!")
            assert result is True
            mock_cls.assert_called_once_with("smtp.example.com", 587)
            mock_smtp.starttls.assert_called_once()
            mock_smtp.login.assert_called_once_with("user@example.com", "pass123")
            mock_smtp.send_message.assert_called_once()

    def test_send_success_no_tls(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass123",
            use_tls=False,
        )

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            result = ch.send("recipient@example.com", "Hello!")
            assert result is True
            mock_smtp.starttls.assert_not_called()

    def test_send_no_config(self):
        ch = EmailChannel()
        result = ch.send("recipient@example.com", "Hello!")
        assert result is False

    def test_send_exception(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass123",
        )

        with patch("smtplib.SMTP", side_effect=ConnectionError("refused")):
            result = ch.send("recipient@example.com", "Hello!")
            assert result is False

    def test_send_publishes_event(self):
        bus = EventBus(record_history=True)
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass123",
            bus=bus,
        )

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            ch.send("recipient@example.com", "Hello!")

        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types

    def test_send_with_subject_metadata(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            username="user@example.com",
            password="pass123",
        )

        mock_smtp = MagicMock()
        with patch("smtplib.SMTP", return_value=mock_smtp):
            mock_smtp.__enter__ = MagicMock(return_value=mock_smtp)
            mock_smtp.__exit__ = MagicMock(return_value=False)
            result = ch.send(
                "recipient@example.com",
                "Hello!",
                metadata={"subject": "Custom Subject"},
            )
            assert result is True
            sent_msg = mock_smtp.send_message.call_args[0][0]
            assert sent_msg["Subject"] == "Custom Subject"


class TestStatus:
    def test_no_config_connect_error(self):
        ch = EmailChannel()
        ch.connect()
        assert ch.status() == ChannelStatus.ERROR


class TestConnect:
    def test_connect_smtp_only(self):
        ch = EmailChannel(
            smtp_host="smtp.example.com",
            username="user@example.com",
        )
        ch.connect()
        assert ch.status() == ChannelStatus.CONNECTED
        # No IMAP, so no listener thread
        assert ch._listener_thread is None
