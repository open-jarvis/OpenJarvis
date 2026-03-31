"""Tests for webhook fail-closed validation (Section 3)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestTwilioValidationFailClosed:
    """Twilio validation must reject when SDK is unavailable."""

    def test_missing_sdk_returns_false(self) -> None:
        pytest.importorskip("fastapi")
        from openjarvis.server.webhook_routes import _validate_twilio_signature

        with patch.dict(
            "sys.modules", {"twilio": None, "twilio.request_validator": None}
        ):
            result = _validate_twilio_signature(
                auth_token="test_token",
                url="https://example.com/webhooks/twilio",
                params={"Body": "hello"},
                signature="invalid",
            )
            assert result is False

    def test_empty_auth_token_returns_false(self) -> None:
        pytest.importorskip("fastapi")
        from openjarvis.server.webhook_routes import _validate_twilio_signature

        result = _validate_twilio_signature(
            auth_token="",
            url="https://example.com/webhooks/twilio",
            params={},
            signature="",
        )
        assert result is False
