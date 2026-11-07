//! Search space builder and default search space for configuration optimization.
//!
//! Rust translation of `src/friday_ai/learning/optimize/search_space.py`.

use std::collections::HashMap;

use super::types::{DimensionType, SearchDimension, SearchSpace};

/// Build a [`SearchSpace`] from a config map (typically parsed from TOML).
///
/// Expected structure:
/// ```json
/// {
///   "optimize": {
///     "search": [
///       { "name": "agent.type", "type": "categorical",
///         "values": ["orchestrator", "native_react"],
///         "description": "Agent architecture" },
///       { "name": "intelligence.temperature", "type": "continuous",
///         "low": 0.0, "high": 1.0,
///         "description": "Generation temperature" }
///     ],
///     "fixed": { "engine": "ollama", "model": "qwen3:8b" },
///     "constraints": { "rules": ["SimpleAgent should only have max_turns = 1"] }
///   }
/// }
/// ```
pub fn build_search_space(config: &serde_json::Value) -> SearchSpace {
    let opt = config
        .get("optimize")
        .cloned()
        .unwrap_or(serde_json::Value::Object(Default::default()));

    // Parse search entries
    let search_entries = opt
        .get("search")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();

    // Parse fixed params
    let fixed: HashMap<String, serde_json::Value> = opt
        .get("fixed")
        .and_then(|v| serde_json::from_value(v.clone()).ok())
        .unwrap_or_default();

    // Parse constraints
    let constraints: Vec<String> = opt
        .get("constraints")
        .and_then(|v| v.get("rules"))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();

    // Build dimensions
    let dimensions: Vec<SearchDimension> = search_entries
        .iter()
        .map(|entry| {
            let name = entry
                .get("name")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            // Infer primitive from the first segment of the dotted name
            let primitive = if name.contains('.') {
                name.split('.').next().unwrap_or("").to_string()
            } else {
                String::new()
            };

            let dim_type_str = entry
                .get("type")
                .and_then(|v| v.as_str())
                .unwrap_or("categorical");
            let dim_type = match dim_type_str {
                "continuous" => DimensionType::Continuous,
                "integer" => DimensionType::Integer,
                "subset" => DimensionType::Subset,
                "text" => DimensionType::Text,
                _ => DimensionType::Categorical,
            };

            let values = entry
                .get("values")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            let low = entry.get("low").and_then(|v| v.as_f64());
            let high = entry.get("high").and_then(|v| v.as_f64());
            let description = entry
                .get("description")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            SearchDimension {
                name,
                dim_type,
                values,
                low,
                high,
                description,
                primitive,
            }
        })
        .collect();

    SearchSpace {
        dimensions,
        fixed,
        constraints,
    }
}

