//! OpenJarvis Skills — skill manifests, execution results, and signature verification.

use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

fn decode_hex(s: &str) -> Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err("odd-length hex string".into());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| e.to_string()))
        .collect()
}

/// A single step within a skill: invoke a tool with templated arguments.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillStep {
    pub tool_name: String,
    pub arguments_template: String,
    pub output_key: String,
}

/// Full skill manifest loaded from TOML (signature excluded from verification payload).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillManifest {
    pub name: String,
    pub version: String,
    pub description: String,
    pub author: String,
    pub steps: Vec<SkillStep>,
    pub required_capabilities: Vec<String>,
    #[serde(default)]
    pub signature: String,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

impl SkillManifest {
    /// Canonical bytes for signature verification — everything except `signature`.
    pub fn manifest_bytes(&self) -> Vec<u8> {
        let mut parts: Vec<String> = Vec::with_capacity(8);
        parts.push(self.name.clone());
        parts.push(self.version.clone());
        parts.push(self.description.clone());
        parts.push(self.author.clone());
        for step in &self.steps {
            parts.push(format!(
                "{}:{}:{}",
                step.tool_name, step.arguments_template, step.output_key
            ));
        }
        for cap in &self.required_capabilities {
            parts.push(cap.clone());
        }
        if let Ok(meta) = serde_json::to_string(&self.metadata) {
            parts.push(meta);
        }
        parts.join("|").into_bytes()
    }
}

/// Result of executing a skill.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillResult {
    pub name: String,
    pub success: bool,
    pub outputs: Vec<String>,
    pub duration_seconds: f64,
}

/// Parse a TOML string into a `SkillManifest`.
pub fn load_skill(toml_str: &str) -> Result<SkillManifest, String> {
    toml::from_str(toml_str).map_err(|e| format!("Failed to parse skill TOML: {e}"))
}

/// Verify the Ed25519 signature on a manifest against the given public key bytes.
pub fn verify_signature(manifest: &SkillManifest, public_key_bytes: &[u8]) -> bool {
    let key_bytes: [u8; 32] = match public_key_bytes.try_into() {
        Ok(b) => b,
        Err(_) => return false,
    };
    let verifying_key = match VerifyingKey::from_bytes(&key_bytes) {
        Ok(k) => k,
        Err(_) => return false,
    };
    let sig_bytes = match decode_hex(&manifest.signature) {
        Ok(b) => b,
        Err(_) => return false,
    };
    let sig_array: [u8; 64] = match sig_bytes.try_into() {
        Ok(a) => a,
        Err(_) => return false,
    };
    let signature = Signature::from_bytes(&sig_array);
    let payload = manifest.manifest_bytes();
    verifying_key.verify_strict(&payload, &signature).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    const SKILL_TOML: &str = r#"
name = "file-organizer"
version = "1.0.0"
description = "Organizes files by extension"
author = "openjarvis"
signature = ""
required_capabilities = ["file_read", "file_write"]

[[steps]]
tool_name = "file_read"
arguments_template = '{"path": "{{input_dir}}"}'
output_key = "listing"

[[steps]]
tool_name = "file_write"
arguments_template = '{"dest": "{{output_dir}}/{{ext}}"}'
output_key = "result"
"#;

    #[test]
    fn test_load_skill() {
        let manifest = load_skill(SKILL_TOML).expect("should parse");
        assert_eq!(manifest.name, "file-organizer");
        assert_eq!(manifest.version, "1.0.0");
        assert_eq!(manifest.steps.len(), 2);
        assert_eq!(manifest.required_capabilities.len(), 2);
        assert_eq!(manifest.steps[0].tool_name, "file_read");
        assert_eq!(manifest.steps[1].output_key, "result");
    }

    #[test]
    fn test_manifest_bytes_deterministic() {
        let m = load_skill(SKILL_TOML).unwrap();
        let b1 = m.manifest_bytes();
        let b2 = m.manifest_bytes();
        assert_eq!(b1, b2);
        assert!(!b1.is_empty());
    }

    #[test]
    fn test_verify_signature_bad_key() {
        let m = load_skill(SKILL_TOML).unwrap();
        assert!(!verify_signature(&m, &[0u8; 32]));
    }

    #[test]
    fn test_skill_result_serde() {
        let result = SkillResult {
            name: "test".into(),
            success: true,
            outputs: vec!["a".into(), "b".into()],
            duration_seconds: 1.5,
        };
        let json = serde_json::to_string(&result).unwrap();
        let back: SkillResult = serde_json::from_str(&json).unwrap();
        assert_eq!(back.name, "test");
        assert!(back.success);
        assert_eq!(back.outputs.len(), 2);
    }
}
