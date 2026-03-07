//! OpenJarvis Recipes — composable TOML configs that wire all five pillars.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// A composable recipe that configures the full OpenJarvis stack.
///
/// Mirrors the Python `Recipe` dataclass — every field beyond `name` is optional
/// so that a recipe can specify only the axes it cares about.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Recipe {
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub kind: Option<String>,

    // Intelligence
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub quantization: Option<String>,
    #[serde(default)]
    pub provider: Option<String>,

    // Engine
    #[serde(default)]
    pub engine_key: Option<String>,

    // Agent
    #[serde(default)]
    pub agent_type: Option<String>,
    #[serde(default)]
    pub max_turns: Option<usize>,
    #[serde(default)]
    pub temperature: Option<f64>,
    #[serde(default)]
    pub max_tokens: Option<usize>,
    #[serde(default)]
    pub tools: Option<Vec<String>>,
    #[serde(default)]
    pub system_prompt: Option<String>,

    // Learning / routing
    #[serde(default)]
    pub routing_policy: Option<String>,
    #[serde(default)]
    pub agent_policy: Option<String>,

    // Eval
    #[serde(default)]
    pub eval_suites: Option<Vec<String>>,
    #[serde(default)]
    pub eval_benchmarks: Option<Vec<String>>,

    // Scheduling / operator
    #[serde(default)]
    pub schedule_type: Option<String>,
    #[serde(default)]
    pub schedule_value: Option<String>,
    #[serde(default)]
    pub channels: Option<Vec<String>>,

    // Security
    #[serde(default)]
    pub required_capabilities: Option<Vec<String>>,

    /// Raw TOML table preserved for forward-compat / custom keys.
    #[serde(flatten)]
    pub raw: HashMap<String, serde_json::Value>,
}

impl Recipe {
    /// Convert the recipe into builder kwargs (non-None fields only).
    pub fn to_builder_kwargs(&self) -> HashMap<String, serde_json::Value> {
        let mut map = HashMap::new();

        map.insert("name".into(), serde_json::Value::String(self.name.clone()));

        macro_rules! insert_opt {
            ($field:ident) => {
                if let Some(ref v) = self.$field {
                    if let Ok(val) = serde_json::to_value(v) {
                        map.insert(stringify!($field).to_string(), val);
                    }
                }
            };
        }

        insert_opt!(description);
        insert_opt!(version);
        insert_opt!(kind);
        insert_opt!(model);
        insert_opt!(quantization);
        insert_opt!(provider);
        insert_opt!(engine_key);
        insert_opt!(agent_type);
        insert_opt!(max_turns);
        insert_opt!(temperature);
        insert_opt!(max_tokens);
        insert_opt!(tools);
        insert_opt!(system_prompt);
        insert_opt!(routing_policy);
        insert_opt!(agent_policy);
        insert_opt!(eval_suites);
        insert_opt!(eval_benchmarks);
        insert_opt!(schedule_type);
        insert_opt!(schedule_value);
        insert_opt!(channels);
        insert_opt!(required_capabilities);

        for (k, v) in &self.raw {
            map.entry(k.clone()).or_insert_with(|| v.clone());
        }

        map
    }
}

/// Parse a TOML string into a `Recipe`.
pub fn load_recipe(toml_str: &str) -> Result<Recipe, String> {
    toml::from_str(toml_str).map_err(|e| format!("Failed to parse recipe TOML: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const RECIPE_TOML: &str = r#"
name = "coding_assistant"
description = "A coding-focused assistant"
version = "1.0.0"
kind = "assistant"
model = "qwen3:8b"
engine_key = "ollama"
agent_type = "native_react"
max_turns = 10
temperature = 0.7
tools = ["calculator", "code_interpreter", "file_read"]
routing_policy = "heuristic"
"#;

    #[test]
    fn test_load_recipe() {
        let recipe = load_recipe(RECIPE_TOML).expect("should parse");
        assert_eq!(recipe.name, "coding_assistant");
        assert_eq!(recipe.model.as_deref(), Some("qwen3:8b"));
        assert_eq!(recipe.engine_key.as_deref(), Some("ollama"));
        assert_eq!(recipe.agent_type.as_deref(), Some("native_react"));
        assert_eq!(recipe.max_turns, Some(10));
        assert_eq!(recipe.tools.as_ref().map(|t| t.len()), Some(3));
    }

    #[test]
    fn test_to_builder_kwargs() {
        let recipe = load_recipe(RECIPE_TOML).unwrap();
        let kwargs = recipe.to_builder_kwargs();
        assert_eq!(kwargs["name"], serde_json::Value::String("coding_assistant".into()));
        assert_eq!(kwargs["temperature"], serde_json::json!(0.7));
        assert!(kwargs.contains_key("tools"));
        assert!(!kwargs.contains_key("schedule_type"));
    }

    #[test]
    fn test_minimal_recipe() {
        let toml_str = r#"name = "bare""#;
        let recipe = load_recipe(toml_str).expect("minimal recipe should parse");
        assert_eq!(recipe.name, "bare");
        assert!(recipe.model.is_none());
        assert!(recipe.tools.is_none());
        let kwargs = recipe.to_builder_kwargs();
        assert_eq!(kwargs.len(), 1);
    }

    #[test]
    fn test_recipe_with_extra_keys() {
        let toml_str = r#"
name = "extended"
custom_field = "hello"
"#;
        let recipe = load_recipe(toml_str).unwrap();
        assert_eq!(recipe.raw.get("custom_field").unwrap(), &serde_json::json!("hello"));
    }
}
