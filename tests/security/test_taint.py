"""Tests for taint tracking system (Phase 14.5)."""

from __future__ import annotations

import pytest

from friday_ai.security.taint import (
    SINK_POLICY,
    TaintLabel,
    TaintSet,
    auto_detect_taint,
    check_taint,
    declassify,
    propagate_taint,
)


class TestTaintSet:
    def test_empty_taint(self):
        ts = TaintSet()
        assert not ts
        assert not ts.labels

    def test_from_labels(self):
        ts = TaintSet.from_labels(TaintLabel.PII, TaintLabel.SECRET)
        assert ts.has(TaintLabel.PII)
        assert ts.has(TaintLabel.SECRET)
        assert not ts.has(TaintLabel.EXTERNAL)

    def test_union(self):
        a = TaintSet.from_labels(TaintLabel.PII)
        b = TaintSet.from_labels(TaintLabel.SECRET)
        merged = a.union(b)
        assert merged.has(TaintLabel.PII)
        assert merged.has(TaintLabel.SECRET)

    def test_frozen(self):
        ts = TaintSet.from_labels(TaintLabel.PII)
        # TaintSet is frozen dataclass
        with pytest.raises(AttributeError):
            ts.labels = frozenset()

    def test_bool_true_when_has_labels(self):
        ts = TaintSet.from_labels(TaintLabel.PII)
        assert bool(ts)

    def test_bool_false_when_empty(self):
        ts = TaintSet()
        assert not bool(ts)


class TestCheckTaint:
    def test_clean_data_passes(self):
        ts = TaintSet()
        assert check_taint("web_search", ts) is None

    def test_pii_blocked_for_web_search(self):
        ts = TaintSet.from_labels(TaintLabel.PII)
        result = check_taint("web_search", ts)
        assert result is not None
        assert "pii" in result.lower()

    def test_secret_blocked_for_web_search(self):
        ts = TaintSet.from_labels(TaintLabel.SECRET)
        result = check_taint("web_search", ts)
        assert result is not None
        assert "secret" in result.lower()

    def test_secret_blocked_for_channel_send(self):
        ts = TaintSet.from_labels(TaintLabel.SECRET)
        result = check_taint("channel_send", ts)
        assert result is not None

    def test_external_allowed_for_web_search(self):
        ts = TaintSet.from_labels(TaintLabel.EXTERNAL)
        assert check_taint("web_search", ts) is None

    def test_unknown_tool_allowed(self):
        ts = TaintSet.from_labels(TaintLabel.PII, TaintLabel.SECRET)
        assert check_taint("calculator", ts) is None

    def test_sink_policy_has_expected_tools(self):
        assert "web_search" in SINK_POLICY
        assert "channel_send" in SINK_POLICY
        assert "code_interpreter" in SINK_POLICY


class TestDeclassify:
    def test_remove_label(self):
        ts = TaintSet.from_labels(TaintLabel.PII, TaintLabel.SECRET)
        result = declassify(ts, TaintLabel.PII, "User consent given")
        assert not result.has(TaintLabel.PII)
        assert result.has(TaintLabel.SECRET)

    def test_remove_nonexistent_label(self):
        ts = TaintSet.from_labels(TaintLabel.PII)
        result = declassify(ts, TaintLabel.SECRET, "Not present")
        assert result.has(TaintLabel.PII)


class TestAutoDetect:
    def test_detect_email(self):
        ts = auto_detect_taint("Contact: user@example.com")
        assert ts.has(TaintLabel.PII)

    def test_detect_ssn(self):
        ts = auto_detect_taint("SSN: 123-45-6789")
        assert ts.has(TaintLabel.PII)

    def test_detect_api_key(self):
        ts = auto_detect_taint("Key: sk-abc123def456ghi789jkl012mno")
        assert ts.has(TaintLabel.SECRET)

    def test_detect_github_token(self):
        ts = auto_detect_taint("Token: ghp_abcdefghijklmnopqrstuvwxyz0123456789")
        assert ts.has(TaintLabel.SECRET)

    def test_clean_text(self):
        ts = auto_detect_taint("Hello, this is a normal message.")
        assert not ts

    def test_detect_private_key(self):
        ts = auto_detect_taint("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        assert ts.has(TaintLabel.SECRET)


class TestPropagate:
    def test_propagate_input_taint(self):
        input_taint = TaintSet.from_labels(TaintLabel.EXTERNAL)
        result = propagate_taint(input_taint, "Normal output")
        assert result.has(TaintLabel.EXTERNAL)

    def test_propagate_detects_new_taint(self):
        input_taint = TaintSet()
        result = propagate_taint(input_taint, "Found: user@example.com")
        assert result.has(TaintLabel.PII)

    def test_propagate_merges(self):
        input_taint = TaintSet.from_labels(TaintLabel.EXTERNAL)
        result = propagate_taint(input_taint, "Key: sk-abc123def456ghi789jkl012mno")
        assert result.has(TaintLabel.EXTERNAL)
        assert result.has(TaintLabel.SECRET)
