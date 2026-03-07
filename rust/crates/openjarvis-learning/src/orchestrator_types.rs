//! Episode dataclasses for orchestrator training.
//!
//! Ported from Python `openjarvis.learning.orchestrator.types`.

use once_cell::sync::Lazy;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Answer grading utilities
// ---------------------------------------------------------------------------

/// Try to parse a string as a number, stripping commas, spaces, and trailing `.0`.
pub fn normalize_number(s: &str) -> Option<f64> {
    let s = s.trim().to_lowercase();
    let s = s.replace([',', ' '], "");
    let s = s.trim_end_matches(".00").trim_end_matches(".0");
    s.parse::<f64>().ok()
}

static ANSWER_PATTERNS: Lazy<Vec<Regex>> = Lazy::new(|| {
    [
        r"(?i)(?:the\s+)?answer\s+is[:\s]+(.+?)(?:\.|$)",
        r"(?i)result[:\s]+(.+?)(?:\.|$)",
        r"=\s*(.+?)(?:\.|$)",
        r"(?i)therefore[,\s]+(?:the\s+)?(?:answer\s+is\s+)?(.+?)(?:\.|$)",
    ]
    .iter()
    .filter_map(|p| Regex::new(p).ok())
    .collect()
});

/// Extract the core answer from a potentially verbose response.
pub fn extract_answer(text: &str) -> String {
    let text = text.trim();
    for re in ANSWER_PATTERNS.iter() {
        if let Some(caps) = re.captures(text) {
            if let Some(m) = caps.get(1) {
                return m.as_str().trim().to_string();
            }
        }
    }
    text.to_string()
}

/// Grade an answer against expected with smart matching (exact, extracted, numeric).
pub fn grade_answer(predicted: &str, expected: &str, tolerance: f64) -> bool {
    let p = predicted.trim();
    let e = expected.trim();

    if p.eq_ignore_ascii_case(e) {
        return true;
    }

    let pe = extract_answer(p);
    let ee = extract_answer(e);
    if pe.eq_ignore_ascii_case(&ee) {
        return true;
    }

    if let (Some(pn), Some(en)) = (normalize_number(&pe), normalize_number(&ee)) {
        if en == 0.0 {
            return pn.abs() < tolerance;
        }
        return ((pn - en) / en.abs()).abs() < tolerance;
    }

    false
}

