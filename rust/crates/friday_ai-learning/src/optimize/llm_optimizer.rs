//! LLM-based optimizer for FridayAI configuration tuning.
//!
//! Rust translation of `src/friday_ai/learning/optimize/llm_optimizer.py`.
//!
//! The actual LLM call is abstracted via the [`OptimizerBackend`] trait so
//! that Python can provide the implementation via FFI / PyO3.

use std::collections::{HashMap, HashSet};

use super::types::{SearchSpace, TrialConfig, TrialFeedback, TrialResult};

// ---------------------------------------------------------------------------
// Backend trait (Python fills this in)
// ---------------------------------------------------------------------------

/// Abstraction for the LLM backend used by the optimizer.
///
/// The real implementation calls a cloud LLM (e.g. Claude, GPT) to generate
/// configuration proposals and trial analyses. In Rust-only tests a simple
/// mock can be used.
pub trait OptimizerBackend: Send + Sync {
    /// Generate a text response from the LLM.
    fn generate(
        &self,
        prompt: &str,
        model: &str,
        system: &str,
        temperature: f64,
        max_tokens: usize,
    ) -> String;
}

// ---------------------------------------------------------------------------
// LLMOptimizer
// ---------------------------------------------------------------------------

/// Uses an LLM to propose optimal FridayAI configurations.
///
/// Inspired by DSPy's GEPA: uses textual feedback from execution traces
/// rather than just scalar rewards to guide the optimizer.
pub struct LLMOptimizer {
    pub search_space: SearchSpace,
    pub optimizer_model: String,
    backend: Option<Box<dyn OptimizerBackend>>,
}

impl LLMOptimizer {
    /// Create a new LLM optimizer.
    ///
    /// If `backend` is `None`, `propose_initial` / `propose_next` will
    /// return a default config derived from the search space's fixed params.
    pub fn new(search_space: SearchSpace, optimizer_model: String) -> Self {
        Self {
            search_space,
            optimizer_model,
            backend: None,
        }
    }

    /// Create a new LLM optimizer with a backend.
    pub fn with_backend(
        search_space: SearchSpace,
        optimizer_model: String,
        backend: Box<dyn OptimizerBackend>,
    ) -> Self {
        Self {
            search_space,
            optimizer_model,
            backend: Some(backend),
        }
    }

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------

    /// Propose a reasonable starting config from the search space.
    ///
    /// If no backend is configured, returns a config with just fixed params.
    pub fn propose_initial(&self) -> TrialConfig {
        let trial_id = new_trial_id();

        if let Some(ref backend) = self.backend {
            let prompt = self.build_initial_prompt();
            let response = backend.generate(
                &prompt,
                &self.optimizer_model,
                "You are an expert AI systems optimizer.",
                0.7,
                2048,
            );
            return self.parse_config_response(&response, &trial_id);
        }

        // Fallback: use fixed params
        let fixed: HashMap<String, serde_json::Value> = self
            .search_space
            .fixed
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();

        TrialConfig {
            trial_id,
            params: fixed,
            reasoning: "Default config from fixed parameters".into(),
        }
    }

    /// Propose the next config based on trial history.
    pub fn propose_next(&self, history: &[TrialResult]) -> TrialConfig {
        let trial_id = new_trial_id();

        if let Some(ref backend) = self.backend {
            let prompt = self.build_propose_prompt(history, None);
            let response = backend.generate(
                &prompt,
                &self.optimizer_model,
                "You are an expert AI systems optimizer.",
                0.7,
                2048,
            );
            return self.parse_config_response(&response, &trial_id);
        }

        // Fallback
        let fixed: HashMap<String, serde_json::Value> = self
            .search_space
            .fixed
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();

        TrialConfig {
            trial_id,
            params: fixed,
            reasoning: "Default config (no backend available)".into(),
        }
    }

