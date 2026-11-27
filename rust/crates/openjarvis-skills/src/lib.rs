//! OpenJarvis Skills — skill manifests, execution results, and signature verification.

use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

fn decode_hex(s: &str) -> Result<Vec<u8>, String> {
    if !s.len().is_multiple_of(2) {
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
    #[serde(default)]
    pub tool_name: String,
    #[serde(default)]
    pub skill_name: String,
    #[serde(default = "default_arguments_template")]
    pub arguments_template: String,
    #[serde(default)]
    pub output_key: String,
}

fn default_arguments_template() -> String {
    "{}".into()
}

/// Full skill manifest loaded from TOML (signature excluded from verification payload).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillManifest {
    pub name: String,
    #[serde(default = "default_version")]
    pub version: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub author: String,
    #[serde(default)]
    pub steps: Vec<SkillStep>,
    #[serde(default)]
    pub required_capabilities: Vec<String>,
    #[serde(default)]
    pub signature: String,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub depends: Vec<String>,
    #[serde(default = "default_true")]
    pub user_invocable: bool,
    #[serde(default)]
    pub disable_model_invocation: bool,
    #[serde(default)]
    pub markdown_content: String,
}

fn default_version() -> String {
    "0.1.0".into()
}

fn default_true() -> bool {
    true
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

#[derive(Debug, Deserialize)]
struct SectionedSkillFile {
    skill: Option<SkillSection>,
}

#[derive(Debug, Deserialize, Default)]
struct SkillSection {
    name: Option<String>,
    version: Option<String>,
    description: Option<String>,
    author: Option<String>,
    #[serde(default)]
    steps: Vec<SkillStep>,
    #[serde(default)]
    required_capabilities: Vec<String>,
    #[serde(default)]
    signature: Option<String>,
    #[serde(default)]
    metadata: Option<HashMap<String, serde_json::Value>>,
    #[serde(default)]
    tags: Option<Vec<String>>,
    #[serde(default)]
    depends: Option<Vec<String>>,
    #[serde(default)]
    user_invocable: Option<bool>,
    #[serde(default)]
    disable_model_invocation: Option<bool>,
    #[serde(default)]
    markdown_content: Option<String>,
}

/// Parse a TOML string into a `SkillManifest`.
/// Supports both sectioned TOML (`[skill]`) and flat TOML.
pub fn load_skill(toml_str: &str) -> Result<SkillManifest, String> {
    if let Ok(sec) = toml::from_str::<SectionedSkillFile>(toml_str) {
        if let Some(s) = sec.skill {
            let name = s.name.ok_or_else(|| "missing field `name` in [skill]".to_string())?;
            return Ok(SkillManifest {
                name,
                version: s.version.unwrap_or_else(default_version),
                description: s.description.unwrap_or_default(),
                author: s.author.unwrap_or_default(),
                steps: s.steps,
                required_capabilities: s.required_capabilities,
                signature: s.signature.unwrap_or_default(),
                metadata: s.metadata.unwrap_or_default(),
                tags: s.tags.unwrap_or_default(),
                depends: s.depends.unwrap_or_default(),
                user_invocable: s.user_invocable.unwrap_or(true),
                disable_model_invocation: s.disable_model_invocation.unwrap_or(false),
                markdown_content: s.markdown_content.unwrap_or_default(),
            });
        }
    }

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
name = "web_search_and_summarize"
version = "0.1.0"
description = "Searches the web and produces a summary"
author = "openjarvis"
required_capabilities = ["network:http"]

[[steps]]
tool_name = "web_search"
arguments_template = '{"query": "{query}"}'
output_key = "results"

[[steps]]
tool_name = "summarizer"
arguments_template = '{"text": "{results}"}'
output_key = "summary"
"#;

    const SHIPPED_DAILY_DIGEST: &str =
        include_str!("../../../../src/openjarvis/skills/data/daily-digest.toml");

    #[test]
    fn test_load_skill() {
        let manifest = load_skill(SKILL_TOML).expect("should parse");
        assert_eq!(manifest.name, "web_search_and_summarize");
        assert_eq!(manifest.steps.len(), 2);
        assert_eq!(manifest.steps[0].tool_name, "web_search");
        assert_eq!(manifest.required_capabilities, vec!["network:http"]);
    }

    #[test]
    fn test_load_shipped_sectioned_skill() {
        let manifest = load_skill(SHIPPED_DAILY_DIGEST).expect("should parse shipped daily-digest skill");
        assert_eq!(manifest.name, "daily-digest");
        assert_eq!(manifest.version, "0.1.0");
        assert_eq!(manifest.author, "openjarvis");
        assert_eq!(manifest.steps.len(), 3);
        assert_eq!(manifest.steps[0].tool_name, "memory_search");
        assert_eq!(manifest.steps[0].output_key, "recent_items");
        assert_eq!(manifest.steps[1].tool_name, "think");
    }

    #[test]
    fn test_manifest_bytes_deterministic() {
        let m1 = load_skill(SKILL_TOML).unwrap();
        let m2 = load_skill(SKILL_TOML).unwrap();
        assert_eq!(m1.manifest_bytes(), m2.manifest_bytes());
    }

    #[test]
    fn test_serde_roundtrip() {
        let manifest = load_skill(SKILL_TOML).unwrap();
        let json = serde_json::to_string(&manifest).unwrap();
        let back: SkillManifest = serde_json::from_str(&json).unwrap();
        assert_eq!(back.name, manifest.name);
        assert_eq!(back.steps.len(), manifest.steps.len());
    }
}
