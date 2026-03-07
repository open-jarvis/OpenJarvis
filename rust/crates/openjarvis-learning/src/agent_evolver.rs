//! AgentConfigEvolver — analyze traces to produce agent configuration recommendations.
//!
//! Ported from Python `openjarvis.learning.agent_evolver`.
//! File I/O (TOML writing, versioning, rollback) stays in Python;
//! this module provides pure analysis and scoring logic.

use crate::trace_policy::classify_query;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ---------------------------------------------------------------------------
// Scoring accumulators
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Default)]
pub struct ToolScore {
    pub count: u32,
    pub successes: u32,
    pub feedback_sum: f64,
}

impl ToolScore {
    /// Weighted score: 40% success rate + 40% avg feedback + 20% log-frequency.
    pub fn composite_score(&self) -> f64 {
        if self.count == 0 {
            return 0.0;
        }
        let sr = self.successes as f64 / self.count as f64;
        let fb = self.feedback_sum / self.count as f64;
        let freq_bonus = ((self.count as f64) + 1.0).ln() / 10.0;
        0.4 * sr + 0.4 * fb + 0.2 * freq_bonus.min(1.0)
    }
}

#[derive(Debug, Clone, Default)]
pub struct AgentScore {
    pub count: u32,
    pub successes: u32,
    pub feedback_sum: f64,
}

impl AgentScore {
    /// Weighted score: 60% success rate + 40% avg feedback.
    pub fn composite_score(&self) -> f64 {
        if self.count == 0 {
            return 0.0;
        }
        let sr = self.successes as f64 / self.count as f64;
        let fb = self.feedback_sum / self.count as f64;
        0.6 * sr + 0.4 * fb
    }
}

// ---------------------------------------------------------------------------
// Recommendation output
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentConfigRecommendation {
    pub query_class: String,
    pub recommended_tools: Vec<String>,
    pub recommended_agent: String,
    pub recommended_max_turns: usize,
    pub sample_count: usize,
}

// ---------------------------------------------------------------------------
// Trace data passed from Python (no direct TraceStore dependency)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvolutionTraceData {
    pub query: String,
    pub outcome: String,
    pub feedback: Option<f64>,
    pub agent: String,
    pub tool_calls: Vec<String>,
}

// ---------------------------------------------------------------------------
// AgentConfigEvolver
// ---------------------------------------------------------------------------

pub struct AgentConfigEvolver {
    min_quality: f64,
}

impl AgentConfigEvolver {
    pub fn new(min_quality: f64) -> Self {
        Self { min_quality }
    }

    pub fn min_quality(&self) -> f64 {
        self.min_quality
    }

    /// Analyze traces and return per-query-class recommendations.
    pub fn analyze(&self, traces: &[EvolutionTraceData]) -> Vec<AgentConfigRecommendation> {
        if traces.is_empty() {
            return Vec::new();
        }

        let mut groups: HashMap<&str, Vec<&EvolutionTraceData>> = HashMap::new();
        for trace in traces {
            let qclass = classify_query(&trace.query);
            groups.entry(qclass).or_default().push(trace);
        }

        let mut recommendations = Vec::new();
        let mut classes: Vec<_> = groups.keys().copied().collect();
        classes.sort();

        for qclass in classes {
            let class_traces = &groups[qclass];
            if let Some(rec) = self.analyze_class(qclass, class_traces) {
                recommendations.push(rec);
            }
        }

        recommendations
    }

