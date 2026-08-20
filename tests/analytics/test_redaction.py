"""Tests for openjarvis.analytics.redaction.

Two layers of guarantee are tested here:
  - Value-level: ``redact()`` drops string values that match any PII
    pattern, exceed ``MAX_STR_LEN``, or carry composite types.
  - Structural: ``validate_event()`` from the catalog drops unknown
    events and properties whose values fail the per-spec validator.

Together they form fail-closed PII protection. Adding a new event or
property anywhere in the analytics module should require touching
this file as well.
"""

from __future__ import annotations

import pytest

from openjarvis.analytics.events import (
    REGISTRY,
    known_event_names,
    validate_event,
)
from openjarvis.analytics.redaction import (
    MAX_STR_LEN,
    hash_id,
    looks_like_pii,
    redact,
)

# ---------------------------------------------------------------------------
# Value-level PII detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        # Emails
        "user@example.com",
        "first.last+filter@subdomain.example.co.uk",
        "leak hidden in user@example.com sentence",
        # IPv4
        "127.0.0.1",
        "192.168.1.42",
        "trace from 10.0.0.5 here",
        # IPv6 (loose pattern)
        "fe80::1ff:fe23:4567:890a",
        # MAC
        "00:1A:2B:3C:4D:5E",
        "AA:BB:CC:DD:EE:FF",
        # Home paths
        "/Users/alice/Documents/secret.txt",
        "/home/bob/.ssh/id_rsa",
        "~/Library/Application Support",
        "$HOME/secrets",
        # File URLs
        "file:///etc/passwd",
        # API keys
        "sk-abcdefghijklmnop123456",
        "sk-proj-AbCdEfGhIjKlMnOpQrStUv",
        "xoxb-1234567890-abcdefghij-1234567890abcdef",
        "ghp_1234567890abcdefghij1234567890abcd",
        "gho_1234567890abcdefghij1234567890abcd",
        "AKIAIOSFODNN7EXAMPLE",
        "AIzaSyD-1234567890abcdefghij1234567890",
        "ya29.a0AfH6SMBabc123def456ghi789jkl",
        # JWT
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        # Bearer tokens
        "Bearer abc123def456",
        "bearer xyz789",
        # Password / secret assignments
        "password=hunter2",
        "API_KEY: super-secret-value",
        "token=abc123",
        # .local hostnames
        "alice-macbook.local",
    ],
)
def test_pii_patterns_are_detected(value: str) -> None:
    assert looks_like_pii(value), f"expected to flag: {value!r}"


@pytest.mark.parametrize(
    "value",
    [
        "darwin",
        "arm64",
        "0.1.1",
        "qwen3.5:2b",  # model name with colon — must not look like IPv6
        "ok",
        "chat",
        "v1.2.3",
        "8754b77c7eee26e4",  # a hashed id
        "true",
    ],
)
def test_safe_values_pass(value: str) -> None:
    assert not looks_like_pii(value), f"false positive: {value!r}"


# ---------------------------------------------------------------------------
# redact() — full property dict cleaning
# ---------------------------------------------------------------------------


def test_redact_keeps_safe_values() -> None:
    cleaned = redact(
        {
            "os": "darwin",
            "arch": "arm64",
            "count": 42,
            "ratio": 0.5,
            "enabled": True,
        }
    )
    assert cleaned == {
        "os": "darwin",
        "arch": "arm64",
        "count": 42,
        "ratio": 0.5,
        "enabled": True,
    }


def test_redact_drops_pii_strings() -> None:
    _jwt = (
        "eyJhbGciOiJIUzI1NiJ9"
        ".eyJzdWIiOiIxMjM0In0"
        ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    )
    cleaned = redact(
        {
            "ok": "chat",
            "leak_email": "user@example.com",
            "leak_path": "/Users/alice/file.txt",
            "leak_key": "sk-1234567890abcdef",
            "leak_jwt": _jwt,
            "leak_bearer": "Bearer abc123",
        }
    )
    assert cleaned == {"ok": "chat"}


def test_redact_drops_long_strings() -> None:
    huge = "x" * (MAX_STR_LEN + 1)
    cleaned = redact({"safe": "short", "huge": huge})
    assert cleaned == {"safe": "short"}


def test_redact_drops_empty_strings() -> None:
    # Empty strings carry no signal — drop them to keep the wire clean.
    cleaned = redact({"empty": "", "real": "value"})
    assert cleaned == {"real": "value"}


def test_redact_drops_composite_types() -> None:
    # Lists, dicts, sets, and tuples bypass redaction entirely. Sending
    # them would let PII smuggle through inside containers.
    cleaned = redact(
        {
            "good": 1,
            "list": ["a", "b"],
            "dict": {"k": "v"},
            "set": {"x", "y"},
            "tuple": ("p", "q"),
        }
    )
    assert cleaned == {"good": 1}