    /// Propose a config that only changes one primitive.
    pub fn propose_targeted(
        &self,
        history: &[TrialResult],
        base_config: &TrialConfig,
        target_primitive: &str,
        frontier_ids: Option<&HashSet<String>>,
    ) -> TrialConfig {
        let trial_id = new_trial_id();

        if let Some(ref backend) = self.backend {
            let prompt =
                self.build_targeted_prompt(history, base_config, target_primitive, frontier_ids);
            let response = backend.generate(
                &prompt,
                &self.optimizer_model,
                "You are an expert AI systems optimizer.",
                0.7,
                2048,
            );
            let proposed = self.parse_config_response(&response, &trial_id);

            // Enforce constraint: preserve non-target params from base_config
            let mut merged = base_config.params.clone();
            let target_prefix = format!("{target_primitive}.");
            let alt_prefix = {
                let trimmed = target_primitive.trim_end_matches('s');
                format!("{trimmed}.")
            };
            for (key, value) in &proposed.params {
                if key.starts_with(&target_prefix) || key.starts_with(&alt_prefix) {
                    merged.insert(key.clone(), value.clone());
                }
            }

            return TrialConfig {
                trial_id: proposed.trial_id,
                params: merged,
                reasoning: proposed.reasoning,
            };
        }

        // Fallback: return base config as-is
        TrialConfig {
            trial_id,
            params: base_config.params.clone(),
            reasoning: format!("Targeted mutation on {target_primitive} (no backend)"),
        }
    }

    /// Combine best aspects of frontier members into one config.
    pub fn propose_merge(
        &self,
        candidates: &[TrialResult],
        history: &[TrialResult],
        frontier_ids: Option<&HashSet<String>>,
    ) -> TrialConfig {
        let trial_id = new_trial_id();

        if let Some(ref backend) = self.backend {
            let prompt = self.build_merge_prompt(candidates, history, frontier_ids);
            let response = backend.generate(
                &prompt,
                &self.optimizer_model,
                "You are an expert AI systems optimizer.",
                0.7,
                2048,
            );
            return self.parse_config_response(&response, &trial_id);
        }

        // Fallback: use the first candidate's config
        let params = candidates
            .first()
            .map(|c| c.config.params.clone())
            .unwrap_or_default();

        TrialConfig {
            trial_id,
            params,
            reasoning: "Merge fallback (no backend)".into(),
        }
    }

    /// Analyze a completed trial. Returns structured feedback.
    pub fn analyze_trial(
        &self,
        trial: &TrialConfig,
        accuracy: f64,
        mean_latency_seconds: f64,
        total_cost_usd: f64,
    ) -> TrialFeedback {
        if let Some(ref backend) = self.backend {
            let prompt = format!(
                "Analyze this FridayAI evaluation result.\n\n\
                 ## Configuration\n{}\n\n\
                 ## Results\n- accuracy: {accuracy:.4}\n\
                 - mean_latency_seconds: {mean_latency_seconds:.4}\n\
                 - total_cost_usd: {total_cost_usd:.4}\n\n\
                 Provide your analysis as a JSON object inside a ```json code block with:\n\
                 1. \"summary_text\": string with detailed analysis\n\
                 2. \"failure_patterns\": list of identified failure patterns\n\
                 3. \"primitive_ratings\": dict mapping primitive names to \"high\"/\"medium\"/\"low\"\n\
                 4. \"suggested_changes\": list of specific config changes to try\n\
                 5. \"target_primitive\": which primitive to change next",
                format_config_params(&trial.params),
            );
            let response = backend.generate(
                &prompt,
                &self.optimizer_model,
                "You are an expert AI systems analyst.",
                0.3,
                2048,
            );
            return parse_feedback_response(&response);
        }

        // Fallback
        TrialFeedback {
            summary_text: format!(
                "Trial {}: accuracy={accuracy:.4}, latency={mean_latency_seconds:.4}s, cost=${total_cost_usd:.4}",
                trial.trial_id,
            ),
            ..Default::default()
        }
    }

    // ------------------------------------------------------------------
    // Prompt builders
    // ------------------------------------------------------------------

    #[allow(clippy::vec_init_then_push)]
    fn build_initial_prompt(&self) -> String {
        let mut lines = Vec::new();
        lines.push("You are optimizing an FridayAI AI system configuration.".into());
        lines.push(String::new());
        lines.push(self.search_space.to_prompt_description());
        lines.push("## Objective".into());
        lines.push("Maximize accuracy while minimizing latency and cost.".into());
        lines.push(String::new());
        lines.push("## Your Task".into());
        lines.push(
            "Propose an initial configuration that is a reasonable starting \
             point for optimization. Choose sensible defaults that balance \
             accuracy, latency, and cost."
                .into(),
        );
        lines.push(String::new());
        lines.push(
            "Return a JSON object inside a ```json code block with:".into(),
        );
        lines.push(
            "1. \"params\": dict of config params (dotted keys matching the search space)"
                .into(),
        );
        lines.push(
            "2. \"reasoning\": string explaining why this is a good starting configuration"
                .into(),
        );
        lines.join("\n")
    }

