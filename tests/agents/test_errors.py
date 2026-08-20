"""Tests for agent error classification."""

from __future__ import annotations


class TestErrorClassification:
    def test_retryable_error(self):
        from openjarvis.agents.errors import RetryableError

        err = RetryableError("rate limit hit")
        assert err.retryable is True
        assert str(err) == "rate limit hit"

    def test_fatal_error(self):
        from openjarvis.agents.errors import FatalError

        err = FatalError("invalid API key")
        assert err.retryable is False

    def test_escalate_error(self):
        from openjarvis.agents.errors import EscalateError

        err = EscalateError("agent uncertain about next step")
        assert err.retryable is False
        assert err.needs_human is True

    def test_classify_rate_limit(self):
        from openjarvis.agents.errors import classify_error

        result = classify_error(Exception("rate limit exceeded"))
        assert result.retryable is True

    def test_classify_timeout(self):
        from openjarvis.agents.errors import classify_error

        result = classify_error(TimeoutError("connection timed out"))
        assert result.retryable is True

    def test_classify_permission(self):
        from openjarvis.agents.errors import classify_error

        result = classify_error(PermissionError("access denied"))
        assert result.retryable is False

    def test_classify_unknown_defaults_retryable(self):
        from openjarvis.agents.errors import classify_error

        result = classify_error(ValueError("something weird"))
        assert result.retryable is True

    def test_retry_delay_exponential(self):
        from openjarvis.agents.errors import retry_delay

        assert retry_delay(0) == 10
        assert retry_delay(1) == 20
        assert retry_delay(2) == 40
        # Capped at 300 seconds
        assert retry_delay(10) == 300

    def test_classify_context_length_is_fatal(self):
        # A context-window overflow is deterministic — retrying the identical
        # over-length request can never succeed, so it must NOT be classified
        # retryable (which would burn ~30s of backoff on guaranteed failures).
        from openjarvis.agents.errors import classify_error
        from openjarvis.engine._base import EngineContextLengthError

        typed = classify_error(
            EngineContextLengthError(
                "The conversation is too long for the model's context window."
            )
        )
        assert typed.retryable is False

        # Same for untyped errors whose message reads like a context overflow
        # (e.g. raw vendor errors from engines without the typed mapping).
        untyped = classify_error(
            Exception("This model's maximum context length is 4096 tokens.")
        )
        assert untyped.retryable is False

    def test_suggest_action_context_length(self):
        from openjarvis.agents.errors import FatalError, suggest_action

        action = suggest_action(FatalError("prompt exceeds the model's context window"))
        assert "context window" in action or "too long" in action.lower()
