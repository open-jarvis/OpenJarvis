//! Rate limiter — token bucket algorithm for per-agent/per-tool throttling.

use parking_lot::Mutex;
use std::collections::HashMap;
use std::time::Instant;

#[derive(Debug, Clone)]
pub struct RateLimitConfig {
    pub requests_per_minute: u32,
    pub burst_size: u32,
    pub enabled: bool,
}

impl Default for RateLimitConfig {
    fn default() -> Self {
        Self {
            requests_per_minute: 60,
            burst_size: 10,
            enabled: true,
        }
    }
}

struct TokenBucket {
    rate: f64,
    capacity: f64,
    tokens: f64,
    last_refill: Instant,
}

impl TokenBucket {
    fn new(rate: f64, capacity: u32) -> Self {
        Self {
            rate,
            capacity: capacity as f64,
            tokens: capacity as f64,
            last_refill: Instant::now(),
        }
    }

    fn consume(&mut self, tokens: u32) -> (bool, f64) {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_refill).as_secs_f64();
        self.tokens = (self.tokens + elapsed * self.rate).min(self.capacity);
        self.last_refill = now;

        let needed = tokens as f64;
        if self.tokens >= needed {
            self.tokens -= needed;
            (true, 0.0)
        } else {
            let wait = (needed - self.tokens) / self.rate;
            (false, wait)
        }
    }
}

/// Rate limiter with per-key token buckets.
pub struct RateLimiter {
    config: RateLimitConfig,
    buckets: Mutex<HashMap<String, TokenBucket>>,
}

impl RateLimiter {
    pub fn new(config: RateLimitConfig) -> Self {
        Self {
            config,
            buckets: Mutex::new(HashMap::new()),
        }
    }

    /// Check if request is allowed. Returns `(allowed, wait_seconds)`.
    pub fn check(&self, key: &str) -> (bool, f64) {
        if !self.config.enabled {
            return (true, 0.0);
        }

        let mut buckets = self.buckets.lock();
        let bucket = buckets.entry(key.to_string()).or_insert_with(|| {
            let rate = self.config.requests_per_minute as f64 / 60.0;
            TokenBucket::new(rate, self.config.burst_size)
        });
        bucket.consume(1)
    }

    pub fn reset(&self, key: Option<&str>) {
        let mut buckets = self.buckets.lock();
        if let Some(k) = key {
            buckets.remove(k);
        } else {
            buckets.clear();
        }
    }
}

impl Default for RateLimiter {
    fn default() -> Self {
        Self::new(RateLimitConfig::default())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rate_limiter_allows_within_burst() {
        let limiter = RateLimiter::new(RateLimitConfig {
            requests_per_minute: 60,
            burst_size: 5,
            enabled: true,
        });
        for _ in 0..5 {
            let (allowed, _) = limiter.check("test");
            assert!(allowed);
        }
    }

    #[test]
    fn test_rate_limiter_blocks_over_burst() {
        let limiter = RateLimiter::new(RateLimitConfig {
            requests_per_minute: 60,
            burst_size: 2,
            enabled: true,
        });
        let (a1, _) = limiter.check("test");
        let (a2, _) = limiter.check("test");
        let (a3, wait) = limiter.check("test");
        assert!(a1);
        assert!(a2);
        assert!(!a3);
        assert!(wait > 0.0);
    }

    #[test]
    fn test_disabled_limiter() {
        let limiter = RateLimiter::new(RateLimitConfig {
            requests_per_minute: 1,
            burst_size: 1,
            enabled: false,
        });
        for _ in 0..100 {
            let (allowed, _) = limiter.check("test");
            assert!(allowed);
        }
    }
}
