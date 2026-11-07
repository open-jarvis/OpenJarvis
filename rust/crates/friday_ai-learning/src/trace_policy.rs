//! Trace-driven router policy — learns from interaction history.

use once_cell::sync::Lazy;
use parking_lot::RwLock;
use regex::Regex;
use std::collections::HashMap;

static CODE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)```|`[^`]+`|\bdef\s|\bclass\s|\bimport\s|\bfunction\s").unwrap()
});
static MATH_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?i)\bsolve\b|\bintegral\b|\bequation\b|\bcalculate\b|\bcompute\b").unwrap()
});

/// Classify a query into a broad category for routing.
pub fn classify_query(query: &str) -> &'static str {
    if CODE_RE.is_match(query) {
        return "code";
    }
    if MATH_RE.is_match(query) {
        return "math";
    }
    if query.len() < 50 {
        return "short";
    }
    if query.len() > 500 {
        return "long";
    }
    "general"
}

#[derive(Debug, Clone)]
struct ModelScore {
    count: u32,
    successes: u32,
    total_latency: f64,
    feedback_sum: f64,
    feedback_count: u32,
}

impl ModelScore {
    fn new() -> Self {
        Self {
            count: 0,
            successes: 0,
            total_latency: 0.0,
            feedback_sum: 0.0,
            feedback_count: 0,
        }
    }

    fn composite_score(&self) -> f64 {
        let sr = if self.count > 0 {
            self.successes as f64 / self.count as f64
        } else {
            0.0
        };
        let fb = if self.feedback_count > 0 {
            self.feedback_sum / self.feedback_count as f64
        } else {
            0.5
        };
        0.6 * sr + 0.4 * fb
    }
}

#[derive(Debug)]
pub struct TraceDrivenPolicy {
    available: Vec<String>,
    default_model: String,
    fallback_model: String,
    policy_map: RwLock<HashMap<String, String>>,
    confidence: RwLock<HashMap<String, u32>>,
    pub min_samples: u32,
}

impl Clone for TraceDrivenPolicy {
    fn clone(&self) -> Self {
        Self {
            available: self.available.clone(),
            default_model: self.default_model.clone(),
            fallback_model: self.fallback_model.clone(),
            policy_map: RwLock::new(self.policy_map.read().clone()),
            confidence: RwLock::new(self.confidence.read().clone()),
            min_samples: self.min_samples,
        }
    }
}

impl TraceDrivenPolicy {
    pub fn new(
        available_models: Vec<String>,
        default_model: String,
        fallback_model: String,
    ) -> Self {
        Self {
            available: available_models,
            default_model,
            fallback_model,
            policy_map: RwLock::new(HashMap::new()),
            confidence: RwLock::new(HashMap::new()),
            min_samples: 5,
        }
    }

    /// Select the best model based on learned policy or fallback.
    pub fn select_model(&self, query: &str) -> String {
        let qclass = classify_query(query);

        let map = self.policy_map.read();
        let conf = self.confidence.read();

        if let Some(model) = map.get(qclass) {
            if conf.get(qclass).copied().unwrap_or(0) >= self.min_samples
                && (self.available.is_empty() || self.available.contains(model))
            {
                return model.clone();
            }
        }
        drop(map);
        drop(conf);

        if !self.default_model.is_empty()
            && (self.available.is_empty() || self.available.contains(&self.default_model))
        {
            return self.default_model.clone();
        }
        if !self.fallback_model.is_empty()
            && (self.available.is_empty() || self.available.contains(&self.fallback_model))
        {
            return self.fallback_model.clone();
        }
        if let Some(first) = self.available.first() {
            return first.clone();
        }
        self.default_model.clone()
    }

