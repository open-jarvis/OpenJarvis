//! OpenJarvis Templates — pre-configured agent templates loaded from TOML.

use serde::{Deserialize, Serialize};

/// A pre-configured agent template with system prompt, tool set, and behavioural parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTemplate {
    pub name: String,
    pub description: String,
    pub system_prompt: String,
    pub agent_type: String,
    #[serde(default)]
    pub tools: Vec<String>,
    #[serde(default = "default_max_turns")]
    pub max_turns: usize,
    #[serde(default = "default_temperature")]
    pub temperature: f64,
}

fn default_max_turns() -> usize {
    10
}

fn default_temperature() -> f64 {
    0.7
}

/// Parse a TOML string into an `AgentTemplate`.
pub fn load_template(toml_str: &str) -> Result<AgentTemplate, String> {
    toml::from_str(toml_str).map_err(|e| format!("Failed to parse template TOML: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEMPLATE_TOML: &str = r#"
name = "code-reviewer"
description = "Reviews code for quality, bugs, and style"
system_prompt = "You are a senior code reviewer. Analyze code for bugs, style issues, and improvements."
agent_type = "native_react"
tools = ["file_read", "code_interpreter"]
max_turns = 5
temperature = 0.3
"#;

    #[test]
    fn test_load_template() {
        let tpl = load_template(TEMPLATE_TOML).expect("should parse");
        assert_eq!(tpl.name, "code-reviewer");
        assert_eq!(tpl.agent_type, "native_react");
        assert_eq!(tpl.tools.len(), 2);
        assert_eq!(tpl.max_turns, 5);
        assert!((tpl.temperature - 0.3).abs() < f64::EPSILON);
    }

    #[test]
    fn test_defaults() {
        let toml_str = r#"
name = "minimal"
description = "A minimal template"
system_prompt = "You are a helpful assistant."
agent_type = "simple"
"#;
        let tpl = load_template(toml_str).expect("should parse");
        assert_eq!(tpl.max_turns, 10);
        assert!((tpl.temperature - 0.7).abs() < f64::EPSILON);
        assert!(tpl.tools.is_empty());
    }

    #[test]
    fn test_serde_roundtrip() {
        let tpl = load_template(TEMPLATE_TOML).unwrap();
        let json = serde_json::to_string(&tpl).unwrap();
        let back: AgentTemplate = serde_json::from_str(&json).unwrap();
        assert_eq!(back.name, tpl.name);
        assert_eq!(back.tools, tpl.tools);
    }
}
