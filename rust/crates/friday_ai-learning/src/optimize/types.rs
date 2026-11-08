//! Core data types for the optimization framework.
//!
//! Rust translation of `src/friday_ai/learning/optimize/types.py`.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Search space types
// ---------------------------------------------------------------------------

/// The type of a search dimension.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DimensionType {
    Categorical,
    Continuous,
    Integer,
    Subset,
    Text,
}

impl std::fmt::Display for DimensionType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DimensionType::Categorical => write!(f, "categorical"),
            DimensionType::Continuous => write!(f, "continuous"),
            DimensionType::Integer => write!(f, "integer"),
            DimensionType::Subset => write!(f, "subset"),
            DimensionType::Text => write!(f, "text"),
        }
    }
}

/// One tunable dimension in the configuration search space.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchDimension {
    /// Dotted parameter name, e.g. `"agent.type"`, `"intelligence.temperature"`.
    pub name: String,
    /// Kind of parameter.
    pub dim_type: DimensionType,
    /// Explicit options for categorical/subset dimensions.
    #[serde(default)]
    pub values: Vec<serde_json::Value>,
    /// Lower bound for continuous/integer dimensions.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub low: Option<f64>,
    /// Upper bound for continuous/integer dimensions.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub high: Option<f64>,
    /// Human-readable explanation (shown to the LLM optimizer).
    #[serde(default)]
    pub description: String,
    /// Which primitive this dimension belongs to: intelligence, engine, agent, tools, learning.
    #[serde(default)]
    pub primitive: String,
}

/// The full space of configs the optimizer can propose.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SearchSpace {
    /// Tunable dimensions.
    #[serde(default)]
    pub dimensions: Vec<SearchDimension>,
    /// Parameters that are NOT being optimized (always injected).
    #[serde(default)]
    pub fixed: HashMap<String, serde_json::Value>,
    /// Natural-language constraints for the LLM optimizer.
    #[serde(default)]
    pub constraints: Vec<String>,
}

impl SearchSpace {
    /// Render the search space as structured text for the LLM optimizer prompt.
    pub fn to_prompt_description(&self) -> String {
        let mut lines = Vec::new();
        lines.push("# Search Space".to_string());
        lines.push(String::new());

        // Group dimensions by primitive
        let mut by_primitive: HashMap<&str, Vec<&SearchDimension>> = HashMap::new();
        for dim in &self.dimensions {
            let key = if dim.primitive.is_empty() {
                "other"
            } else {
                dim.primitive.as_str()
            };
            by_primitive.entry(key).or_default().push(dim);
        }

        let mut primitives: Vec<&&str> = by_primitive.keys().collect();
        primitives.sort();

        for primitive in primitives {
            // Title-case the primitive name
            let title = {
                let mut chars = primitive.chars();
                match chars.next() {
                    None => String::new(),
                    Some(c) => {
                        let upper: String = c.to_uppercase().collect();
                        upper + chars.as_str()
                    }
                }
            };
            lines.push(format!("## {title}"));

            for dim in &by_primitive[primitive] {
                lines.push(format!("- **{}** ({})", dim.name, dim.dim_type));
                if !dim.description.is_empty() {
                    lines.push(format!("  Description: {}", dim.description));
                }
                match dim.dim_type {
                    DimensionType::Categorical | DimensionType::Subset => {
                        lines.push(format!("  Options: {:?}", dim.values));
                    }
                    DimensionType::Continuous | DimensionType::Integer => {
                        let lo = dim.low.map(|v| v.to_string()).unwrap_or_default();
                        let hi = dim.high.map(|v| v.to_string()).unwrap_or_default();
                        lines.push(format!("  Range: [{lo}, {hi}]"));
                    }
                    DimensionType::Text => {
                        lines.push("  Free-form text".to_string());
                    }
                }
            }
            lines.push(String::new());
        }

        if !self.fixed.is_empty() {
            lines.push("## Fixed Parameters".to_string());
            let mut sorted_keys: Vec<&String> = self.fixed.keys().collect();
            sorted_keys.sort();
            for k in sorted_keys {
                lines.push(format!("- {k} = {}", self.fixed[k]));
            }
            lines.push(String::new());
        }

        if !self.constraints.is_empty() {
            lines.push("## Constraints".to_string());
            for c in &self.constraints {
                lines.push(format!("- {c}"));
            }
            lines.push(String::new());
        }

        lines.join("\n")
    }
}

// ---------------------------------------------------------------------------
// Optimization objective
// ---------------------------------------------------------------------------

/// Direction in which an objective should be optimized.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Maximize,
    Minimize,
}

impl std::fmt::Display for Direction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Direction::Maximize => write!(f, "maximize"),
            Direction::Minimize => write!(f, "minimize"),
        }
    }
}

