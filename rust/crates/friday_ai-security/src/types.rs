//! Security data types — threat levels, scan findings, security events.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, PartialOrd, Ord)]
#[serde(rename_all = "lowercase")]
pub enum ThreatLevel {
    Low,
    Medium,
    High,
    Critical,
}

impl std::fmt::Display for ThreatLevel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ThreatLevel::Low => write!(f, "low"),
            ThreatLevel::Medium => write!(f, "medium"),
            ThreatLevel::High => write!(f, "high"),
            ThreatLevel::Critical => write!(f, "critical"),
        }
    }
}

impl std::str::FromStr for ThreatLevel {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "low" => Ok(ThreatLevel::Low),
            "medium" => Ok(ThreatLevel::Medium),
            "high" => Ok(ThreatLevel::High),
            "critical" => Ok(ThreatLevel::Critical),
            _ => Err(format!("Unknown threat level: {s}")),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RedactionMode {
    Warn,
    Redact,
    Block,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SecurityEventType {
    SecretDetected,
    PiiDetected,
    SensitiveFileBlocked,
    ToolBlocked,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScanFinding {
    pub pattern_name: String,
    pub matched_text: String,
    pub threat_level: ThreatLevel,
    pub start: usize,
    pub end: usize,
    #[serde(default)]
    pub description: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ScanResult {
    pub findings: Vec<ScanFinding>,
}

impl ScanResult {
    pub fn clean(&self) -> bool {
        self.findings.is_empty()
    }

    pub fn highest_threat(&self) -> Option<ThreatLevel> {
        self.findings
            .iter()
            .map(|f| f.threat_level)
            .max()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecurityEvent {
    pub event_type: SecurityEventType,
    pub timestamp: f64,
    #[serde(default)]
    pub findings: Vec<ScanFinding>,
    #[serde(default)]
    pub content_preview: String,
    #[serde(default)]
    pub action_taken: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_threat_level_ordering() {
        assert!(ThreatLevel::Low < ThreatLevel::Critical);
        assert!(ThreatLevel::Medium < ThreatLevel::High);
    }

    #[test]
    fn test_scan_result_clean() {
        let result = ScanResult::default();
        assert!(result.clean());
    }

    #[test]
    fn test_scan_result_with_findings() {
        let result = ScanResult {
            findings: vec![ScanFinding {
                pattern_name: "test".into(),
                matched_text: "secret".into(),
                threat_level: ThreatLevel::High,
                start: 0,
                end: 6,
                description: "test finding".into(),
            }],
        };
        assert!(!result.clean());
        assert_eq!(result.highest_threat(), Some(ThreatLevel::High));
    }
}