    fn analyze_class(
        &self,
        qclass: &str,
        traces: &[&EvolutionTraceData],
    ) -> Option<AgentConfigRecommendation> {
        let mut tool_scores: HashMap<&str, ToolScore> = HashMap::new();
        let mut agent_scores: HashMap<&str, AgentScore> = HashMap::new();
        let mut turn_counts: Vec<usize> = Vec::new();

        for trace in traces {
            let feedback = trace.feedback.unwrap_or(0.0);
            let is_success = trace.outcome == "success";

            turn_counts.push(trace.tool_calls.len());

            for tool_name in &trace.tool_calls {
                let ts = tool_scores.entry(tool_name.as_str()).or_default();
                ts.count += 1;
                ts.feedback_sum += feedback;
                if is_success {
                    ts.successes += 1;
                }
            }

            if !trace.agent.is_empty() {
                let ag = agent_scores.entry(trace.agent.as_str()).or_default();
                ag.count += 1;
                ag.feedback_sum += feedback;
                if is_success {
                    ag.successes += 1;
                }
            }
        }

        if agent_scores.is_empty() {
            return None;
        }

        let best_agent = agent_scores
            .iter()
            .max_by(|a, b| a.1.composite_score().partial_cmp(&b.1.composite_score()).unwrap())
            .map(|(name, _)| name.to_string())?;

        let mut ranked_tools: Vec<_> = tool_scores.iter().collect();
        ranked_tools.sort_by(|a, b| b.1.composite_score().partial_cmp(&a.1.composite_score()).unwrap());
        let recommended_tools: Vec<String> = ranked_tools.iter().map(|(name, _)| name.to_string()).collect();

        let recommended_max_turns = if turn_counts.is_empty() {
            10
        } else {
            let mut sorted = turn_counts.clone();
            sorted.sort();
            let p75_idx = (sorted.len() as f64 * 0.75) as usize;
            let p75 = sorted[p75_idx.min(sorted.len() - 1)];
            (p75 + 2).max(5)
        };

        Some(AgentConfigRecommendation {
            query_class: qclass.to_string(),
            recommended_tools,
            recommended_agent: best_agent,
            recommended_max_turns,
            sample_count: traces.len(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_trace(
        query: &str,
        agent: &str,
        outcome: &str,
        feedback: Option<f64>,
        tools: &[&str],
    ) -> EvolutionTraceData {
        EvolutionTraceData {
            query: query.into(),
            outcome: outcome.into(),
            feedback,
            agent: agent.into(),
            tool_calls: tools.iter().map(|s| s.to_string()).collect(),
        }
    }

    #[test]
    fn test_empty_traces() {
        let evolver = AgentConfigEvolver::new(0.5);
        let recs = evolver.analyze(&[]);
        assert!(recs.is_empty());
    }

    #[test]
    fn test_analyze_produces_recommendations() {
        let evolver = AgentConfigEvolver::new(0.5);
        let traces = vec![
            make_trace("Hello", "simple", "success", Some(0.9), &["calculator"]),
            make_trace("Hi there", "simple", "success", Some(0.8), &["calculator", "think"]),
            make_trace("Hey", "orchestrator", "failure", Some(0.3), &["think"]),
        ];
        let recs = evolver.analyze(&traces);
        assert!(!recs.is_empty());

        let rec = &recs[0];
        assert_eq!(rec.query_class, "short");
        assert_eq!(rec.recommended_agent, "simple");
        assert!(rec.recommended_max_turns >= 5);
        assert!(!rec.recommended_tools.is_empty());
    }

    #[test]
    fn test_tool_score_composite() {
        let ts = ToolScore {
            count: 10,
            successes: 8,
            feedback_sum: 7.0,
        };
        let score = ts.composite_score();
        assert!(score > 0.0);
        assert!(score <= 1.0);
    }

    #[test]
    fn test_agent_score_composite() {
        let ag = AgentScore {
            count: 10,
            successes: 10,
            feedback_sum: 10.0,
        };
        let score = ag.composite_score();
        assert!((score - 1.0).abs() < 1e-9);
    }

    #[test]
    fn test_no_agent_returns_none() {
        let evolver = AgentConfigEvolver::new(0.5);
        let traces = vec![EvolutionTraceData {
            query: "test query".into(),
            outcome: "success".into(),
            feedback: Some(0.9),
            agent: String::new(),
            tool_calls: vec!["calc".into()],
        }];
        let recs = evolver.analyze(&traces);
        assert!(recs.is_empty());
    }

    #[test]
    fn test_multiple_query_classes() {
        let evolver = AgentConfigEvolver::new(0.5);
        let traces = vec![
            make_trace("Hello", "simple", "success", Some(0.9), &[]),
            make_trace("def foo(): pass", "orchestrator", "success", Some(0.8), &["calculator"]),
            make_trace("solve x^2 = 4 for the equation's roots", "simple", "success", Some(0.7), &["think"]),
        ];
        let recs = evolver.analyze(&traces);
        assert!(recs.len() >= 2, "should have recommendations for multiple classes");
    }
}
