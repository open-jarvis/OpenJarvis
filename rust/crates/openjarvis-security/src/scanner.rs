//! Concrete security scanners — secrets and PII detection.

use crate::types::{ScanFinding, ScanResult, ThreatLevel};
use once_cell::sync::Lazy;
use regex::Regex;

struct PatternDef {
    name: &'static str,
    regex: Regex,
    threat: ThreatLevel,
    description: &'static str,
    /// Optional post-filter for matches the regex engine cannot express (no look-around).
    check: Option<fn(&str, usize, usize) -> bool>,
}

/// True when `text[start..end]` is a real dotted-quad: every octet <= 255 and the match is not
/// part of a longer dotted number (e.g. "2.432.902.008.176.640.000" or a version like "1.2.3.4.5").
fn is_standalone_ipv4(text: &str, start: usize, end: usize) -> bool {
    let m = &text[start..end];
    if m.split('.')
        .any(|o| o.parse::<u16>().map_or(true, |n| n > 255))
    {
        return false;
    }
    let b = text.as_bytes();
    let joined_before = start >= 2 && b[start - 1] == b'.' && b[start - 2].is_ascii_digit();
    let joined_after = end + 1 < b.len() && b[end] == b'.' && b[end + 1].is_ascii_digit();
    !(joined_before || joined_after)
}

macro_rules! pattern {
    ($name:expr, $pat:expr, $threat:expr, $desc:expr) => {
        PatternDef {
            name: $name,
            regex: Regex::new($pat).unwrap(),
            threat: $threat,
            description: $desc,
            check: None,
        }
    };
    ($name:expr, $pat:expr, $threat:expr, $desc:expr, $check:expr) => {
        PatternDef {
            name: $name,
            regex: Regex::new($pat).unwrap(),
            threat: $threat,
            description: $desc,
            check: Some($check),
        }
    };
}

static SECRET_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        pattern!(
            "openai_key",
            r"sk-[A-Za-z0-9_-]{20,}",
            ThreatLevel::Critical,
            "OpenAI API key"
        ),
        pattern!(
            "anthropic_key",
            r"sk-ant-[A-Za-z0-9_-]{20,}",
            ThreatLevel::Critical,
            "Anthropic API key"
        ),
        pattern!(
            "aws_access_key",
            r"AKIA[0-9A-Z]{16}",
            ThreatLevel::Critical,
            "AWS access key"
        ),
        pattern!(
            "github_token",
            r"(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{36,}",
            ThreatLevel::Critical,
            "GitHub token"
        ),
        pattern!(
            "password_assignment",
            r#"(?:password|passwd|pwd)\s*[=:]\s*['"]([^'"]{4,})['"]"#,
            ThreatLevel::High,
            "Password assignment"
        ),
        pattern!(
            "db_connection_string",
            r"(?:postgres|mysql|mongodb|redis)://[^\s]{10,}",
            ThreatLevel::High,
            "Database connection string"
        ),
        pattern!(
            "private_key",
            r"-----BEGIN (?:RSA )?PRIVATE KEY-----",
            ThreatLevel::Critical,
            "Private key"
        ),
        pattern!(
            "slack_token",
            r"xox[bpors]-[A-Za-z0-9\-]{10,}",
            ThreatLevel::High,
            "Slack token"
        ),
        pattern!(
            "stripe_key",
            r"(?:sk|pk)_(?:test|live)_[A-Za-z0-9]{20,}",
            ThreatLevel::Critical,
            "Stripe key"
        ),
        pattern!(
            "generic_api_key",
            r#"(?:api_key|secret_key|auth_token)\s*[=:]\s*['"]([^'"]{8,})['"]"#,
            ThreatLevel::High,
            "Generic API key/secret"
        ),
    ]
});

static PII_PATTERNS: Lazy<Vec<PatternDef>> = Lazy::new(|| {
    vec![
        pattern!(
            "email",
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            ThreatLevel::Medium,
            "Email address"
        ),
        pattern!(
            "us_ssn",
            r"\b\d{3}-\d{2}-\d{4}\b",
            ThreatLevel::Critical,
            "US Social Security Number"
        ),
        pattern!(
            "credit_card_visa",
            r"\b4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            ThreatLevel::Critical,
            "Visa credit card"
        ),
        pattern!(
            "credit_card_mastercard",
            r"\b5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            ThreatLevel::Critical,
            "Mastercard credit card"
        ),
        pattern!(
            "credit_card_amex",
            r"\b3[47]\d{2}[\s-]?\d{6}[\s-]?\d{5}\b",
            ThreatLevel::Critical,
            "Amex credit card"
        ),
        pattern!(
            "us_phone",
            r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
            ThreatLevel::Medium,
            "US phone number"
        ),
        pattern!(
            "ipv4_address",
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            ThreatLevel::Low,
            "IPv4 address",
            is_standalone_ipv4
        ),
    ]
});

