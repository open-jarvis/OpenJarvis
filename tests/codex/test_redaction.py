from __future__ import annotations

from openjarvis.codex.redaction import (
    redact_data,
    redact_text,
    safe_error_message,
    sanitized_codex_environment,
)


def test_nested_credentials_are_redacted() -> None:
    payload = {
        "accessToken": "secret-access-token",
        "nested": {
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz123456",
            "message": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456",
        },
    }

    redacted = redact_data(payload)

    assert redacted["accessToken"] == "[REDACTED]"
    assert redacted["nested"]["api_key"] == "[REDACTED]"
    assert "abcdefghijklmnopqrstuvwxyz123456" not in redacted["nested"]["message"]


def test_error_messages_do_not_leak_credentials() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    error = RuntimeError(f"request failed with api_key={secret}")

    message = safe_error_message(error)

    assert secret not in message
    assert "[REDACTED" in message


def test_jwt_like_values_are_redacted() -> None:
    token = "eyJabcdefghijk.abcdefghijklmnop.abcdefghijklmnop"

    assert token not in redact_text(f"token={token}")


def test_codex_child_environment_removes_api_fallbacks() -> None:
    environment = {
        "PATH": "safe",
        "CODEX_HOME": "safe-home",
        "OPENAI_API_KEY": "secret",
        "CODEX_ACCESS_TOKEN": "secret",
        "SOME_REFRESH_TOKEN": "secret",
    }

    sanitized = sanitized_codex_environment(environment)

    assert sanitized == {"PATH": "safe", "CODEX_HOME": "safe-home"}