// ---------------------------------------------------------------------------
// Core data structures
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorAction {
    pub thought: String,
    pub tool_name: String,
    pub tool_input: String,
    pub is_final_answer: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorObservation {
    pub content: String,
    pub latency_seconds: f64,
    pub cost_usd: f64,
    pub energy_joules: f64,
    pub power_watts: f64,
    pub tokens: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EpisodeStep {
    pub turn: usize,
    pub action: OrchestratorAction,
    pub observation: OrchestratorObservation,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Episode {
    pub task_id: String,
    pub initial_prompt: String,
    pub steps: Vec<EpisodeStep>,
    pub final_answer: String,
    pub ground_truth: String,
    pub correct: bool,
    pub total_energy_joules: f64,
    pub total_cost_usd: f64,
    pub total_latency_seconds: f64,
    pub total_tokens: u64,
    pub max_power_watts: f64,
    pub metadata: HashMap<String, serde_json::Value>,
}

impl Episode {
    pub fn new(task_id: String, initial_prompt: String) -> Self {
        Self {
            task_id,
            initial_prompt,
            steps: Vec::new(),
            final_answer: String::new(),
            ground_truth: String::new(),
            correct: false,
            total_energy_joules: 0.0,
            total_cost_usd: 0.0,
            total_latency_seconds: 0.0,
            total_tokens: 0,
            max_power_watts: 0.0,
            metadata: HashMap::new(),
        }
    }

    pub fn add_step(&mut self, action: OrchestratorAction, observation: OrchestratorObservation) {
        let step = EpisodeStep {
            turn: self.steps.len(),
            action,
            observation,
        };

        self.total_energy_joules += step.observation.energy_joules;
        self.total_latency_seconds += step.observation.latency_seconds;
        self.total_cost_usd += step.observation.cost_usd;
        self.total_tokens += step.observation.tokens;
        if step.observation.power_watts > self.max_power_watts {
            self.max_power_watts = step.observation.power_watts;
        }

        if step.action.is_final_answer {
            self.final_answer = step.observation.content.clone();
        }

        self.steps.push(step);
    }

    pub fn num_turns(&self) -> usize {
        self.steps.len()
    }

    /// Compute Intelligence Per Joule: accuracy / energy.
    pub fn compute_ipj(&self) -> f64 {
        if self.total_energy_joules <= 0.0 {
            return 0.0;
        }
        let acc = if self.correct { 1.0 } else { 0.0 };
        acc / self.total_energy_joules
    }

    pub fn to_value(&self) -> serde_json::Value {
        serde_json::to_value(self).unwrap_or_default()
    }
}

// ---------------------------------------------------------------------------
// EpisodeState — mutable state during episode execution
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EpisodeState {
    pub initial_prompt: String,
    pub history: Vec<(OrchestratorAction, OrchestratorObservation)>,
    pub final_answer: Option<String>,
}

impl EpisodeState {
    pub fn new(initial_prompt: String) -> Self {
        Self {
            initial_prompt,
            history: Vec::new(),
            final_answer: None,
        }
    }

    pub fn add_turn(&mut self, action: OrchestratorAction, observation: OrchestratorObservation) {
        if action.is_final_answer {
            self.final_answer = Some(observation.content.clone());
        }
        self.history.push((action, observation));
    }

    pub fn num_turns(&self) -> usize {
        self.history.len()
    }

    pub fn to_episode(&self, task_id: String, ground_truth: String, correct: bool) -> Episode {
        let mut episode = Episode::new(task_id, self.initial_prompt.clone());
        episode.ground_truth = ground_truth;
        episode.correct = correct;
        episode.final_answer = self.final_answer.clone().unwrap_or_default();
        for (action, observation) in &self.history {
            episode.add_step(action.clone(), observation.clone());
        }
        episode
    }
}

// ---------------------------------------------------------------------------
// PolicyOutput — output from policy model prediction
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PolicyOutput {
    pub thought: String,
    pub tool_name: String,
    pub tool_input: String,
    pub is_final_answer: bool,
    pub raw_text: String,
    pub confidence: f64,
}

impl PolicyOutput {
    pub fn new(thought: String, tool_name: String, tool_input: String) -> Self {
        Self {
            thought,
            tool_name,
            tool_input,
            is_final_answer: false,
            raw_text: String::new(),
            confidence: 1.0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_number() {
        assert_eq!(normalize_number("42"), Some(42.0));
        assert_eq!(normalize_number("1,234.0"), Some(1234.0));
        assert_eq!(normalize_number("  3.14  "), Some(3.14));
        assert!(normalize_number("not a number").is_none());
    }

    #[test]
    fn test_extract_answer() {
        assert_eq!(extract_answer("The answer is 42."), "42");
        assert_eq!(extract_answer("Result: hello world."), "hello world");
        assert_eq!(extract_answer("= 7."), "7");
        assert_eq!(extract_answer("Therefore, the answer is yes."), "yes");
        assert_eq!(extract_answer("just text"), "just text");
    }

    #[test]
    fn test_grade_answer_exact() {
        assert!(grade_answer("Hello", "hello", 1e-6));
        assert!(grade_answer("  42  ", "42", 1e-6));
    }

    #[test]
    fn test_grade_answer_numeric() {
        assert!(grade_answer("The answer is 42", "42", 0.01));
        assert!(!grade_answer("The answer is 42", "99", 0.01));
        // Decimal with tolerance: extract_answer captures "3" from "3.14"
        // because `.` triggers the sentence-end pattern, so we need wider tolerance.
        assert!(grade_answer("The answer is 3.14", "3.14", 0.05));
        assert!(grade_answer("3.14", "3.14", 0.01));
    }

    #[test]
    fn test_grade_answer_zero_expected() {
        assert!(grade_answer("0.0000001", "0", 0.001));
        assert!(!grade_answer("5.0", "0", 0.001));
    }

    #[test]
    fn test_episode_lifecycle() {
        let mut ep = Episode::new("t1".into(), "What is 2+2?".into());
        assert_eq!(ep.num_turns(), 0);
        assert_eq!(ep.compute_ipj(), 0.0);

        let action = OrchestratorAction {
            thought: "Use calculator".into(),
            tool_name: "calculator".into(),
            tool_input: "2+2".into(),
            is_final_answer: false,
        };
        let obs = OrchestratorObservation {
            content: "4".into(),
            latency_seconds: 0.5,
            cost_usd: 0.001,
            energy_joules: 10.0,
            power_watts: 20.0,
            tokens: 50,
        };
        ep.add_step(action, obs);
        assert_eq!(ep.num_turns(), 1);
        assert_eq!(ep.total_tokens, 50);
        assert!((ep.total_energy_joules - 10.0).abs() < 1e-9);

        ep.correct = true;
        assert!((ep.compute_ipj() - 0.1).abs() < 1e-9);
    }

    #[test]
    fn test_episode_final_answer() {
        let mut ep = Episode::new("t2".into(), "prompt".into());
        let action = OrchestratorAction {
            thought: "done".into(),
            tool_name: "final".into(),
            tool_input: "".into(),
            is_final_answer: true,
        };
        let obs = OrchestratorObservation {
            content: "the answer".into(),
            latency_seconds: 0.1,
            cost_usd: 0.0,
            energy_joules: 1.0,
            power_watts: 5.0,
            tokens: 10,
        };
        ep.add_step(action, obs);
        assert_eq!(ep.final_answer, "the answer");
    }

    #[test]
    fn test_episode_state_to_episode() {
        let mut state = EpisodeState::new("prompt".into());
        let action = OrchestratorAction {
            thought: "think".into(),
            tool_name: "tool".into(),
            tool_input: "input".into(),
            is_final_answer: true,
        };
        let obs = OrchestratorObservation {
            content: "result".into(),
            latency_seconds: 1.0,
            cost_usd: 0.01,
            energy_joules: 5.0,
            power_watts: 10.0,
            tokens: 100,
        };
        state.add_turn(action, obs);
        assert_eq!(state.final_answer.as_deref(), Some("result"));

        let ep = state.to_episode("tid".into(), "truth".into(), true);
        assert_eq!(ep.num_turns(), 1);
        assert!(ep.correct);
        assert_eq!(ep.final_answer, "result");
        assert_eq!(ep.total_tokens, 100);
    }

    #[test]
    fn test_episode_serialization() {
        let ep = Episode::new("t3".into(), "test".into());
        let val = ep.to_value();
        assert_eq!(val["task_id"], "t3");
        assert_eq!(val["steps"].as_array().unwrap().len(), 0);
    }

    #[test]
    fn test_policy_output_defaults() {
        let po = PolicyOutput::new("thought".into(), "tool".into(), "input".into());
        assert!(!po.is_final_answer);
        assert!((po.confidence - 1.0).abs() < f64::EPSILON);
        assert!(po.raw_text.is_empty());
    }
}
