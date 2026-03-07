//! Skill discovery — mine recurring tool sequences from traces.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiscoveredSkill {
    pub name: String,
    pub description: String,
    pub tool_sequence: Vec<String>,
    pub frequency: usize,
    pub avg_outcome: f64,
    pub example_inputs: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct SkillDiscovery {
    min_freq: usize,
    min_len: usize,
    max_len: usize,
    min_outcome: f64,
    discovered: Vec<DiscoveredSkill>,
}

/// Accumulator for a candidate subsequence during analysis.
struct SeqAccum {
    outcomes: Vec<f64>,
    inputs: Vec<String>,
}

impl SkillDiscovery {
    pub fn new(
        min_frequency: usize,
        min_sequence_length: usize,
        max_sequence_length: usize,
        min_outcome: f64,
    ) -> Self {
        Self {
            min_freq: min_frequency,
            min_len: min_sequence_length,
            max_len: max_sequence_length,
            min_outcome,
            discovered: Vec::new(),
        }
    }

    /// Analyze traces for recurring tool sequences.
    ///
    /// Each trace entry is `(tool_calls, outcome_score, query)`.
    /// Returns a slice of discovered skills meeting all thresholds.
    pub fn analyze(&mut self, traces: &[(Vec<String>, f64, String)]) -> &[DiscoveredSkill] {
        let mut accums: HashMap<Vec<String>, SeqAccum> = HashMap::new();

        for (tool_calls, outcome, query) in traces {
            if tool_calls.len() < self.min_len {
                continue;
            }
            let upper = (self.max_len + 1).min(tool_calls.len() + 1);
            for length in self.min_len..upper {
                for start in 0..=(tool_calls.len() - length) {
                    let seq = tool_calls[start..start + length].to_vec();
                    let acc = accums.entry(seq).or_insert_with(|| SeqAccum {
                        outcomes: Vec::new(),
                        inputs: Vec::new(),
                    });
                    acc.outcomes.push(*outcome);
                    if !query.is_empty() && acc.inputs.len() < 3 {
                        acc.inputs.push(query.clone());
                    }
                }
            }
        }

        let mut discovered: Vec<DiscoveredSkill> = Vec::new();
        for (seq, acc) in accums {
            let freq = acc.outcomes.len();
            let avg = acc.outcomes.iter().sum::<f64>() / freq as f64;
            if freq >= self.min_freq && avg >= self.min_outcome {
                let name = seq.join("_");
                let desc = format!(
                    "Auto-discovered skill: {} (seen {} times)",
                    seq.join(" -> "),
                    freq,
                );
                discovered.push(DiscoveredSkill {
                    name,
                    description: desc,
                    tool_sequence: seq,
                    frequency: freq,
                    avg_outcome: avg,
                    example_inputs: acc.inputs,
                });
            }
        }

        discovered.sort_by(|a, b| {
            let score_a = a.frequency as f64 * a.avg_outcome;
            let score_b = b.frequency as f64 * b.avg_outcome;
            score_b
                .partial_cmp(&score_a)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        self.discovered = discovered;
        &self.discovered
    }

    pub fn discovered_skills(&self) -> &[DiscoveredSkill] {
        &self.discovered
    }

    /// Convert discovered skills to TOML-compatible manifest values.
    pub fn to_manifests(&self) -> Vec<serde_json::Value> {
        self.discovered
            .iter()
            .map(|skill| {
                serde_json::json!({
                    "name": skill.name,
                    "description": skill.description,
                    "steps": skill.tool_sequence.iter()
                        .map(|t| serde_json::json!({"tool": t, "params": {}}))
                        .collect::<Vec<_>>(),
                    "metadata": {
                        "auto_discovered": true,
                        "frequency": skill.frequency,
                        "avg_outcome": skill.avg_outcome,
                    },
                })
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_traces() -> Vec<(Vec<String>, f64, String)> {
        vec![
            (
                vec!["web_search".into(), "file_write".into()],
                0.8,
                "research topic A".into(),
            ),
            (
                vec!["web_search".into(), "file_write".into()],
                0.9,
                "research topic B".into(),
            ),
            (
                vec!["web_search".into(), "file_write".into()],
                0.7,
                "research topic C".into(),
            ),
            (
                vec![
                    "file_read".into(),
                    "calculator".into(),
                    "file_write".into(),
                ],
                0.85,
                "compute stats".into(),
            ),
        ]
    }

    #[test]
    fn test_discovers_frequent_sequence() {
        let mut sd = SkillDiscovery::new(3, 2, 4, 0.5);
        let traces = sample_traces();
        let skills = sd.analyze(&traces);
        assert!(!skills.is_empty());
        let ws_fw = skills
            .iter()
            .find(|s| s.tool_sequence == vec!["web_search", "file_write"]);
        assert!(ws_fw.is_some(), "should discover web_search -> file_write");
        assert_eq!(ws_fw.unwrap().frequency, 3);
    }

    #[test]
    fn test_filters_below_min_freq() {
        let mut sd = SkillDiscovery::new(10, 2, 4, 0.5);
        let traces = sample_traces();
        let skills = sd.analyze(&traces);
        assert!(skills.is_empty(), "nothing should meet freq >= 10");
    }

    #[test]
    fn test_to_manifests() {
        let mut sd = SkillDiscovery::new(3, 2, 4, 0.5);
        let traces = sample_traces();
        sd.analyze(&traces);
        let manifests = sd.to_manifests();
        assert!(!manifests.is_empty());
        assert!(manifests[0].get("name").is_some());
        assert!(manifests[0].get("steps").is_some());
    }
}
