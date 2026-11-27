//! Loop guard — detect and prevent agent loops.

use sha2::{Digest, Sha256};
use std::collections::{HashMap, VecDeque};

pub struct LoopGuard {
    call_counts: HashMap<String, usize>,
    recent_calls: VecDeque<String>,
    per_tool_counts: HashMap<String, usize>,
    poll_budget: usize,
    max_identical: usize,
    max_ping_pong: usize,
}

impl LoopGuard {
    pub fn new(max_identical: usize, max_ping_pong: usize, poll_budget: usize) -> Self {
        Self {
            call_counts: HashMap::new(),
            recent_calls: VecDeque::new(),
            per_tool_counts: HashMap::new(),
            poll_budget,
            max_identical,
            max_ping_pong,
        }
    }

    /// Check a tool call for loop patterns. Returns an error message if a loop is detected.
    pub fn check(&mut self, tool_name: &str, arguments: &str) -> Option<String> {
        let hash = self.hash_call(tool_name, arguments);

        // Check identical calls
        let count = self.call_counts.entry(hash).or_insert(0);
        *count += 1;
        if *count > self.max_identical {
            return Some(format!(
                "Loop detected: identical call to '{tool_name}' repeated {count} times (max {})",
                self.max_identical
            ));
        }

        // Check per-tool budget (polling tools)
        let tool_count = self.per_tool_counts.entry(tool_name.to_string()).or_insert(0);
        *tool_count += 1;
        if *tool_count > self.poll_budget {
            return Some(format!(
                "Tool '{tool_name}' exceeded poll budget ({})",
                self.poll_budget
            ));
        }

        // Check ping-pong pattern (A-B-A-B or A-B-C-A-B-C)
        self.recent_calls.push_back(tool_name.to_string());
        let min_len = (self.max_ping_pong * 2).max(4);
        if self.recent_calls.len() > min_len * 2 {
            self.recent_calls.pop_front();
        }

        if self.recent_calls.len() >= min_len {
            let len = self.recent_calls.len();
            let calls: Vec<&String> = self.recent_calls.iter().collect();
            // Period 2 (A-B-A-B)
            if len >= 4
                && calls[len - 1] == calls[len - 3]
                && calls[len - 2] == calls[len - 4]
                && calls[len - 1] != calls[len - 2]
            {
                return Some(format!(
                    "Ping-pong loop detected between '{}' and '{}'",
                    calls[len - 1],
                    calls[len - 2]
                ));
            }
            // Period 3 (A-B-C-A-B-C)
            if len >= 6
                && calls[len - 1] == calls[len - 4]
                && calls[len - 2] == calls[len - 5]
                && calls[len - 3] == calls[len - 6]
                && (calls[len - 1] != calls[len - 2] || calls[len - 2] != calls[len - 3])
            {
                return Some(format!(
                    "Cyclic loop detected between '{}', '{}', and '{}'",
                    calls[len - 3],
                    calls[len - 2],
                    calls[len - 1]
                ));
            }
        }

        None
    }

    pub fn reset(&mut self) {
        self.call_counts.clear();
        self.recent_calls.clear();
        self.per_tool_counts.clear();
    }

    fn hash_call(&self, tool_name: &str, arguments: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(tool_name.as_bytes());
        hasher.update(b":");
        hasher.update(arguments.as_bytes());
        let digest = hasher.finalize();
        let mut encoded = String::with_capacity(digest.len() * 2);
        const HEX: &[u8; 16] = b"0123456789abcdef";
        for byte in digest.iter().copied() {
            encoded.push(HEX[(byte >> 4) as usize] as char);
            encoded.push(HEX[(byte & 0x0f) as usize] as char);
        }
        encoded
    }
}

impl Default for LoopGuard {
    fn default() -> Self {
        Self::new(50, 4, 100)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_identical_call_detection() {
        let mut guard = LoopGuard::new(2, 4, 100);
        assert!(guard.check("calc", r#"{"expr":"2+2"}"#).is_none());
        assert!(guard.check("calc", r#"{"expr":"2+2"}"#).is_none());
        let result = guard.check("calc", r#"{"expr":"2+2"}"#);
        assert!(result.is_some());
        assert!(result
            .unwrap()
            .contains("identical call to 'calc' repeated 3 times (max 2)"));
    }

    #[test]
    fn test_different_calls_ok() {
        let mut guard = LoopGuard::default();
        assert!(guard.check("calc", r#"{"expr":"2+2"}"#).is_none());
        assert!(guard.check("calc", r#"{"expr":"3+3"}"#).is_none());
    }

    #[test]
    fn test_ping_pong_detection() {
        let mut guard = LoopGuard::new(100, 2, 100);
        assert!(guard.check("tool_a", "1").is_none());
        assert!(guard.check("tool_b", "2").is_none());
        assert!(guard.check("tool_a", "3").is_none());
        let result = guard.check("tool_b", "4");
        assert!(result.is_some());
        assert!(result.unwrap().contains("Ping-pong"));
    }

    #[test]
    fn test_poll_budget_per_tool() {
        let mut guard = LoopGuard::new(1000, 100, 2);
        assert!(guard.check("tool_a", "1").is_none());
        assert!(guard.check("tool_b", "1").is_none());
        assert!(guard.check("tool_a", "2").is_none());
        assert!(guard.check("tool_b", "2").is_none());
        let result_a = guard.check("tool_a", "3");
        assert!(result_a.is_some());
        assert!(result_a.unwrap().contains("Tool 'tool_a' exceeded poll budget (2)"));
        assert!(guard.check("tool_c", "1").is_none());
    }
}
