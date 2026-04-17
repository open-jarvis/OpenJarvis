//! TrainingDataMiner — extract supervised training pairs from trace data.
//!
//! Ported from Python `openjarvis.learning.training.data`.
//! File I/O stays in Python; this module provides pure data extraction.

use crate::trace_policy::classify_query;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

// ---------------------------------------------------------------------------
// Output types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SFTPair {
    pub input: String,
    pub output: String,
    pub query_class: String,
    pub model: String,
    pub feedback: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoutingRecommendation {
    pub query_class: String,
    pub best_model: String,
    pub avg_feedback: f64,
    pub sample_count: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentConfigPair {
    pub query_class: String,
    pub best_agent: String,
    pub best_tools: Vec<String>,
    pub avg_feedback: f64,
    pub sample_count: usize,
}

// ---------------------------------------------------------------------------
// Trace data passed from Python (no direct TraceStore dependency)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MinerTraceData {
    pub query: String,
    pub result: String,
    pub model: String,
    pub agent: String,
    pub outcome: String,
    pub feedback: Option<f64>,
    pub tool_names: Vec<String>,
}

// ---------------------------------------------------------------------------
// TrainingDataMiner
// ---------------------------------------------------------------------------

pub struct TrainingDataMiner {
    min_quality: f64,
    min_samples_per_class: usize,
}

impl TrainingDataMiner {
    pub fn new(min_quality: f64, min_samples_per_class: usize) -> Self {
        Self {
            min_quality,
            min_samples_per_class,
        }
    }

