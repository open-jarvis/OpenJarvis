"""Tests for rate limiter -- token bucket algorithm."""

from __future__ import annotations

import time

from friday_ai.security.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    TokenBucket,
)


class TestTokenBucket:
    """Tests for the TokenBucket class."""

    def test_initial_capacity(self) -> None:
        """New bucket allows burst_size requests."""
        bucket = TokenBucket(rate=1.0, capacity=5)
        for _ in range(5):
            allowed, wait = bucket.consume()
            assert allowed is True
            assert wait == 0.0

    def test_consume_reduces_tokens(self) -> None:
        """After consume, available decreases."""
        bucket = TokenBucket(rate=1.0, capacity=10)
        initial = bucket.available
        bucket.consume(3)
        assert bucket.available < initial

    def test_refill_over_time(self) -> None:
        """After waiting, tokens refill."""
        bucket = TokenBucket(rate=10.0, capacity=5)
        # Drain all tokens
        for _ in range(5):
            bucket.consume()
        assert bucket.available < 1.0
        # Wait for refill
        time.sleep(0.15)
        assert bucket.available >= 1.0

    def test_exceeds_capacity(self) -> None:
        """Consuming more than available returns (False, wait_time)."""
        bucket = TokenBucket(rate=1.0, capacity=3)
        # Drain all tokens
        for _ in range(3):
            bucket.consume()
        allowed, wait = bucket.consume()
        assert allowed is False
        assert wait > 0.0

    def test_burst(self) -> None:
        """Can consume burst_size tokens immediately."""
        capacity = 8
        bucket = TokenBucket(rate=1.0, capacity=capacity)
        allowed, wait = bucket.consume(capacity)
        assert allowed is True
        assert wait == 0.0


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    def test_disabled(self) -> None:
        """When enabled=False, always allows."""
        config = RateLimitConfig(enabled=False, burst_size=1, requests_per_minute=1)
        limiter = RateLimiter(config)
        for _ in range(100):
            allowed, wait = limiter.check("any_key")
            assert allowed is True
            assert wait == 0.0

    def test_allows_within_limit(self) -> None:
        """Requests within RPM are allowed."""
        config = RateLimitConfig(requests_per_minute=600, burst_size=10)
        limiter = RateLimiter(config)
        for _ in range(10):
            allowed, _ = limiter.check("agent_a")
            assert allowed is True

    def test_blocks_over_limit(self) -> None:
        """Rapid requests beyond burst are blocked."""
        config = RateLimitConfig(requests_per_minute=60, burst_size=3)
        limiter = RateLimiter(config)
        # Exhaust burst
        for _ in range(3):
            allowed, _ = limiter.check("agent_b")
            assert allowed is True
        # Next should be blocked
        allowed, wait = limiter.check("agent_b")
        assert allowed is False
        assert wait > 0.0

    def test_separate_keys(self) -> None:
        """Different keys have independent limits."""
        config = RateLimitConfig(requests_per_minute=60, burst_size=2)
        limiter = RateLimiter(config)
        # Exhaust key1
        limiter.check("key1")
        limiter.check("key1")
        allowed_key1, _ = limiter.check("key1")
        assert allowed_key1 is False
        # key2 should still work
        allowed_key2, _ = limiter.check("key2")
        assert allowed_key2 is True

    def test_reset_key(self) -> None:
        """Reset clears specific key."""
        config = RateLimitConfig(requests_per_minute=60, burst_size=2)
        limiter = RateLimiter(config)
        limiter.check("key1")
        limiter.check("key1")
        allowed, _ = limiter.check("key1")
        assert allowed is False
        # Reset key1
        limiter.reset("key1")
        allowed, _ = limiter.check("key1")
        assert allowed is True

    def test_reset_all(self) -> None:
        """Reset without key clears everything."""
        config = RateLimitConfig(requests_per_minute=60, burst_size=1)
        limiter = RateLimiter(config)
        limiter.check("key1")
        limiter.check("key2")
        # Both exhausted
        assert limiter.check("key1")[0] is False
        assert limiter.check("key2")[0] is False
        # Reset all
        limiter.reset()
        assert limiter.check("key1")[0] is True
        assert limiter.check("key2")[0] is True

    def test_default_config(self) -> None:
        """Default values are reasonable."""
        limiter = RateLimiter()
        assert limiter.config.requests_per_minute == 60
        assert limiter.config.burst_size == 10
        assert limiter.config.enabled is True