/// A single optimization objective (e.g. maximize accuracy).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ObjectiveSpec {
    pub metric: String,
    pub direction: Direction,
    #[serde(default = "default_weight")]
    pub weight: f64,
}

fn default_weight() -> f64 {
    1.0
}

/// Default objectives: accuracy up, latency and cost down.
pub fn default_objectives() -> Vec<ObjectiveSpec> {
    vec![
        ObjectiveSpec {
            metric: "accuracy".into(),
            direction: Direction::Maximize,
            weight: 1.0,
        },
        ObjectiveSpec {
            metric: "mean_latency_seconds".into(),
            direction: Direction::Minimize,
            weight: 1.0,
        },
        ObjectiveSpec {
            metric: "total_cost_usd".into(),
            direction: Direction::Minimize,
            weight: 1.0,
        },
    ]
}

/// All supported objectives.
pub fn all_objectives() -> Vec<ObjectiveSpec> {
    vec![
        ObjectiveSpec { metric: "accuracy".into(), direction: Direction::Maximize, weight: 1.0 },
        ObjectiveSpec { metric: "mean_latency_seconds".into(), direction: Direction::Minimize, weight: 1.0 },
        ObjectiveSpec { metric: "total_cost_usd".into(), direction: Direction::Minimize, weight: 1.0 },
        ObjectiveSpec { metric: "total_energy_joules".into(), direction: Direction::Minimize, weight: 1.0 },
        ObjectiveSpec { metric: "avg_power_watts".into(), direction: Direction::Minimize, weight: 1.0 },
        ObjectiveSpec { metric: "throughput_tok_per_sec".into(), direction: Direction::Maximize, weight: 1.0 },
        ObjectiveSpec { metric: "mfu_pct".into(), direction: Direction::Maximize, weight: 1.0 },
        ObjectiveSpec { metric: "mbu_pct".into(), direction: Direction::Maximize, weight: 1.0 },
        ObjectiveSpec { metric: "ipw".into(), direction: Direction::Maximize, weight: 1.0 },
        ObjectiveSpec { metric: "ipj".into(), direction: Direction::Maximize, weight: 1.0 },
        ObjectiveSpec { metric: "energy_per_output_token".into(), direction: Direction::Minimize, weight: 1.0 },
        ObjectiveSpec { metric: "throughput_per_watt".into(), direction: Direction::Maximize, weight: 1.0 },
        ObjectiveSpec { metric: "ttft".into(), direction: Direction::Minimize, weight: 1.0 },
        ObjectiveSpec { metric: "mean_itl_ms".into(), direction: Direction::Minimize, weight: 1.0 },
    ]
}

// ---------------------------------------------------------------------------
// Per-sample and per-benchmark scores
// ---------------------------------------------------------------------------

/// Per-sample metrics from an evaluation trial.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SampleScore {
    pub record_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub is_correct: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score: Option<f64>,
    #[serde(default)]
    pub latency_seconds: f64,
    #[serde(default)]
    pub prompt_tokens: i64,
    #[serde(default)]
    pub completion_tokens: i64,
    #[serde(default)]
    pub cost_usd: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(default)]
    pub ttft: f64,
    #[serde(default)]
    pub energy_joules: f64,
    #[serde(default)]
    pub power_watts: f64,
    #[serde(default)]
    pub gpu_utilization_pct: f64,
    #[serde(default)]
    pub throughput_tok_per_sec: f64,
    #[serde(default)]
    pub mfu_pct: f64,
    #[serde(default)]
    pub mbu_pct: f64,
    #[serde(default)]
    pub ipw: f64,
    #[serde(default)]
    pub ipj: f64,
    #[serde(default)]
    pub energy_per_output_token_joules: f64,
    #[serde(default)]
    pub throughput_per_watt: f64,
    #[serde(default)]
    pub mean_itl_ms: f64,
}

/// Per-benchmark metrics from a multi-benchmark evaluation trial.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BenchmarkScore {
    pub benchmark: String,
    #[serde(default)]
    pub accuracy: f64,
    #[serde(default)]
    pub mean_latency_seconds: f64,
    #[serde(default)]
    pub total_cost_usd: f64,
    #[serde(default)]
    pub total_energy_joules: f64,
    #[serde(default)]
    pub total_tokens: i64,
    #[serde(default)]
    pub samples_evaluated: i64,
    #[serde(default)]
    pub errors: i64,
    #[serde(default = "default_weight")]
    pub weight: f64,
    /// Optional per-sample scores within this benchmark.
    #[serde(default)]
    pub sample_scores: Vec<SampleScore>,
}

// ---------------------------------------------------------------------------
// Trial types
// ---------------------------------------------------------------------------