    #[allow(clippy::vec_init_then_push)]
    fn build_propose_prompt(
        &self,
        history: &[TrialResult],
        frontier_ids: Option<&HashSet<String>>,
    ) -> String {
        let mut lines = Vec::new();
        lines.push("You are optimizing an FridayAI AI system configuration.".into());
        lines.push(String::new());
        lines.push(self.search_space.to_prompt_description());

        lines.push("## Optimization History".into());
        if history.is_empty() {
            lines.push("No trials have been run yet.".into());
        } else {
            lines.push(format_history(history, frontier_ids));
        }
        lines.push(String::new());

        lines.push("## Objective".into());
        lines.push("Maximize accuracy while minimizing latency and cost.".into());
        lines.push(String::new());
        lines.push("## Your Task".into());
        lines.push(
            "Propose the next configuration to evaluate. Learn from \
             previous trials to improve results."
                .into(),
        );
        lines.push(String::new());
        lines.push(
            "Return a JSON object inside a ```json code block with:".into(),
        );
        lines.push(
            "1. \"params\": dict of config params (dotted keys matching the search space)"
                .into(),
        );
        lines.push(
            "2. \"reasoning\": string explaining why this config should improve results".into(),
        );
        lines.join("\n")
    }

    #[allow(clippy::vec_init_then_push)]
    fn build_targeted_prompt(
        &self,
        history: &[TrialResult],
        base_config: &TrialConfig,
        target_primitive: &str,
        frontier_ids: Option<&HashSet<String>>,
    ) -> String {
        let mut lines = Vec::new();
        lines.push("You are optimizing an FridayAI AI system configuration.".into());
        lines.push(String::new());
        lines.push(self.search_space.to_prompt_description());

        lines.push("## Base Configuration".into());
        lines.push(format_config_params(&base_config.params));
        lines.push(String::new());

        lines.push(format!("## Target Primitive: {target_primitive}"));
        lines.push(format!(
            "ONLY change parameters under the '{target_primitive}' primitive. \
             Keep all other parameters exactly as they are."
        ));
        lines.push(String::new());

        lines.push("## Optimization History".into());
        if !history.is_empty() {
            lines.push(format_history(history, frontier_ids));
        }
        lines.push(String::new());

        lines.push(
            format!(
                "Return a JSON object inside a ```json code block with:\n\
                 1. \"params\": dict of config params (only change {target_primitive} params)\n\
                 2. \"reasoning\": string explaining your changes"
            ),
        );
        lines.join("\n")
    }

    #[allow(clippy::vec_init_then_push)]
    fn build_merge_prompt(
        &self,
        candidates: &[TrialResult],
        history: &[TrialResult],
        frontier_ids: Option<&HashSet<String>>,
    ) -> String {
        let mut lines = Vec::new();
        lines.push("You are optimizing an FridayAI AI system configuration.".into());
        lines.push(String::new());
        lines.push(self.search_space.to_prompt_description());

        lines.push("## Frontier Candidates to Merge".into());
        for (i, cand) in candidates.iter().enumerate() {
            lines.push(format!(
                "### Candidate {} (id={})",
                i + 1,
                cand.trial_id
            ));
            lines.push(format!(
                "Params: {}",
                serde_json::to_string(&cand.config.params).unwrap_or_default()
            ));
            lines.push(format!("Accuracy: {:.4}", cand.accuracy));
            lines.push(format!("Latency: {:.4}s", cand.mean_latency_seconds));
            lines.push(format!("Cost: ${:.4}", cand.total_cost_usd));
            lines.push(format!("Energy: {:.4}J", cand.total_energy_joules));
            lines.push(String::new());
        }

        lines.push(
            "Combine the best aspects of these frontier configs into \
             one unified configuration."
                .into(),
        );
        lines.push(String::new());

        if !history.is_empty() {
            lines.push("## Full History".into());
            lines.push(format_history(history, frontier_ids));
            lines.push(String::new());
        }

        lines.push(
            "Return a JSON object inside a ```json code block with:\n\
             1. \"params\": dict of merged config params\n\
             2. \"reasoning\": string explaining the merge strategy"
                .into(),
        );
        lines.join("\n")
    }

