//! OpenJarvis Recipes — composable TOML configs that wire all five primitives.

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
    #[serde(default)]
    pub system_prompt_path: Option<String>,

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
    #[serde(default)]
    pub eval_backend: Option<String>,
    #[serde(default)]
    pub eval_max_samples: Option<usize>,
    #[serde(default)]
    pub eval_judge_model: Option<String>,

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
        insert_opt!(system_prompt_path);
        insert_opt!(routing_policy);
        insert_opt!(agent_policy);
        insert_opt!(eval_suites);
        insert_opt!(eval_benchmarks);
        insert_opt!(eval_backend);
        insert_opt!(eval_max_samples);
        insert_opt!(eval_judge_model);
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

#[derive(Debug, Deserialize)]
struct SectionedRecipeFile {
    recipe: Option<RecipeSection>,
    operator: Option<OperatorSection>,
    intelligence: Option<IntelligenceSection>,
    engine: Option<EngineSection>,
    agent: Option<AgentSection>,
    learning: Option<LearningSection>,
    eval: Option<EvalSection>,
    schedule: Option<ScheduleSection>,
    channels: Option<ChannelsSection>,
    #[serde(flatten)]
    raw: HashMap<String, serde_json::Value>,
}

#[derive(Debug, Deserialize, Default)]
struct RecipeSection {
    name: Option<String>,
    description: Option<String>,
    version: Option<String>,
    kind: Option<String>,
    #[serde(default)]
    required_capabilities: Option<Vec<String>>,
}

#[derive(Debug, Deserialize, Default)]
struct OperatorSection {
    name: Option<String>,
    description: Option<String>,
    version: Option<String>,
    #[serde(default)]
    agent: Option<OperatorAgentSection>,
    #[serde(default)]
    schedule: Option<ScheduleSection>,
    #[serde(default)]
    tools: Option<Vec<String>>,
    #[serde(default)]
    system_prompt: Option<String>,
    #[serde(default)]
    system_prompt_path: Option<String>,
    #[serde(default)]
    max_turns: Option<usize>,
    #[serde(default)]
    temperature: Option<f64>,
    #[serde(default)]
    schedule_type: Option<String>,
    #[serde(default)]
    schedule_value: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize, Default)]