/// Structured feedback from trial analysis.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TrialFeedback {
    #[serde(default)]
    pub summary_text: String,
    #[serde(default)]
    pub failure_patterns: Vec<String>,
    #[serde(default)]
    pub primitive_ratings: HashMap<String, String>,
    #[serde(default)]
    pub suggested_changes: Vec<String>,
    #[serde(default)]
    pub target_primitive: String,
}

/// A single candidate configuration proposed by the optimizer.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrialConfig {
    pub trial_id: String,
    /// Dotted keys -> values, e.g. `{"intelligence.temperature": 0.7}`.
    #[serde(default)]
    pub params: HashMap<String, serde_json::Value>,
    /// Optimizer's explanation of why this config was proposed.
    #[serde(default)]
    pub reasoning: String,
}

/// Result of evaluating a trial.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrialResult {
    pub trial_id: String,
    pub config: TrialConfig,
    #[serde(default)]
    pub accuracy: f64,
    #[serde(default)]
    pub mean_latency_seconds: f64,
    #[serde(default)]
    pub total_cost_usd: f64,
    #[serde(default)]
    pub total_energy_joules: f64,
    #[serde(default)]
    pub total_tokens: i64,
    #[serde(default)]
    pub samples_evaluated: i64,
    #[serde(default)]
    pub analysis: String,
    #[serde(default)]
    pub failure_modes: Vec<String>,
    #[serde(default)]
    pub sample_scores: Vec<SampleScore>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub structured_feedback: Option<TrialFeedback>,
    #[serde(default)]
    pub per_benchmark: Vec<BenchmarkScore>,
}

// ---------------------------------------------------------------------------
// Optimization run
// ---------------------------------------------------------------------------

/// Status of an optimization run.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum RunStatus {
    #[default]
    Running,
    Completed,
    Failed,
}

impl std::fmt::Display for RunStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RunStatus::Running => write!(f, "running"),
            RunStatus::Completed => write!(f, "completed"),
            RunStatus::Failed => write!(f, "failed"),
        }
    }
}

impl std::str::FromStr for RunStatus {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "running" => Ok(RunStatus::Running),
            "completed" => Ok(RunStatus::Completed),
            "failed" => Ok(RunStatus::Failed),
            _ => Err(format!("Unknown run status: {s}")),
        }
    }
}

/// Complete optimization session.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OptimizationRun {
    pub run_id: String,
    pub search_space: SearchSpace,
    #[serde(default)]
    pub trials: Vec<TrialResult>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub best_trial: Option<TrialResult>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub best_recipe_path: Option<String>,
    #[serde(default)]
    pub status: RunStatus,
    #[serde(default)]
    pub optimizer_model: String,
    #[serde(default)]
    pub benchmark: String,
    #[serde(default)]
    pub benchmarks: Vec<String>,
    #[serde(default)]
    pub pareto_frontier: Vec<TrialResult>,
    #[serde(default = "default_objectives")]
    pub objectives: Vec<ObjectiveSpec>,
}

// ---------------------------------------------------------------------------
// Mapping from dotted param names to Recipe constructor fields
// ---------------------------------------------------------------------------

