//! SFT router — learns query_class → model mappings from trace data.

use parking_lot::RwLock;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Serialize, Deserialize)]
pub struct SFTRouterPolicy {
    min_samples: usize,
    #[serde(skip)]
    policy_map: RwLock<HashMap<String, String>>,
}

impl Clone for SFTRouterPolicy {
    fn clone(&self) -> Self {
        Self {
            min_samples: self.min_samples,
            policy_map: RwLock::new(self.policy_map.read().clone()),
        }
    }
}

impl SFTRouterPolicy {
    pub fn new(min_samples: usize) -> Self {
        Self {
            min_samples,
            policy_map: RwLock::new(HashMap::new()),
        }
    }

    pub fn policy_map(&self) -> HashMap<String, String> {
        self.policy_map.read().clone()
    }

    /// Classify a query into a broad category for routing.
    pub fn classify_query(query: &str) -> &'static str {
        let q = query.to_lowercase();
        if ["def ", "class ", "import ", "```", "function"]
            .iter()
            .any(|kw| q.contains(kw))
        {
            return "code";
        }
        if ["solve", "integral", "equation", "derivative", "proof"]
            .iter()
            .any(|kw| q.contains(kw))
        {
            return "math";
        }
        let words: usize = query.split_whitespace().count();
        if words < 10 {
            return "short";
        }
        if words > 100 {
            return "long";
        }
        "general"
    }

    /// Update the policy map from trace data.
    ///
    /// Each entry is `(query, model, outcome, optional_feedback)`.
    /// `outcome` should be `"success"` or another string; feedback is in `[0, 1]`.
    pub fn update_from_data(
        &self,
        traces: &[(String, String, String, Option<f64>)],
    ) -> HashMap<String, serde_json::Value> {
        // query_class -> model -> Vec<composite_score>
        let mut class_model_scores: HashMap<String, HashMap<String, Vec<f64>>> = HashMap::new();

        for (query, model, outcome, feedback) in traces {
            let query_class = Self::classify_query(query);
            let outcome_score = if outcome == "success" { 1.0 } else { 0.0 };
            let fb = feedback.unwrap_or(0.5);
            let composite = 0.6 * outcome_score + 0.4 * fb;

            class_model_scores
                .entry(query_class.to_string())
                .or_default()
                .entry(model.clone())
                .or_default()
                .push(composite);
        }

        let mut changes: HashMap<String, String> = HashMap::new();
        let mut map = self.policy_map.write();

        for (qclass, model_scores) in &class_model_scores {
            let mut best_model: Option<&str> = None;
            let mut best_score = -1.0_f64;

            for (model, scores) in model_scores {
                if scores.len() >= self.min_samples {
                    let avg = scores.iter().sum::<f64>() / scores.len() as f64;
                    if avg > best_score {
                        best_score = avg;
                        best_model = Some(model.as_str());
                    }
                }
            }

            if let Some(bm) = best_model {
                let old = map.get(qclass).cloned();
                if old.as_deref() != Some(bm) {
                    map.insert(qclass.clone(), bm.to_string());
                    changes.insert(qclass.clone(), bm.to_string());
                }
            }
        }

        let mut result = HashMap::new();
        result.insert(
            "updated".to_string(),
            serde_json::Value::Bool(!changes.is_empty()),
        );
        result.insert(
            "changes".to_string(),
            serde_json::to_value(&changes).unwrap_or_default(),
        );
        result.insert(
            "policy_map".to_string(),
            serde_json::to_value(&*map).unwrap_or_default(),
        );
        result
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_classify_query() {
        assert_eq!(SFTRouterPolicy::classify_query("def foo():"), "code");
        assert_eq!(SFTRouterPolicy::classify_query("solve x^2 = 4"), "math");
        assert_eq!(SFTRouterPolicy::classify_query("hello"), "short");
        assert_eq!(
            SFTRouterPolicy::classify_query(
                "word ".repeat(101).trim()
            ),
            "long"
        );
        assert_eq!(
            SFTRouterPolicy::classify_query(
                "word ".repeat(50).trim()
            ),
            "general"
        );
    }

    #[test]
    fn test_update_from_data_builds_policy() {
        let policy = SFTRouterPolicy::new(2);
        let traces: Vec<(String, String, String, Option<f64>)> = vec![
            ("def foo():".into(), "code_model".into(), "success".into(), Some(0.9)),
            ("def bar():".into(), "code_model".into(), "success".into(), Some(0.8)),
            ("def baz():".into(), "other_model".into(), "failure".into(), Some(0.2)),
            ("solve x=1".into(), "math_model".into(), "success".into(), Some(0.85)),
            ("solve y=2".into(), "math_model".into(), "success".into(), Some(0.9)),
        ];
        let result = policy.update_from_data(&traces);
        assert_eq!(result["updated"], serde_json::Value::Bool(true));
        let map = policy.policy_map();
        assert_eq!(map.get("code"), Some(&"code_model".to_string()));
        assert_eq!(map.get("math"), Some(&"math_model".to_string()));
    }

    #[test]
    fn test_min_samples_threshold() {
        let policy = SFTRouterPolicy::new(5);
        let traces: Vec<(String, String, String, Option<f64>)> = vec![
            ("def foo():".into(), "m1".into(), "success".into(), Some(0.9)),
            ("def bar():".into(), "m1".into(), "success".into(), Some(0.9)),
        ];
        policy.update_from_data(&traces);
        let map = policy.policy_map();
        assert!(!map.contains_key("code"), "should not update with < min_samples");
    }
}
