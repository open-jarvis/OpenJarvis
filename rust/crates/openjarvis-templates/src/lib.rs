//! OpenJarvis Templates — pre-configured agent templates loaded from TOML.

use serde::{Deserialize, Serialize};

/// A pre-configured agent template with system prompt, tool set, and behavioural parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentTemplate {
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub system_prompt: String,
    #[serde(default = "default_agent_type")]
    pub agent_type: String,
    #[serde(default)]
    pub tools: Vec<String>,
    #[serde(default = "default_max_turns")]
    pub max_turns: usize,
    #[serde(default = "default_temperature")]
    pub temperature: f64,
}

fn default_agent_type() -> String {
    "simple".into()
}

fn default_max_turns() -> usize {
    10
}

fn default_temperature() -> f64 {
    0.7
}

#[derive(Debug, Deserialize)]
struct SectionedTemplate {
    template: Option<TemplateSection>,
    agent: Option<AgentSection>,
}

#[derive(Debug, Deserialize)]
struct TemplateSection {
    name: Option<String>,
    #[serde(default)]
    description: Option<String>,
}

#[derive(Debug, Deserialize)]
struct AgentSection {
    #[serde(rename = "type")]
    agent_type: Option<String>,
    #[serde(default)]
    max_turns: Option<usize>,
    #[serde(default)]
    temperature: Option<f64>,
    #[serde(default)]
    tools: Option<Vec<String>>,
    #[serde(default)]
    system_prompt: Option<String>,
}

/// Parse a TOML string into an `AgentTemplate`.
/// Supports both sectioned TOML (`[template]` + `[agent]`) and flat TOML.
pub fn load_template(toml_str: &str) -> Result<AgentTemplate, String> {
    if let Ok(sec) = toml::from_str::<SectionedTemplate>(toml_str) {
        if sec.template.is_some() || sec.agent.is_some() {
            let template_sec = sec.template.unwrap_or(TemplateSection {
                name: None,
                description: None,
            });
            let agent_sec = sec.agent.unwrap_or(AgentSection {
                agent_type: None,
                max_turns: None,
                temperature: None,
                tools: None,
                system_prompt: None,
            });

            let name = template_sec
                .name
                .ok_or_else(|| "missing field `name` in [template]".to_string())?;

            return Ok(AgentTemplate {
                name,
                description: template_sec.description.unwrap_or_default(),
                system_prompt: agent_sec.system_prompt.unwrap_or_default(),
                agent_type: agent_sec.agent_type.unwrap_or_else(default_agent_type),
                tools: agent_sec.tools.unwrap_or_default(),
                max_turns: agent_sec.max_turns.unwrap_or_else(default_max_turns),
                temperature: agent_sec.temperature.unwrap_or_else(default_temperature),
            });
        }
    }

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

    const SHIPPED_CODE_REVIEWER: &str =
        include_str!("../../../../src/openjarvis/templates/data/code-reviewer.toml");

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
    fn test_load_shipped_sectioned_template() {
        let tpl = load_template(SHIPPED_CODE_REVIEWER).expect("should parse shipped sectioned file");
        assert_eq!(tpl.name, "code-reviewer");
        assert_eq!(tpl.agent_type, "native_react");
        assert_eq!(tpl.max_turns, 8);
        assert!((tpl.temperature - 0.3).abs() < f64::EPSILON);
        assert_eq!(tpl.tools, vec!["file_read", "think"]);
        assert!(tpl.system_prompt.starts_with("You are an expert code reviewer."));
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