/// Maps dotted param names (used in search space) to Recipe field names.
pub fn param_to_recipe_field(dotted_key: &str) -> Option<&'static str> {
    match dotted_key {
        "intelligence.model" => Some("model"),
        "intelligence.temperature" => Some("temperature"),
        "intelligence.max_tokens" => Some("max_tokens"),
        "intelligence.quantization" => Some("quantization"),
        "engine.backend" => Some("engine_key"),
        "agent.type" => Some("agent_type"),
        "agent.max_turns" => Some("max_turns"),
        "agent.system_prompt" | "intelligence.system_prompt" => Some("system_prompt"),
        "tools.tool_set" => Some("tools"),
        "learning.routing_policy" => Some("routing_policy"),
        "learning.agent_policy" => Some("agent_policy"),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dimension_type_display() {
        assert_eq!(DimensionType::Categorical.to_string(), "categorical");
        assert_eq!(DimensionType::Continuous.to_string(), "continuous");
        assert_eq!(DimensionType::Text.to_string(), "text");
    }

    #[test]
    fn test_dimension_type_serde_roundtrip() {
        let dt = DimensionType::Integer;
        let json = serde_json::to_string(&dt).unwrap();
        assert_eq!(json, "\"integer\"");
        let parsed: DimensionType = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed, dt);
    }

    #[test]
    fn test_direction_display() {
        assert_eq!(Direction::Maximize.to_string(), "maximize");
        assert_eq!(Direction::Minimize.to_string(), "minimize");
    }

    #[test]
    fn test_search_space_to_prompt_description() {
        let space = SearchSpace {
            dimensions: vec![
                SearchDimension {
                    name: "intelligence.temperature".into(),
                    dim_type: DimensionType::Continuous,
                    values: vec![],
                    low: Some(0.0),
                    high: Some(1.0),
                    description: "Generation temperature".into(),
                    primitive: "intelligence".into(),
                },
                SearchDimension {
                    name: "agent.type".into(),
                    dim_type: DimensionType::Categorical,
                    values: vec![
                        serde_json::json!("simple"),
                        serde_json::json!("orchestrator"),
                    ],
                    low: None,
                    high: None,
                    description: "Agent architecture".into(),
                    primitive: "agent".into(),
                },
            ],
            fixed: {
                let mut m = HashMap::new();
                m.insert("engine".into(), serde_json::json!("ollama"));
                m
            },
            constraints: vec![
                "SimpleAgent should only have max_turns = 1".into(),
            ],
        };

        let desc = space.to_prompt_description();
        assert!(desc.contains("# Search Space"));
        assert!(desc.contains("## Intelligence"));
        assert!(desc.contains("## Agent"));
        assert!(desc.contains("Generation temperature"));
        assert!(desc.contains("## Fixed Parameters"));
        assert!(desc.contains("## Constraints"));
    }

    #[test]
    fn test_trial_config_serde() {
        let config = TrialConfig {
            trial_id: "abc123".into(),
            params: {
                let mut m = HashMap::new();
                m.insert("intelligence.temperature".into(), serde_json::json!(0.7));
                m
            },
            reasoning: "Initial config".into(),
        };
        let json = serde_json::to_string(&config).unwrap();
        let parsed: TrialConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.trial_id, "abc123");
        assert_eq!(parsed.params.len(), 1);
    }

    #[test]
    fn test_trial_result_serde() {
        let result = TrialResult {
            trial_id: "t1".into(),
            config: TrialConfig {
                trial_id: "t1".into(),
                params: HashMap::new(),
                reasoning: String::new(),
            },
            accuracy: 0.85,
            mean_latency_seconds: 1.2,
            total_cost_usd: 0.05,
            total_energy_joules: 100.0,
            total_tokens: 500,
            samples_evaluated: 50,
            analysis: "Good".into(),
            failure_modes: vec!["timeout".into()],
            sample_scores: vec![],
            structured_feedback: None,
            per_benchmark: vec![],
        };
        let json = serde_json::to_string(&result).unwrap();
        let parsed: TrialResult = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.trial_id, "t1");
        assert!((parsed.accuracy - 0.85).abs() < 1e-9);
    }

    #[test]
    fn test_run_status_roundtrip() {
        let status = RunStatus::Completed;
        assert_eq!(status.to_string(), "completed");
        let parsed: RunStatus = "completed".parse().unwrap();
        assert_eq!(parsed, status);
    }

    #[test]
    fn test_default_objectives() {
        let objs = default_objectives();
        assert_eq!(objs.len(), 3);
        assert_eq!(objs[0].metric, "accuracy");
        assert_eq!(objs[0].direction, Direction::Maximize);
    }

    #[test]
    fn test_all_objectives() {
        let objs = all_objectives();
        assert_eq!(objs.len(), 14);
    }

    #[test]
    fn test_param_to_recipe_field() {
        assert_eq!(
            param_to_recipe_field("intelligence.model"),
            Some("model")
        );
        assert_eq!(
            param_to_recipe_field("agent.type"),
            Some("agent_type")
        );
        assert_eq!(param_to_recipe_field("unknown.param"), None);
    }

    #[test]
    fn test_sample_score_default() {
        let ss = SampleScore::default();
        assert_eq!(ss.record_id, "");
        assert_eq!(ss.latency_seconds, 0.0);
        assert!(ss.is_correct.is_none());
    }

    #[test]
    fn test_benchmark_score_serde() {
        let bs = BenchmarkScore {
            benchmark: "supergpqa".into(),
            accuracy: 0.72,
            mean_latency_seconds: 2.5,
            total_cost_usd: 0.1,
            total_energy_joules: 50.0,
            total_tokens: 1000,
            samples_evaluated: 100,
            errors: 2,
            weight: 1.0,
            sample_scores: vec![],
        };
        let json = serde_json::to_string(&bs).unwrap();
        let parsed: BenchmarkScore = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.benchmark, "supergpqa");
    }

    #[test]
    fn test_trial_feedback_serde() {
        let fb = TrialFeedback {
            summary_text: "Good result".into(),
            failure_patterns: vec!["timeout".into()],
            primitive_ratings: {
                let mut m = HashMap::new();
                m.insert("intelligence".into(), "high".into());
                m
            },
            suggested_changes: vec!["increase temperature".into()],
            target_primitive: "intelligence".into(),
        };
        let json = serde_json::to_string(&fb).unwrap();
        let parsed: TrialFeedback = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.summary_text, "Good result");
        assert_eq!(parsed.target_primitive, "intelligence");
    }
}