    // ------------------------------------------------------------------
    // Response parsing
    // ------------------------------------------------------------------

    fn parse_config_response(&self, response: &str, trial_id: &str) -> TrialConfig {
        // Try to extract from ```json code block
        if let Some(json_str) = extract_json_block(response) {
            if let Ok(data) = serde_json::from_str::<serde_json::Value>(&json_str) {
                if let Some(config) = self.config_from_value(&data, trial_id) {
                    return config;
                }
            }
        }

        // Try to find a raw JSON object
        if let Some(config) = self.try_parse_raw_json(response, trial_id) {
            return config;
        }

        // Last resort: return config with fixed params
        let fixed: HashMap<String, serde_json::Value> = self
            .search_space
            .fixed
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();

        TrialConfig {
            trial_id: trial_id.into(),
            params: fixed,
            reasoning: "Failed to parse LLM response.".into(),
        }
    }

    fn config_from_value(
        &self,
        data: &serde_json::Value,
        trial_id: &str,
    ) -> Option<TrialConfig> {
        let params_val = data.get("params")?;
        let params: HashMap<String, serde_json::Value> =
            serde_json::from_value(params_val.clone()).ok()?;
        let reasoning = data
            .get("reasoning")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string();

        // Inject fixed params
        let mut merged = params;
        for (key, value) in &self.search_space.fixed {
            merged.insert(key.clone(), value.clone());
        }

        Some(TrialConfig {
            trial_id: trial_id.into(),
            params: merged,
            reasoning,
        })
    }

    fn try_parse_raw_json(&self, response: &str, trial_id: &str) -> Option<TrialConfig> {
        // Scan for '{' and try to parse JSON objects
        for (idx, _) in response.match_indices('{') {
            if let Ok(data) = serde_json::from_str::<serde_json::Value>(&response[idx..]) {
                if data.is_object() {
                    if let Some(config) = self.config_from_value(&data, trial_id) {
                        return Some(config);
                    }
                }
            }
        }
        None
    }
}

// ---------------------------------------------------------------------------
// Free-standing helpers
// ---------------------------------------------------------------------------

fn new_trial_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()[..12].to_string()
}

/// Extract content from a ```json ... ``` or ``` ... ``` code block.
fn extract_json_block(text: &str) -> Option<String> {
    // Try ```json first ((?s) enables dotall so . matches \n)
    let re_json = regex::Regex::new(r"(?s)```json\s*\n?(.*?)\n?\s*```").ok()?;
    if let Some(caps) = re_json.captures(text) {
        return Some(caps.get(1)?.as_str().trim().to_string());
    }

    // Try generic ```
    let re_code = regex::Regex::new(r"(?s)```\s*\n?(.*?)\n?\s*```").ok()?;
    if let Some(caps) = re_code.captures(text) {
        return Some(caps.get(1)?.as_str().trim().to_string());
    }

    None
}

/// Parse an LLM response into a [`TrialFeedback`].
fn parse_feedback_response(response: &str) -> TrialFeedback {
    if let Some(json_str) = extract_json_block(response) {
        if let Ok(fb) = serde_json::from_str::<TrialFeedback>(&json_str) {
            return fb;
        }
    }

    // Try raw JSON
    for (idx, _) in response.match_indices('{') {
        if let Ok(fb) = serde_json::from_str::<TrialFeedback>(&response[idx..]) {
            return fb;
        }
    }

    // Fallback: wrap raw text
    TrialFeedback {
        summary_text: response.trim().to_string(),
        ..Default::default()
    }
}

fn format_config_params(params: &HashMap<String, serde_json::Value>) -> String {
    let mut sorted: Vec<(&String, &serde_json::Value)> = params.iter().collect();
    sorted.sort_by_key(|(k, _)| k.as_str());
    sorted
        .iter()
        .map(|(k, v)| format!("- {k}: {v}"))
        .collect::<Vec<_>>()
        .join("\n")
}

