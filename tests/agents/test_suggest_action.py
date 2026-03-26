"""Tests for suggest_action helper."""

from openjarvis.agents.errors import FatalError, RetryableError, suggest_action


def test_suggest_action_rate_limit():
    err = RetryableError("rate limit exceeded")
    assert "auto-retry" in suggest_action(err).lower()


def test_suggest_action_timeout():
    err = RetryableError("connection timed out")
    assert "engine" in suggest_action(err).lower()


def test_suggest_action_auth():
    err = FatalError("401 unauthorized")
    assert "API key" in suggest_action(err)


def test_suggest_action_not_found():
    err = FatalError("model not found (404)")
    action = suggest_action(err).lower()
    assert "model name" in action or "endpoint" in action


def test_suggest_action_unknown():
    err = RetryableError("something weird happened")
    assert "trace" in suggest_action(err).lower()