    /// Batch-update the policy map from trace data.
    ///
    /// Each entry is `(query, model, outcome, latency_s, optional_feedback)`.
    pub fn update_from_data(
        &self,
        traces: &[(String, String, String, f64, Option<f64>)],
    ) -> HashMap<String, serde_json::Value> {
        // query_class -> model -> ModelScore
        let mut groups: HashMap<String, HashMap<String, ModelScore>> = HashMap::new();

        for (query, model, outcome, latency, feedback) in traces {
            if model.is_empty() {
                continue;
            }
            let qclass = classify_query(query);
            let score = groups
                .entry(qclass.to_string())
                .or_default()
                .entry(model.clone())
                .or_insert_with(ModelScore::new);

            score.count += 1;
            score.total_latency += latency;
            if outcome == "success" {
                score.successes += 1;
            }
            if let Some(fb) = feedback {
                score.feedback_sum += fb;
                score.feedback_count += 1;
            }
        }

        let mut map = self.policy_map.write();
        let mut conf = self.confidence.write();
        let old_map = map.clone();
        let mut changes: HashMap<String, HashMap<String, String>> = HashMap::new();

        for (qclass, model_scores) in &groups {
            let best = model_scores
                .iter()
                .max_by(|a, b| {
                    a.1.composite_score()
                        .partial_cmp(&b.1.composite_score())
                        .unwrap_or(std::cmp::Ordering::Equal)
                });

            if let Some((best_model, _)) = best {
                map.insert(qclass.clone(), best_model.clone());
                let total_count: u32 = model_scores.values().map(|s| s.count).sum();
                conf.insert(qclass.clone(), total_count);

                if old_map.get(qclass) != Some(best_model) {
                    let mut change = HashMap::new();
                    change.insert(
                        "old".to_string(),
                        old_map.get(qclass).cloned().unwrap_or_default(),
                    );
                    change.insert("new".to_string(), best_model.clone());
                    changes.insert(qclass.clone(), change);
                }
            }
        }

        let mut result = HashMap::new();
        result.insert("updated".into(), serde_json::Value::Bool(true));
        result.insert(
            "query_classes".into(),
            serde_json::Value::Number(groups.len().into()),
        );
        result.insert(
            "total_traces".into(),
            serde_json::Value::Number(traces.len().into()),
        );
        result.insert(
            "changes".into(),
            serde_json::to_value(&changes).unwrap_or_default(),
        );
        result
    }

    /// Record a single observation for online (incremental) updates.
    pub fn observe(
        &self,
        query: &str,
        model: &str,
        outcome: Option<&str>,
        feedback: Option<f64>,
    ) {
        let qclass = classify_query(query);
        let mut map = self.policy_map.write();
        let mut conf = self.confidence.write();

        let current_count = conf.get(qclass).copied().unwrap_or(0);

        if !map.contains_key(qclass) {
            map.insert(qclass.to_string(), model.to_string());
            conf.insert(qclass.to_string(), 1);
            return;
        }

        conf.insert(qclass.to_string(), current_count + 1);

        if outcome == Some("success") {
            if let Some(fb) = feedback {
                if fb > 0.7 && current_count < self.min_samples {
                    map.insert(qclass.to_string(), model.to_string());
                }
            }
        }
    }

    pub fn policy_map(&self) -> HashMap<String, String> {
        self.policy_map.read().clone()
    }

    pub fn confidence(&self) -> HashMap<String, u32> {
        self.confidence.read().clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_classify_code() {
        assert_eq!(classify_query("```python\nprint(1)\n```"), "code");
        assert_eq!(classify_query("def foo():"), "code");
        assert_eq!(classify_query("function bar()"), "code");
    }

    #[test]
    fn test_classify_math() {
        assert_eq!(classify_query("solve x^2 + 3x = 0"), "math");
        assert_eq!(classify_query("compute the integral"), "math");
    }

    #[test]
    fn test_classify_length() {
        assert_eq!(classify_query("hi"), "short");
        assert_eq!(classify_query(&"a".repeat(600)), "long");
        let medium = "word ".repeat(20);
        assert_eq!(classify_query(&medium), "general");
    }

    #[test]
    fn test_select_model_fallback() {
        let policy = TraceDrivenPolicy::new(
            vec!["m1".into(), "m2".into()],
            "m1".into(),
            "m2".into(),
        );
        assert_eq!(policy.select_model("hello"), "m1");
    }

    #[test]
    fn test_update_and_select() {
        let policy = TraceDrivenPolicy::new(vec![], "default".into(), "fallback".into());
        let _ = policy.min_samples;

        let traces: Vec<(String, String, String, f64, Option<f64>)> = (0..10)
            .map(|_| {
                (
                    "def foo():".to_string(),
                    "code_model".to_string(),
                    "success".to_string(),
                    0.5,
                    Some(0.9),
                )
            })
            .collect();

        policy.update_from_data(&traces);

        let map = policy.policy_map();
        assert_eq!(map.get("code"), Some(&"code_model".to_string()));
    }

    #[test]
    fn test_observe() {
        let policy = TraceDrivenPolicy::new(vec![], "default".into(), "".into());
        policy.observe("hello there", "new_model", Some("success"), Some(0.9));
        let map = policy.policy_map();
        assert_eq!(map.get("short"), Some(&"new_model".to_string()));
    }
}
