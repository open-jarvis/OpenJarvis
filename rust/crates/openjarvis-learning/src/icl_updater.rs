//! ICL (in-context learning) example updater with versioning and rollback.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// An in-context learning example with version tracking.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ICLExample {
    pub query: String,
    pub response: String,
    pub outcome: f64,
    pub metadata: HashMap<String, String>,
    pub version: u32,
}

/// A discovered tool-call sequence from traces.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DiscoveredSequence {
    pub sequence: String,
    pub tools: Vec<String>,
    pub occurrences: usize,
}

/// Maintains a versioned database of ICL examples and discovers
/// recurring tool-call skills from traces.
#[derive(Debug, Clone)]
pub struct ICLUpdaterPolicy {
    min_score: f64,
    max_examples: usize,
    min_skill_occurrences: usize,
    example_db: Vec<ICLExample>,
    version: u32,
    discovered_skills: Vec<DiscoveredSequence>,
}

impl ICLUpdaterPolicy {
    pub fn new(min_score: f64, max_examples: usize, min_skill_occurrences: usize) -> Self {
        Self {
            min_score,
            max_examples,
            min_skill_occurrences,
            example_db: Vec::new(),
            version: 0,
            discovered_skills: Vec::new(),
        }
    }

    /// Add an ICL example if it meets the quality threshold.
    ///
    /// Returns `true` if the example was accepted.
    pub fn add_example(
        &mut self,
        query: String,
        response: String,
        outcome: f64,
        metadata: HashMap<String, String>,
    ) -> bool {
        if outcome < self.min_score {
            return false;
        }

        self.version += 1;
        let entry = ICLExample {
            query,
            response,
            outcome,
            metadata,
            version: self.version,
        };
        self.example_db.push(entry);

        if self.example_db.len() > self.max_examples {
            let start = self.example_db.len() - self.max_examples;
            self.example_db = self.example_db[start..].to_vec();
        }

        true
    }

    /// Remove all examples added after the given version.
    pub fn rollback(&mut self, version: u32) {
        self.example_db.retain(|ex| ex.version <= version);
        self.version = version;
    }

    /// Retrieve the best examples, optionally filtered by query substring.
    ///
    /// Results are sorted by outcome descending and capped at `top_k`.
    pub fn get_examples(&self, query_class: &str, top_k: usize) -> Vec<ICLExample> {
        let pool: Vec<&ICLExample> = if query_class.is_empty() {
            self.example_db.iter().collect()
        } else {
            let lc = query_class.to_lowercase();
            self.example_db
                .iter()
                .filter(|ex| ex.query.to_lowercase().contains(&lc))
                .collect()
        };

        let mut ranked: Vec<ICLExample> = pool.into_iter().cloned().collect();
        ranked.sort_by(|a, b| {
            b.outcome
                .partial_cmp(&a.outcome)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        ranked.truncate(top_k);
        ranked
    }

    /// Discover recurring tool-call sequences from traces.
    ///
    /// Each trace entry is a list of tool names used in order.
    pub fn discover_skills(&mut self, tool_sequences: &[Vec<String>]) -> &[DiscoveredSequence] {
        let mut seq_counts: HashMap<String, (Vec<String>, usize)> = HashMap::new();

        for seq in tool_sequences {
            if seq.len() < 2 {
                continue;
            }
            let upper = (seq.len() + 1).min(5);
            for length in 2..upper {
                for start in 0..=(seq.len() - length) {
                    let sub = &seq[start..start + length];
                    let key = sub.join(" -> ");
                    let entry = seq_counts
                        .entry(key.clone())
                        .or_insert_with(|| (sub.to_vec(), 0));
                    entry.1 += 1;
                }
            }
        }

        let mut skills: Vec<DiscoveredSequence> = Vec::new();
        for (key, (tools, count)) in seq_counts {
            if count >= self.min_skill_occurrences {
                skills.push(DiscoveredSequence {
                    sequence: key,
                    tools,
                    occurrences: count,
                });
            }
        }

        skills.sort_by_key(|s| std::cmp::Reverse(s.occurrences));
        self.discovered_skills = skills;
        &self.discovered_skills
    }

    pub fn version(&self) -> u32 {
        self.version
    }

    pub fn example_db(&self) -> &[ICLExample] {
        &self.example_db
    }

    pub fn discovered(&self) -> &[DiscoveredSequence] {
        &self.discovered_skills
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_add_example_quality_gate() {
        let mut policy = ICLUpdaterPolicy::new(0.7, 20, 3);
        assert!(!policy.add_example(
            "q".into(), "r".into(), 0.3, HashMap::new(),
        ));
        assert!(policy.add_example(
            "q".into(), "r".into(), 0.9, HashMap::new(),
        ));
        assert_eq!(policy.example_db().len(), 1);
        assert_eq!(policy.version(), 1);
    }

    #[test]
    fn test_rollback() {
        let mut policy = ICLUpdaterPolicy::new(0.5, 20, 3);
        policy.add_example("q1".into(), "r1".into(), 0.8, HashMap::new());
        policy.add_example("q2".into(), "r2".into(), 0.9, HashMap::new());
        policy.add_example("q3".into(), "r3".into(), 0.7, HashMap::new());
        assert_eq!(policy.version(), 3);

        policy.rollback(1);
        assert_eq!(policy.version(), 1);
        assert_eq!(policy.example_db().len(), 1);
        assert_eq!(policy.example_db()[0].query, "q1");
    }

    #[test]
    fn test_get_examples_filtered() {
        let mut policy = ICLUpdaterPolicy::new(0.5, 20, 3);
        policy.add_example("def foo():".into(), "r1".into(), 0.9, HashMap::new());
        policy.add_example("solve x=1".into(), "r2".into(), 0.8, HashMap::new());
        policy.add_example("def bar():".into(), "r3".into(), 0.95, HashMap::new());

        let code_examples = policy.get_examples("def", 10);
        assert_eq!(code_examples.len(), 2);
        assert!(
            code_examples[0].outcome >= code_examples[1].outcome,
            "should be sorted by outcome desc"
        );
    }

    #[test]
    fn test_max_examples_trim() {
        let mut policy = ICLUpdaterPolicy::new(0.0, 3, 3);
        for i in 0..5 {
            policy.add_example(format!("q{}", i), format!("r{}", i), 0.5, HashMap::new());
        }
        assert_eq!(policy.example_db().len(), 3);
        assert_eq!(policy.example_db()[0].query, "q2");
    }

    #[test]
    fn test_discover_skills() {
        let mut policy = ICLUpdaterPolicy::new(0.5, 20, 2);
        let seqs = vec![
            vec!["search".into(), "write".into()],
            vec!["search".into(), "write".into()],
            vec!["search".into(), "write".into()],
            vec!["read".into(), "calc".into()],
        ];
        let skills = policy.discover_skills(&seqs);
        assert!(!skills.is_empty());
        let sw = skills.iter().find(|s| s.tools == vec!["search", "write"]);
        assert!(sw.is_some());
        assert!(sw.unwrap().occurrences >= 3);
    }
}