struct OperatorAgentSection {
    max_turns: Option<usize>,
    temperature: Option<f64>,
    tools: Option<Vec<String>>,
    system_prompt: Option<String>,
    system_prompt_path: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
struct IntelligenceSection {
    model: Option<String>,
    quantization: Option<String>,
    provider: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
struct EngineSection {
    key: Option<String>,
    provider: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
struct AgentSection {
    #[serde(rename = "type")]
    agent_type: Option<String>,
    max_turns: Option<usize>,
    temperature: Option<f64>,
    max_tokens: Option<usize>,
    tools: Option<Vec<String>>,
    system_prompt: Option<String>,
    system_prompt_path: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
struct LearningSection {
    routing: Option<String>,
    agent: Option<String>,
}

#[derive(Debug, Deserialize, Default)]
struct EvalSection {
    suites: Option<Vec<String>>,
    benchmarks: Option<Vec<String>>,
    backend: Option<String>,
    max_samples: Option<usize>,
    judge_model: Option<String>,
}

#[derive(Debug, Deserialize, Default, Clone)]
struct ScheduleSection {
    #[serde(rename = "type")]
    schedule_type: Option<String>,
    value: Option<serde_json::Value>,
}

#[derive(Debug, Deserialize, Default)]
struct ChannelsSection {
    output: Option<Vec<String>>,
}

/// Parse a TOML string into a `Recipe`.
/// Supports both sectioned TOML (`[recipe]`, `[intelligence]`, etc., and legacy `[operator]`) and flat TOML.
pub fn load_recipe(toml_str: &str) -> Result<Recipe, String> {
    if let Ok(sec) = toml::from_str::<SectionedRecipeFile>(toml_str) {
        if sec.recipe.is_some()
            || sec.operator.is_some()
            || sec.intelligence.is_some()
            || sec.engine.is_some()
            || sec.agent.is_some()
            || sec.learning.is_some()
            || sec.eval.is_some()
            || sec.schedule.is_some()
            || sec.channels.is_some()
        {
            let recipe_sec = sec.recipe.unwrap_or_default();
            let op_sec = sec.operator.unwrap_or_default();
            let op_agent = op_sec.agent.unwrap_or_default();
            let intel_sec = sec.intelligence.unwrap_or_default();
            let engine_sec = sec.engine.unwrap_or_default();
            let agent_sec = sec.agent.unwrap_or_default();
            let learn_sec = sec.learning.unwrap_or_default();
            let eval_sec = sec.eval.unwrap_or_default();
            let sched_sec = sec.schedule.or(op_sec.schedule);
            let chan_sec = sec.channels.unwrap_or_default();

            let name = recipe_sec
                .name
                .or(op_sec.name)
                .ok_or_else(|| "missing field `name` in recipe/operator".to_string())?;

            let kind = recipe_sec.kind.or_else(|| {
                if sched_sec.is_some() {
                    Some("operator".to_string())
                } else {
                    Some("discrete".to_string())
                }
            });

            let provider = intel_sec.provider.or(engine_sec.provider);
            let schedule_type = sched_sec
                .as_ref()
                .and_then(|s| s.schedule_type.clone())
                .or(op_sec.schedule_type);

            let schedule_value = sched_sec
                .as_ref()
                .and_then(|s| {
                    s.value.as_ref().map(|v| match v {
                        serde_json::Value::String(s) => s.clone(),
                        other => other.to_string(),
                    })
                })
                .or_else(|| {
                    op_sec.schedule_value.map(|v| match v {
                        serde_json::Value::String(s) => s,
                        other => other.to_string(),
                    })
                });

            let max_turns = agent_sec.max_turns.or(op_agent.max_turns).or(op_sec.max_turns);
            let temperature = agent_sec.temperature.or(op_agent.temperature).or(op_sec.temperature);
            let tools = agent_sec.tools.or(op_agent.tools).or(op_sec.tools);
            let system_prompt = agent_sec.system_prompt.or(op_agent.system_prompt).or(op_sec.system_prompt);
            let system_prompt_path = agent_sec
                .system_prompt_path
                .or(op_agent.system_prompt_path)
                .or(op_sec.system_prompt_path);

            return Ok(Recipe {
                name,
                description: recipe_sec.description.or(op_sec.description),
                version: recipe_sec.version.or(op_sec.version).or_else(|| Some("0.1.0".to_string())),
                kind,
                model: intel_sec.model,
                quantization: intel_sec.quantization,
                provider,
                engine_key: engine_sec.key,
                agent_type: agent_sec.agent_type,
                max_turns,
                temperature,
                max_tokens: agent_sec.max_tokens,
                tools,
                system_prompt,
                system_prompt_path,
                routing_policy: learn_sec.routing,
                agent_policy: learn_sec.agent,
                eval_suites: eval_sec.suites,
                eval_benchmarks: eval_sec.benchmarks,
                eval_backend: eval_sec.backend,
                eval_max_samples: eval_sec.max_samples,
                eval_judge_model: eval_sec.judge_model,
                schedule_type,
                schedule_value,
                channels: chan_sec.output,
                required_capabilities: recipe_sec.required_capabilities,
                raw: sec.raw,
            });
        }
    }

    toml::from_str(toml_str).map_err(|e| format!("Failed to parse recipe TOML: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    const RECIPE_TOML: &str = r#"
name = "coding_assistant"
description = "A coding-focused assistant"
version = "0.1.0"
kind = "assistant"
model = "qwen3:8b"
engine_key = "ollama"
agent_type = "native_react"
max_turns = 10
temperature = 0.7
tools = ["calculator", "code_interpreter", "file_read"]
routing_policy = "heuristic"
"#;

    const SHIPPED_RESEARCH_ASSISTANT: &str =
        include_str!("../../../../src/openjarvis/recipes/data/research_assistant.toml");
    const SHIPPED_OPERATOR_CORRESPONDENT: &str =
        include_str!("../../../../src/openjarvis/recipes/data/operators/correspondent.toml");

    #[test]
    fn test_load_recipe() {
        let recipe = load_recipe(RECIPE_TOML).expect("should parse");
        assert_eq!(recipe.name, "coding_assistant");
        assert_eq!(recipe.model.as_deref(), Some("qwen3:8b"));
        assert_eq!(recipe.engine_key.as_deref(), Some("ollama"));
        assert_eq!(recipe.agent_type.as_deref(), Some("native_react"));
        assert_eq!(recipe.max_turns, Some(10));
        assert_eq!(recipe.tools.as_ref().map(|v| v.len()), Some(3));
    }

    #[test]
    fn test_load_shipped_sectioned_recipe() {
        let recipe = load_recipe(SHIPPED_RESEARCH_ASSISTANT).expect("should parse shipped recipe file");
        assert_eq!(recipe.name, "research_assistant");
        assert_eq!(recipe.model.as_deref(), Some("qwen3:8b"));
        assert_eq!(recipe.engine_key.as_deref(), Some("ollama"));
        assert_eq!(recipe.agent_type.as_deref(), Some("orchestrator"));
        assert_eq!(recipe.max_turns, Some(15));
        assert_eq!(recipe.temperature, Some(0.5));
        assert!(recipe.tools.as_ref().unwrap().contains(&"web_search".to_string()));
        assert_eq!(recipe.routing_policy.as_deref(), Some("grpo"));
        assert_eq!(recipe.agent_policy.as_deref(), Some("icl_updater"));
        assert_eq!(recipe.eval_suites.as_deref(), Some(&["reasoning".to_string()][..]));
    }

    #[test]
    fn test_load_shipped_operator_recipe() {
        let recipe = load_recipe(SHIPPED_OPERATOR_CORRESPONDENT).expect("should parse operator recipe");
        assert_eq!(recipe.name, "correspondent");
        assert_eq!(recipe.kind.as_deref(), Some("operator"));
        assert_eq!(recipe.max_turns, Some(15));
        assert_eq!(recipe.temperature, Some(0.4));
        assert_eq!(recipe.schedule_type.as_deref(), Some("interval"));
        assert_eq!(recipe.schedule_value.as_deref(), Some("300"));
        assert_eq!(recipe.system_prompt_path.as_deref(), Some("correspondent_prompt.md"));
        assert_eq!(recipe.tools.as_ref().unwrap().len(), 4);
    }

    #[test]
    fn test_to_builder_kwargs() {
        let recipe = load_recipe(RECIPE_TOML).unwrap();
        let kwargs = recipe.to_builder_kwargs();
        assert_eq!(kwargs.get("name").unwrap(), "coding_assistant");
        assert_eq!(kwargs.get("model").unwrap(), "qwen3:8b");
        assert_eq!(kwargs.get("engine_key").unwrap(), "ollama");
    }

    #[test]
    fn test_serde_roundtrip() {
        let recipe = load_recipe(RECIPE_TOML).unwrap();
        let json = serde_json::to_string(&recipe).unwrap();
        let back: Recipe = serde_json::from_str(&json).unwrap();
        assert_eq!(back.name, recipe.name);
        assert_eq!(back.model, recipe.model);
    }
}