/// Default search space covering all 5 primitives.
pub fn default_search_space() -> SearchSpace {
    SearchSpace {
        dimensions: vec![
            // Intelligence primitive
            SearchDimension {
                name: "intelligence.model".into(),
                dim_type: DimensionType::Categorical,
                values: vec![
                    serde_json::json!("qwen3:8b"),
                    serde_json::json!("qwen3:4b"),
                    serde_json::json!("qwen3:1.7b"),
                    serde_json::json!("llama3.1:8b"),
                    serde_json::json!("llama3.1:70b"),
                    serde_json::json!("gemma2:9b"),
                    serde_json::json!("mistral:7b"),
                    serde_json::json!("deepseek-r1:8b"),
                ],
                low: None,
                high: None,
                description: "The LLM model to use for generation".into(),
                primitive: "intelligence".into(),
            },
            SearchDimension {
                name: "intelligence.temperature".into(),
                dim_type: DimensionType::Continuous,
                values: vec![],
                low: Some(0.0),
                high: Some(1.0),
                description: "Generation temperature (0 = deterministic, 1 = creative)"
                    .into(),
                primitive: "intelligence".into(),
            },
            SearchDimension {
                name: "intelligence.max_tokens".into(),
                dim_type: DimensionType::Integer,
                values: vec![],
                low: Some(256.0),
                high: Some(8192.0),
                description: "Maximum tokens to generate per response".into(),
                primitive: "intelligence".into(),
            },
            SearchDimension {
                name: "intelligence.top_p".into(),
                dim_type: DimensionType::Continuous,
                values: vec![],
                low: Some(0.0),
                high: Some(1.0),
                description: "Nucleus sampling probability threshold".into(),
                primitive: "intelligence".into(),
            },
            SearchDimension {
                name: "intelligence.system_prompt".into(),
                dim_type: DimensionType::Text,
                values: vec![],
                low: None,
                high: None,
                description: "System prompt to guide model behavior".into(),
                primitive: "intelligence".into(),
            },
            // Engine primitive
            SearchDimension {
                name: "engine.backend".into(),
                dim_type: DimensionType::Categorical,
                values: vec![
                    serde_json::json!("ollama"),
                    serde_json::json!("vllm"),
                    serde_json::json!("sglang"),
                    serde_json::json!("llamacpp"),
                    serde_json::json!("mlx"),
                    serde_json::json!("lmstudio"),
                    serde_json::json!("exo"),
                    serde_json::json!("nexa"),
                    serde_json::json!("uzu"),
                    serde_json::json!("apple_fm"),
                ],
                low: None,
                high: None,
                description: "Inference engine backend".into(),
                primitive: "engine".into(),
            },
            // Agent primitive
            SearchDimension {
                name: "agent.type".into(),
                dim_type: DimensionType::Categorical,
                values: vec![
                    serde_json::json!("simple"),
                    serde_json::json!("orchestrator"),
                    serde_json::json!("native_react"),
                    serde_json::json!("native_openhands"),
                ],
                low: None,
                high: None,
                description: "Agent architecture to use".into(),
                primitive: "agent".into(),
            },
            SearchDimension {
                name: "agent.max_turns".into(),
                dim_type: DimensionType::Integer,
                values: vec![],
                low: Some(1.0),
                high: Some(30.0),
                description: "Maximum number of agent reasoning turns".into(),
                primitive: "agent".into(),
            },
            // Tools primitive
            SearchDimension {
                name: "tools.tool_set".into(),
                dim_type: DimensionType::Subset,
                values: vec![
                    serde_json::json!("calculator"),
                    serde_json::json!("think"),
                    serde_json::json!("file_read"),
                    serde_json::json!("file_write"),
                    serde_json::json!("web_search"),
                    serde_json::json!("code_interpreter"),
                    serde_json::json!("llm"),
                    serde_json::json!("shell_exec"),
                    serde_json::json!("apply_patch"),
                    serde_json::json!("http_request"),
                    serde_json::json!("database_query"),
                ],
                low: None,
                high: None,
                description: "Set of tools available to the agent".into(),
                primitive: "tools".into(),
            },
            // Learning primitive
            SearchDimension {
                name: "learning.routing_policy".into(),
                dim_type: DimensionType::Categorical,
                values: vec![
                    serde_json::json!("heuristic"),
                    serde_json::json!("grpo"),
                    serde_json::json!("bandit"),
                    serde_json::json!("learned"),
                ],
                low: None,
                high: None,
                description: "Router policy for model/agent selection".into(),
                primitive: "learning".into(),
            },
        ],
        fixed: HashMap::new(),
        constraints: vec![
            "SimpleAgent (agent.type='simple') should only have max_turns = 1".into(),
            "agent.max_turns must be >= 1".into(),
            "intelligence.temperature and intelligence.top_p \
             should not both be at extreme values"
                .into(),
        ],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_search_space() {
        let space = default_search_space();
        assert_eq!(space.dimensions.len(), 10);
        assert_eq!(space.constraints.len(), 3);
        assert!(space.fixed.is_empty());

        // Check primitive groupings
        let intelligence_dims: Vec<_> = space
            .dimensions
            .iter()
            .filter(|d| d.primitive == "intelligence")
            .collect();
        assert_eq!(intelligence_dims.len(), 5);

        let agent_dims: Vec<_> = space
            .dimensions
            .iter()
            .filter(|d| d.primitive == "agent")
            .collect();
        assert_eq!(agent_dims.len(), 2);
    }

    #[test]
    fn test_build_search_space_from_config() {
        let config = serde_json::json!({
            "optimize": {
                "search": [
                    {
                        "name": "intelligence.temperature",
                        "type": "continuous",
                        "low": 0.0,
                        "high": 1.0,
                        "description": "Generation temperature"
                    },
                    {
                        "name": "agent.type",
                        "type": "categorical",
                        "values": ["simple", "orchestrator"]
                    }
                ],
                "fixed": { "engine": "ollama" },
                "constraints": {
                    "rules": ["SimpleAgent should only have max_turns = 1"]
                }
            }
        });

        let space = build_search_space(&config);
        assert_eq!(space.dimensions.len(), 2);
        assert_eq!(space.dimensions[0].name, "intelligence.temperature");
        assert_eq!(space.dimensions[0].dim_type, DimensionType::Continuous);
        assert_eq!(space.dimensions[0].primitive, "intelligence");
        assert_eq!(space.dimensions[1].primitive, "agent");
        assert_eq!(space.fixed.len(), 1);
        assert_eq!(space.constraints.len(), 1);
    }

    #[test]
    fn test_build_search_space_empty_config() {
        let config = serde_json::json!({});
        let space = build_search_space(&config);
        assert!(space.dimensions.is_empty());
        assert!(space.fixed.is_empty());
        assert!(space.constraints.is_empty());
    }

    #[test]
    fn test_default_space_prompt_description() {
        let space = default_search_space();
        let desc = space.to_prompt_description();
        assert!(desc.contains("intelligence.model"));
        assert!(desc.contains("agent.type"));
        assert!(desc.contains("tools.tool_set"));
        assert!(desc.contains("learning.routing_policy"));
    }
}