    fn quality_traces<'a>(&self, traces: &'a [MinerTraceData]) -> Vec<&'a MinerTraceData> {
        traces
            .iter()
            .filter(|t| {
                t.outcome == "success"
                    && t.feedback.is_some_and(|f| f >= self.min_quality)
            })
            .collect()
    }

    /// Extract SFT training pairs from high-quality traces, deduplicating on (input, output).
    pub fn extract_sft_pairs(&self, traces: &[MinerTraceData]) -> Vec<SFTPair> {
        let quality = self.quality_traces(traces);
        let mut seen: HashSet<(String, String)> = HashSet::new();
        let mut pairs = Vec::new();

        for t in quality {
            let key = (t.query.clone(), t.result.clone());
            if seen.contains(&key) {
                continue;
            }
            seen.insert(key);

            pairs.push(SFTPair {
                input: t.query.clone(),
                output: t.result.clone(),
                query_class: classify_query(&t.query).to_string(),
                model: t.model.clone(),
                feedback: t.feedback.unwrap_or(0.0),
            });
        }

        pairs
    }

    /// Extract per-query-class routing recommendations identifying the best model.
    pub fn extract_routing_pairs(&self, traces: &[MinerTraceData]) -> Vec<RoutingRecommendation> {
        let quality = self.quality_traces(traces);

        // Accumulate per (query_class, model) feedback scores
        let mut class_model_scores: HashMap<String, HashMap<String, Vec<f64>>> = HashMap::new();
        for t in &quality {
            let qc = classify_query(&t.query).to_string();
            let fb = t.feedback.unwrap_or(0.0);
            class_model_scores
                .entry(qc)
                .or_default()
                .entry(t.model.clone())
                .or_default()
                .push(fb);
        }

        let mut result = Vec::new();
        let mut classes: Vec<_> = class_model_scores.keys().cloned().collect();
        classes.sort();

        for qc in classes {
            let model_scores = &class_model_scores[&qc];
            let total_count: usize = model_scores.values().map(|v| v.len()).sum();
            if total_count < self.min_samples_per_class {
                continue;
            }

            let mut best_model = String::new();
            let mut best_avg: f64 = -1.0;
            for (model, scores) in model_scores {
                let avg = scores.iter().sum::<f64>() / scores.len() as f64;
                if avg > best_avg {
                    best_avg = avg;
                    best_model = model.clone();
                }
            }

            let all_scores: Vec<f64> = model_scores.values().flat_map(|v| v.iter().copied()).collect();
            let overall_avg = if all_scores.is_empty() {
                0.0
            } else {
                all_scores.iter().sum::<f64>() / all_scores.len() as f64
            };

            result.push(RoutingRecommendation {
                query_class: qc,
                best_model,
                avg_feedback: overall_avg,
                sample_count: total_count,
            });
        }

        result
    }

    /// Extract per-query-class agent and tool recommendations.
    pub fn extract_agent_config_pairs(&self, traces: &[MinerTraceData]) -> Vec<AgentConfigPair> {
        let quality = self.quality_traces(traces);

        let mut class_agent_scores: HashMap<String, HashMap<String, Vec<f64>>> = HashMap::new();
        let mut class_agent_tools: HashMap<String, HashMap<String, Vec<Vec<String>>>> = HashMap::new();

        for t in &quality {
            let qc = classify_query(&t.query).to_string();
            let fb = t.feedback.unwrap_or(0.0);

            class_agent_scores
                .entry(qc.clone())
                .or_default()
                .entry(t.agent.clone())
                .or_default()
                .push(fb);

            class_agent_tools
                .entry(qc)
                .or_default()
                .entry(t.agent.clone())
                .or_default()
                .push(t.tool_names.clone());
        }

        let mut result = Vec::new();
        let mut classes: Vec<_> = class_agent_scores.keys().cloned().collect();
        classes.sort();

        for qc in classes {
            let agent_scores = &class_agent_scores[&qc];
            let total_count: usize = agent_scores.values().map(|v| v.len()).sum();
            if total_count < self.min_samples_per_class {
                continue;
            }

            let mut best_agent = String::new();
            let mut best_avg: f64 = -1.0;
            for (agent, scores) in agent_scores {
                let avg = scores.iter().sum::<f64>() / scores.len() as f64;
                if avg > best_avg {
                    best_avg = avg;
                    best_agent = agent.clone();
                }
            }

            // Collect tool frequency for best agent
            let mut tool_freq: HashMap<String, usize> = HashMap::new();
            if let Some(agent_tools) = class_agent_tools.get(&qc) {
                if let Some(tool_lists) = agent_tools.get(&best_agent) {
                    for tool_list in tool_lists {
                        for tool in tool_list {
                            *tool_freq.entry(tool.clone()).or_default() += 1;
                        }
                    }
                }
            }
            let mut ranked: Vec<_> = tool_freq.into_iter().collect();
            ranked.sort_by_key(|r| std::cmp::Reverse(r.1));
            let best_tools: Vec<String> = ranked.into_iter().map(|(name, _)| name).collect();

            let all_scores: Vec<f64> = agent_scores.values().flat_map(|v| v.iter().copied()).collect();
            let overall_avg = if all_scores.is_empty() {
                0.0
            } else {
                all_scores.iter().sum::<f64>() / all_scores.len() as f64
            };

            result.push(AgentConfigPair {
                query_class: qc,
                best_agent,
                best_tools,
                avg_feedback: overall_avg,
                sample_count: total_count,
            });
        }

        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_trace(
        query: &str,
        result: &str,
        model: &str,
        agent: &str,
        outcome: &str,
        feedback: Option<f64>,
        tools: &[&str],
    ) -> MinerTraceData {
        MinerTraceData {
            query: query.into(),
            result: result.into(),
            model: model.into(),
            agent: agent.into(),
            outcome: outcome.into(),
            feedback,
            tool_names: tools.iter().map(|s| s.to_string()).collect(),
        }
    }

    #[test]
    fn test_empty_traces() {
        let miner = TrainingDataMiner::new(0.7, 1);
        assert!(miner.extract_sft_pairs(&[]).is_empty());
        assert!(miner.extract_routing_pairs(&[]).is_empty());
        assert!(miner.extract_agent_config_pairs(&[]).is_empty());
    }

    #[test]
    fn test_sft_pairs_deduplication() {
        let miner = TrainingDataMiner::new(0.7, 1);
        let traces = vec![
            make_trace("q1", "r1", "m1", "a1", "success", Some(0.9), &[]),
            make_trace("q1", "r1", "m1", "a1", "success", Some(0.8), &[]),
            make_trace("q2", "r2", "m1", "a1", "success", Some(0.9), &[]),
        ];
        let pairs = miner.extract_sft_pairs(&traces);
        assert_eq!(pairs.len(), 2, "duplicate (q1,r1) should be collapsed");
    }

    #[test]
    fn test_sft_pairs_quality_filter() {
        let miner = TrainingDataMiner::new(0.7, 1);
        let traces = vec![
            make_trace("q1", "r1", "m1", "a1", "success", Some(0.9), &[]),
            make_trace("q2", "r2", "m1", "a1", "success", Some(0.3), &[]),
            make_trace("q3", "r3", "m1", "a1", "failure", Some(0.9), &[]),
            make_trace("q4", "r4", "m1", "a1", "success", None, &[]),
        ];
        let pairs = miner.extract_sft_pairs(&traces);
        assert_eq!(pairs.len(), 1, "only q1 passes quality filter");
        assert_eq!(pairs[0].input, "q1");
    }

    #[test]
    fn test_routing_pairs() {
        let miner = TrainingDataMiner::new(0.7, 1);
        let traces = vec![
            make_trace("Hello", "r1", "fast_model", "a1", "success", Some(0.9), &[]),
            make_trace("Hi", "r2", "fast_model", "a1", "success", Some(0.8), &[]),
            make_trace("Hey", "r3", "slow_model", "a1", "success", Some(0.7), &[]),
        ];
        let recs = miner.extract_routing_pairs(&traces);
        assert!(!recs.is_empty());
        let rec = &recs[0];
        assert_eq!(rec.query_class, "short");
        assert_eq!(rec.best_model, "fast_model");
        assert_eq!(rec.sample_count, 3);
    }

    #[test]
    fn test_agent_config_pairs() {
        let miner = TrainingDataMiner::new(0.7, 1);
        let traces = vec![
            make_trace("Hello", "r1", "m1", "simple", "success", Some(0.9), &["calc"]),
            make_trace("Hi", "r2", "m1", "simple", "success", Some(0.8), &["calc", "think"]),
            make_trace("Hey", "r3", "m1", "orch", "success", Some(0.7), &["think"]),
        ];
        let pairs = miner.extract_agent_config_pairs(&traces);
        assert!(!pairs.is_empty());
        let pair = &pairs[0];
        assert_eq!(pair.best_agent, "simple");
        assert!(!pair.best_tools.is_empty());
        assert!(pair.best_tools.contains(&"calc".to_string()));
    }

    #[test]
    fn test_min_samples_per_class() {
        let miner = TrainingDataMiner::new(0.7, 5);
        let traces = vec![
            make_trace("Hello", "r1", "m1", "a1", "success", Some(0.9), &[]),
            make_trace("Hi", "r2", "m1", "a1", "success", Some(0.8), &[]),
        ];
        let recs = miner.extract_routing_pairs(&traces);
        assert!(recs.is_empty(), "only 2 samples, need 5");
    }
}
