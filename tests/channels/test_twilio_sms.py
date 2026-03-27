"""Tests for Twilio SMS channel."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.channels._stubs import ChannelStatus
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.registry import ChannelRegistry


@pytest.fixture(autouse=True)
def _register_twilio():
    if not ChannelRegistry.contains("twilio"):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        ChannelRegistry.register_value("twilio", TwilioSMSChannel)


class TestRegistration:
    def test_registered(self):
        assert ChannelRegistry.contains("twilio")


class TestInit:
    def test_from_params(self):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        ch = TwilioSMSChannel(
            account_sid="AC_test",
            auth_token="token_test",
            phone_number="+15551234567",
        )
        assert ch.channel_id == "twilio"
        assert ch.status() == ChannelStatus.DISCONNECTED

    def test_from_env_vars(self, monkeypatch):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_env")
        monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token_env")
        monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15559876543")
        ch = TwilioSMSChannel()
        assert ch._account_sid == "AC_env"


class TestSend:
    def test_send_success(self):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        ch = TwilioSMSChannel(
            account_sid="AC_test",
            auth_token="token_test",
            phone_number="+15551234567",
        )
        ch.connect()

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(sid="SM_test")
        ch._client = mock_client

        result = ch.send("+15559999999", "Hello via SMS!")
        assert result is True
        mock_client.messages.create.assert_called_once_with(
            body="Hello via SMS!",
            from_="+15551234567",
            to="+15559999999",
        )

    def test_send_failure(self):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        ch = TwilioSMSChannel(
            account_sid="AC_test",
            auth_token="token_test",
            phone_number="+15551234567",
        )
        ch.connect()

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        ch._client = mock_client

        result = ch.send("+15559999999", "Hello!")
        assert result is False

    def test_send_publishes_event(self):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        bus = EventBus(record_history=True)
        ch = TwilioSMSChannel(
            account_sid="AC_test",
            auth_token="token_test",
            phone_number="+15551234567",
            bus=bus,
        )
        ch.connect()

        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(sid="SM_test")
        ch._client = mock_client

        ch.send("+15559999999", "Hello!")
        event_types = [e.event_type for e in bus.history]
        assert EventType.CHANNEL_MESSAGE_SENT in event_types


class TestStatus:
    def test_connected_after_connect(self):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        ch = TwilioSMSChannel(
            account_sid="AC_test",
            auth_token="token_test",
            phone_number="+15551234567",
        )
        with patch("openjarvis.channels.twilio_sms._create_twilio_client"):
            ch.connect()
        assert ch.status() == ChannelStatus.CONNECTED

    def test_disconnected_after_disconnect(self):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        ch = TwilioSMSChannel(
            account_sid="AC_test",
            auth_token="token_test",
            phone_number="+15551234567",
        )
        with patch("openjarvis.channels.twilio_sms._create_twilio_client"):
            ch.connect()
            ch.disconnect()
        assert ch.status() == ChannelStatus.DISCONNECTED


class TestOnMessage:
    def test_registers_handler(self):
        from openjarvis.channels.twilio_sms import (
            TwilioSMSChannel,
        )

        ch = TwilioSMSChannel(
            account_sid="AC_test",
            auth_token="token_test",
            phone_number="+15551234567",
        )
        handler = MagicMock()
        ch.on_message(handler)
        assert handler in ch._handlers