def test_redact_preserves_numeric_zero_and_false() -> None:
    # Falsy non-string values must survive — they're meaningful counts.
    cleaned = redact({"a": 0, "b": False, "c": 0.0})
    assert cleaned == {"a": 0, "b": False, "c": 0.0}


def test_redact_returns_new_dict_does_not_mutate_input() -> None:
    src = {"safe": "ok", "leak": "user@example.com"}
    out = redact(src)
    assert "leak" in src  # original unchanged
    assert "leak" not in out


# ---------------------------------------------------------------------------
# hash_id() — for cohorting without leaking identifiers
# ---------------------------------------------------------------------------


def test_hash_id_is_16_lowercase_hex() -> None:
    h = hash_id("llama3.1:8b")
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_hash_id_is_deterministic() -> None:
    a = hash_id("some-model-name")
    b = hash_id("some-model-name")
    assert a == b


def test_hash_id_differs_for_different_inputs() -> None:
    assert hash_id("model-a") != hash_id("model-b")


def test_hash_id_empty_string_returns_empty() -> None:
    assert hash_id("") == ""


# ---------------------------------------------------------------------------
# Structural validation — events.py catalog
# ---------------------------------------------------------------------------


def test_unknown_event_is_rejected() -> None:
    assert validate_event("not_a_real_event", {"any": "thing"}) is None


def test_known_event_with_no_properties_is_accepted() -> None:
    # Empty result is still a valid event — we'd still record it.
    assert validate_event("first_chat_sent", {}) == {}


def test_unknown_properties_are_silently_dropped() -> None:
    cleaned = validate_event(
        "install_started",
        {
            "os": "darwin",
            "arch": "arm64",
            "installer_version": "0.1.1",
            "malicious_extra": "should-not-survive",
        },
    )
    assert cleaned == {
        "os": "darwin",
        "arch": "arm64",
        "installer_version": "0.1.1",
    }


def test_invalid_enum_value_is_dropped() -> None:
    # 'os' must be in the allowlist; a path-like value fails.
    cleaned = validate_event(
        "install_started",
        {"os": "/Users/alice", "arch": "arm64"},
    )
    assert cleaned == {"arch": "arm64"}


def test_invalid_int_property_is_dropped() -> None:
    cleaned = validate_event(
        "install_stage_completed",
        {"stage": "uv", "elapsed_ms": -5},  # negative ms fails _is_int_nonneg
    )
    assert cleaned == {"stage": "uv"}


def test_bool_is_not_int_for_int_validators() -> None:
    # Critical: bool is a subclass of int in Python; the catalog
    # validators must reject booleans where ints are expected
    # (otherwise True would count as elapsed_ms=1).
    cleaned = validate_event(
        "install_stage_completed",
        {"stage": "uv", "elapsed_ms": True},
    )
    assert "elapsed_ms" not in cleaned


def test_chat_session_ended_properties_pass() -> None:
    cleaned = validate_event(
        "chat_session_ended",
        {
            "turn_count": 5,
            "tokens_in": 1000,
            "tokens_out": 500,
            "latency_ms_p50": 250.0,
            "latency_ms_p95": 800.0,
            "tool_count": 3,
            "unique_tools": 2,
            "unique_models": 1,
            "error_count": 0,
            "model_hash": "8754b77c7eee26e4",
            "engine": "ollama",
            "duration_ms": 60000,
        },
    )
    assert cleaned["turn_count"] == 5
    assert cleaned["model_hash"] == "8754b77c7eee26e4"
    assert cleaned["engine"] == "ollama"


def test_chat_session_ended_rejects_bad_hash() -> None:
    cleaned = validate_event(
        "chat_session_ended",
        {
            "turn_count": 1,
            "model_hash": "not-a-hash-too-short",  # not 16 hex chars
        },
    )
    assert "turn_count" in cleaned
    assert "model_hash" not in cleaned


# ---------------------------------------------------------------------------
# Catalog sanity
# ---------------------------------------------------------------------------


def test_catalog_has_expected_lifecycle_events() -> None:
    names = set(known_event_names())
    must_exist = {
        "install_started",
        "install_stage_completed",
        "install_completed",
        "install_failed",
        "uninstall_started",
        "app_opened",
        "setup_completed",
        "first_chat_sent",
        "chat_session_ended",
        "tool_first_used",
        "model_changed",
        "feature_used",
        "error_shown_to_user",
        "feedback_submitted",
        "usage_daily_summary",
    }
    missing = must_exist - names
    assert not missing, f"catalog is missing required events: {sorted(missing)}"


def test_every_event_has_at_least_one_property_or_is_marker() -> None:
    # Either the spec has properties, OR it's intentionally a marker
    # event with no payload (e.g. first_chat_sent). We just assert
    # that no property dict is malformed.
    for name, spec in REGISTRY.items():
        assert isinstance(spec.properties, dict), f"{name}: properties must be dict"
        for prop, validator in spec.properties.items():
            assert callable(validator), f"{name}.{prop}: validator must be callable"