fn format_history(
    history: &[TrialResult],
    frontier_ids: Option<&HashSet<String>>,
) -> String {
    let mut lines = Vec::new();
    for (i, result) in history.iter().enumerate() {
        let tag = frontier_ids
            .filter(|ids| ids.contains(&result.trial_id))
            .map(|_| " [FRONTIER]")
            .unwrap_or("");

        lines.push(format!(
            "### Trial {} (id={}){tag}",
            i + 1,
            result.trial_id
        ));
        lines.push(format!(
            "Params: {}",
            serde_json::to_string(&result.config.params).unwrap_or_default()
        ));
        lines.push(format!("Accuracy: {:.4}", result.accuracy));
        lines.push(format!("Latency: {:.4}s", result.mean_latency_seconds));
        lines.push(format!("Cost: ${:.4}", result.total_cost_usd));
        lines.push(format!("Energy: {:.4}J", result.total_energy_joules));

        if let Some(ref fb) = result.structured_feedback {
            if !fb.failure_patterns.is_empty() {
                lines.push(format!(
                    "Failure patterns: {}",
                    fb.failure_patterns.join(", ")
                ));
            }
            if !fb.primitive_ratings.is_empty() {
                let ratings: Vec<String> = {
                    let mut sorted: Vec<_> = fb.primitive_ratings.iter().collect();
                    sorted.sort_by_key(|(k, _)| k.as_str());
                    sorted
                        .iter()
                        .map(|(k, v)| format!("{k}={v}"))
                        .collect()
                };
                lines.push(format!("Primitive ratings: {}", ratings.join(", ")));
            }
            if !fb.target_primitive.is_empty() {
                lines.push(format!("Target primitive: {}", fb.target_primitive));
            }
        } else if !result.analysis.is_empty() {
            lines.push(format!("Analysis: {}", result.analysis));
        }

        if !result.failure_modes.is_empty() {
            lines.push(format!(
                "Failure modes: {}",
                result.failure_modes.join(", ")
            ));
        }
        lines.push(String::new());
    }
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::optimize::types::*;

    /// A mock backend that returns a canned JSON response.
    struct MockBackend {
        response: String,
    }

    impl OptimizerBackend for MockBackend {
        fn generate(
            &self,
            _prompt: &str,
            _model: &str,
            _system: &str,
            _temperature: f64,
            _max_tokens: usize,
        ) -> String {
            self.response.clone()
        }
    }

    #[test]
    fn test_propose_initial_no_backend() {
        let space = SearchSpace {
            fixed: {
                let mut m = HashMap::new();
                m.insert("intelligence.model".into(), serde_json::json!("qwen3:8b"));
                m
            },
            ..Default::default()
        };
        let opt = LLMOptimizer::new(space, "test".into());
        let config = opt.propose_initial();
        assert!(!config.trial_id.is_empty());
        assert_eq!(
            config.params.get("intelligence.model"),
            Some(&serde_json::json!("qwen3:8b"))
        );
    }

    #[test]
    fn test_propose_initial_with_backend() {
        let response = r#"Here is my proposal:

```json
{
  "params": {
    "intelligence.model": "qwen3:8b",
    "intelligence.temperature": 0.7,
    "agent.type": "orchestrator"
  },
  "reasoning": "Good starting point"
}
```"#;

        let space = SearchSpace::default();
        let opt = LLMOptimizer::with_backend(
            space,
            "test".into(),
            Box::new(MockBackend {
                response: response.into(),
            }),
        );

        let config = opt.propose_initial();
        assert_eq!(
            config.params.get("intelligence.model"),
            Some(&serde_json::json!("qwen3:8b"))
        );
        assert_eq!(
            config.params.get("agent.type"),
            Some(&serde_json::json!("orchestrator"))
        );
        assert_eq!(config.reasoning, "Good starting point");
    }

    #[test]
    fn test_propose_next_no_backend() {
        let space = SearchSpace::default();
        let opt = LLMOptimizer::new(space, "test".into());
        let config = opt.propose_next(&[]);
        assert!(!config.trial_id.is_empty());
    }

    #[test]
    fn test_parse_feedback_response_json_block() {
        let response = r#"```json
{
  "summary_text": "Good result overall",
  "failure_patterns": ["timeout"],
  "primitive_ratings": {"intelligence": "high"},
  "suggested_changes": ["lower temp"],
  "target_primitive": "intelligence"
}
```"#;
        let fb = parse_feedback_response(response);
        assert_eq!(fb.summary_text, "Good result overall");
        assert_eq!(fb.failure_patterns, vec!["timeout"]);
        assert_eq!(fb.target_primitive, "intelligence");
    }

    #[test]
    fn test_parse_feedback_response_fallback() {
        let response = "This is just plain text analysis.";
        let fb = parse_feedback_response(response);
        assert_eq!(fb.summary_text, "This is just plain text analysis.");
        assert!(fb.failure_patterns.is_empty());
    }

    #[test]
    fn test_extract_json_block() {
        let text = "Some text\n```json\n{\"key\": \"value\"}\n```\nMore text";
        let block = extract_json_block(text);
        assert!(block.is_some());
        assert_eq!(block.unwrap(), "{\"key\": \"value\"}");
    }

    #[test]
    fn test_extract_json_block_generic() {
        let text = "Some text\n```\n{\"key\": \"value\"}\n```\nMore text";
        let block = extract_json_block(text);
        assert!(block.is_some());
    }

    #[test]
    fn test_extract_json_block_none() {
        let text = "No code blocks here.";
        let block = extract_json_block(text);
        assert!(block.is_none());
    }

    #[test]
    fn test_format_history() {
        let trial = TrialResult {
            trial_id: "t1".into(),
            config: TrialConfig {
                trial_id: "t1".into(),
                params: {
                    let mut m = HashMap::new();
                    m.insert("intelligence.model".into(), serde_json::json!("qwen3:8b"));
                    m
                },
                reasoning: String::new(),
            },
            accuracy: 0.85,
            mean_latency_seconds: 1.0,
            total_cost_usd: 0.05,
            total_energy_joules: 10.0,
            total_tokens: 100,
            samples_evaluated: 10,
            analysis: "ok".into(),
            failure_modes: vec![],
            sample_scores: vec![],
            structured_feedback: None,
            per_benchmark: vec![],
        };

        let mut frontier = HashSet::new();
        frontier.insert("t1".into());

        let text = format_history(&[trial], Some(&frontier));
        assert!(text.contains("[FRONTIER]"));
        assert!(text.contains("0.8500"));
    }

    #[test]
    fn test_analyze_trial_no_backend() {
        let opt = LLMOptimizer::new(SearchSpace::default(), "test".into());
        let config = TrialConfig {
            trial_id: "t1".into(),
            params: HashMap::new(),
            reasoning: String::new(),
        };
        let fb = opt.analyze_trial(&config, 0.85, 1.0, 0.05);
        assert!(fb.summary_text.contains("0.85"));
    }

    #[test]
    fn test_propose_targeted_no_backend() {
        let opt = LLMOptimizer::new(SearchSpace::default(), "test".into());
        let base = TrialConfig {
            trial_id: "t1".into(),
            params: {
                let mut m = HashMap::new();
                m.insert("intelligence.model".into(), serde_json::json!("qwen3:8b"));
                m.insert("agent.type".into(), serde_json::json!("orchestrator"));
                m
            },
            reasoning: String::new(),
        };
        let config = opt.propose_targeted(&[], &base, "intelligence", None);
        // Should preserve base params
        assert_eq!(
            config.params.get("agent.type"),
            Some(&serde_json::json!("orchestrator"))
        );
    }

    #[test]
    fn test_propose_merge_no_backend() {
        let opt = LLMOptimizer::new(SearchSpace::default(), "test".into());
        let cand = TrialResult {
            trial_id: "t1".into(),
            config: TrialConfig {
                trial_id: "t1".into(),
                params: {
                    let mut m = HashMap::new();
                    m.insert("intelligence.model".into(), serde_json::json!("qwen3:8b"));
                    m
                },
                reasoning: String::new(),
            },
            accuracy: 0.9,
            mean_latency_seconds: 1.0,
            total_cost_usd: 0.05,
            total_energy_joules: 10.0,
            total_tokens: 100,
            samples_evaluated: 10,
            analysis: String::new(),
            failure_modes: vec![],
            sample_scores: vec![],
            structured_feedback: None,
            per_benchmark: vec![],
        };
        let config = opt.propose_merge(&[cand], &[], None);
        assert!(!config.trial_id.is_empty());
    }
}