fn scan_with_patterns(text: &str, patterns: &[PatternDef]) -> ScanResult {
    let mut findings = Vec::new();
    for p in patterns {
        for m in p.regex.find_iter(text) {
            if let Some(check) = p.check {
                if !check(text, m.start(), m.end()) {
                    continue;
                }
            }
            findings.push(ScanFinding {
                pattern_name: p.name.to_string(),
                matched_text: m.as_str().to_string(),
                threat_level: p.threat,
                start: m.start(),
                end: m.end(),
                description: p.description.to_string(),
            });
        }
    }
    ScanResult { findings }
}

fn redact_with_patterns(text: &str, patterns: &[PatternDef]) -> String {
    let mut result = text.to_string();
    for p in patterns {
        let marker = format!("[REDACTED:{}]", p.name);
        let mut out = String::with_capacity(result.len());
        let mut last = 0;
        for m in p.regex.find_iter(&result) {
            if let Some(check) = p.check {
                if !check(&result, m.start(), m.end()) {
                    continue;
                }
            }
            out.push_str(&result[last..m.start()]);
            out.push_str(&marker);
            last = m.end();
        }
        out.push_str(&result[last..]);
        result = out;
    }
    result
}

/// Detect API keys, tokens, passwords, and other secrets.
pub struct SecretScanner;

impl SecretScanner {
    pub fn new() -> Self {
        Self
    }

    pub fn scan(&self, text: &str) -> ScanResult {
        scan_with_patterns(text, &SECRET_PATTERNS)
    }

    pub fn redact(&self, text: &str) -> String {
        redact_with_patterns(text, &SECRET_PATTERNS)
    }
}

impl Default for SecretScanner {
    fn default() -> Self {
        Self::new()
    }
}

/// Detect personally identifiable information.
pub struct PIIScanner;

impl PIIScanner {
    pub fn new() -> Self {
        Self
    }

    pub fn scan(&self, text: &str) -> ScanResult {
        scan_with_patterns(text, &PII_PATTERNS)
    }

    pub fn redact(&self, text: &str) -> String {
        redact_with_patterns(text, &PII_PATTERNS)
    }
}

impl Default for PIIScanner {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_secret_scanner_openai_key() {
        let scanner = SecretScanner::new();
        let text = "My key is sk-abcdefghijklmnopqrstuvwxyz1234";
        let result = scanner.scan(text);
        assert!(!result.clean());
        assert_eq!(result.findings[0].pattern_name, "openai_key");
    }

    #[test]
    fn test_secret_scanner_redact() {
        let scanner = SecretScanner::new();
        let text = "key: sk-abcdefghijklmnopqrstuvwxyz1234";
        let redacted = scanner.redact(text);
        assert!(redacted.contains("[REDACTED:openai_key]"));
        assert!(!redacted.contains("sk-"));
    }

    #[test]
    fn test_pii_scanner_email() {
        let scanner = PIIScanner::new();
        let result = scanner.scan("Contact user@example.com for info");
        assert!(!result.clean());
        assert_eq!(result.findings[0].pattern_name, "email");
    }

    #[test]
    fn test_pii_scanner_ssn() {
        let scanner = PIIScanner::new();
        let result = scanner.scan("SSN: 123-45-6789");
        assert!(!result.clean());
        assert_eq!(result.findings[0].pattern_name, "us_ssn");
        assert_eq!(result.highest_threat(), Some(ThreatLevel::Critical));
    }

    #[test]
    fn test_ipv4_real_and_false_positives() {
        let scanner = PIIScanner::new();
        assert!(!scanner.scan("server 200.10.20.30 ok").clean());
        assert!(scanner
            .scan("factorial of 21 is 51.090.942.171.709.440.000")
            .clean());
        assert!(scanner.scan("version 1.2.3.4.5").clean());
        assert!(scanner.scan("999.1.1.1").clean());
        assert_eq!(
            scanner.redact("a 2.432.902.008.176.640.000 b 8.8.8.8"),
            "a 2.432.902.008.176.640.000 b [REDACTED:ipv4_address]"
        );
    }

    #[test]
    fn test_clean_text() {
        let scanner = SecretScanner::new();
        let result = scanner.scan("Hello, this is safe text.");
        assert!(result.clean());
    }
}
