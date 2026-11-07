//! Taint tracking — information flow control.

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum TaintLabel {
    Pii,
    Secret,
    UserPrivate,
    External,
}

impl std::fmt::Display for TaintLabel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TaintLabel::Pii => write!(f, "pii"),
            TaintLabel::Secret => write!(f, "secret"),
            TaintLabel::UserPrivate => write!(f, "user_private"),
            TaintLabel::External => write!(f, "external"),
        }
    }
}

/// Immutable set of taint labels attached to data.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct TaintSet {
    labels: HashSet<TaintLabel>,
}

impl TaintSet {
    pub fn new() -> Self {
        Self {
            labels: HashSet::new(),
        }
    }

    pub fn from_labels(labels: &[TaintLabel]) -> Self {
        Self {
            labels: labels.iter().copied().collect(),
        }
    }

    pub fn union(&self, other: &TaintSet) -> TaintSet {
        TaintSet {
            labels: self.labels.union(&other.labels).copied().collect(),
        }
    }

    pub fn has(&self, label: TaintLabel) -> bool {
        self.labels.contains(&label)
    }

    pub fn is_empty(&self) -> bool {
        self.labels.is_empty()
    }

    pub fn labels(&self) -> &HashSet<TaintLabel> {
        &self.labels
    }

    pub fn remove(&self, label: TaintLabel) -> TaintSet {
        let mut new_labels = self.labels.clone();
        new_labels.remove(&label);
        TaintSet { labels: new_labels }
    }
}

/// Sink policy: which taint labels are forbidden for each tool.
static SINK_POLICY: Lazy<HashMap<&'static str, HashSet<TaintLabel>>> = Lazy::new(|| {
    let mut m = HashMap::new();
    m.insert(
        "web_search",
        HashSet::from([TaintLabel::Pii, TaintLabel::Secret]),
    );
    m.insert("channel_send", HashSet::from([TaintLabel::Secret]));
    m.insert("code_interpreter", HashSet::from([TaintLabel::Secret]));
    m
});

static PII_PATTERNS: Lazy<Vec<Regex>> = Lazy::new(|| {
    vec![
        Regex::new(r"\b\d{3}-\d{2}-\d{4}\b").unwrap(),
        Regex::new(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b").unwrap(),
        Regex::new(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b").unwrap(),
        Regex::new(r"\b\+?1?\s*\(?[2-9]\d{2}\)?\s*[-.\s]?\d{3}\s*[-.\s]?\d{4}\b").unwrap(),
    ]
});

static SECRET_PATTERNS: Lazy<Vec<Regex>> = Lazy::new(|| {
    vec![
        Regex::new(r"(?:sk|pk|api)[_-][a-zA-Z0-9]{20,}").unwrap(),
        Regex::new(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}").unwrap(),
        Regex::new(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----").unwrap(),
        Regex::new(r"(?i)(?:bearer|token|password|secret|key)\s*[=:]\s*\S{8,}").unwrap(),
    ]
});

/// Check if taint labels violate the sink policy for a tool.
/// Returns a violation description, or None if clean.
pub fn check_taint(tool_name: &str, taint: &TaintSet) -> Option<String> {
    let forbidden = SINK_POLICY.get(tool_name)?;
    let violations: Vec<_> = taint
        .labels
        .intersection(forbidden)
        .collect();
    if violations.is_empty() {
        return None;
    }
    let mut sorted: Vec<_> = violations.iter().map(|v| v.to_string()).collect();
    sorted.sort();
    Some(format!(
        "Data with labels [{}] cannot be sent to '{}'.",
        sorted.join(", "),
        tool_name
    ))
}

/// Auto-detect taint labels in text content.
pub fn auto_detect_taint(text: &str) -> TaintSet {
    let mut labels = HashSet::new();

    for pat in PII_PATTERNS.iter() {
        if pat.is_match(text) {
            labels.insert(TaintLabel::Pii);
            break;
        }
    }

    for pat in SECRET_PATTERNS.iter() {
        if pat.is_match(text) {
            labels.insert(TaintLabel::Secret);
            break;
        }
    }

    TaintSet { labels }
}

/// Propagate taint: union of input taint with auto-detected output taint.
pub fn propagate_taint(input_taint: &TaintSet, output_text: &str) -> TaintSet {
    let output_taint = auto_detect_taint(output_text);
    input_taint.union(&output_taint)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_taint_set_operations() {
        let t1 = TaintSet::from_labels(&[TaintLabel::Pii]);
        let t2 = TaintSet::from_labels(&[TaintLabel::Secret]);
        let merged = t1.union(&t2);
        assert!(merged.has(TaintLabel::Pii));
        assert!(merged.has(TaintLabel::Secret));
    }

    #[test]
    fn test_check_taint_violation() {
        let taint = TaintSet::from_labels(&[TaintLabel::Pii, TaintLabel::Secret]);
        let result = check_taint("web_search", &taint);
        assert!(result.is_some());
    }

    #[test]
    fn test_check_taint_clean() {
        let taint = TaintSet::from_labels(&[TaintLabel::External]);
        let result = check_taint("web_search", &taint);
        assert!(result.is_none());
    }

    #[test]
    fn test_auto_detect_pii() {
        let taint = auto_detect_taint("SSN: 123-45-6789");
        assert!(taint.has(TaintLabel::Pii));
    }

    #[test]
    fn test_auto_detect_secret() {
        let taint = auto_detect_taint("key: sk-abcdefghijklmnopqrstuvwxyz");
        assert!(taint.has(TaintLabel::Secret));
    }

    #[test]
    fn test_propagate() {
        let input = TaintSet::from_labels(&[TaintLabel::External]);
        let result = propagate_taint(&input, "SSN: 123-45-6789");
        assert!(result.has(TaintLabel::External));
        assert!(result.has(TaintLabel::Pii));
    }
}
