//! Agent advisor — analyzes trace patterns and suggests improvements.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Summary of a single trace used for pattern analysis.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceInfo {
    pub outcome: String,
    pub query: String,
    pub tool_call_count: usize,
    pub total_latency_seconds: f64,
}

/// A single improvement recommendation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Recommendation {
    pub rec_type: String,
    pub suggestion: String,
    pub severity: String,
}

#[derive(Debug, Clone)]
pub struct AgentAdvisorPolicy {
    max_traces: usize,
}

impl AgentAdvisorPolicy {
    pub fn new(max_traces: usize) -> Self {
        Self { max_traces }
    }

    /// Structural analysis of trace patterns — returns recommendations
    /// without requiring an LM call.
    pub fn analyze_patterns(&self, traces: &[TraceInfo]) -> Vec<Recommendation> {
        let limited = if traces.len() > self.max_traces {
            &traces[traces.len() - self.max_traces..]
        } else {
            traces
        };

        // Separate problem traces (failing or slow)
        let problem_traces: Vec<&TraceInfo> = limited
            .iter()
            .filter(|t| t.outcome != "success" || t.total_latency_seconds > 5.0)
            .collect();

        if problem_traces.is_empty() {
            return Vec::new();
        }

        let mut recs = Vec::new();

        // Check for excessive tool calls
        let tool_heavy_count = problem_traces
            .iter()
            .filter(|t| t.tool_call_count > 5)
            .count();
        if tool_heavy_count as f64 > problem_traces.len() as f64 * 0.3 {
            recs.push(Recommendation {
                rec_type: "agent_structure".to_string(),
                suggestion: "Reduce tool call frequency — many traces have >5 tool calls"
                    .to_string(),
                severity: "medium".to_string(),
            });
        }

        // Check for repeated failures on same query type
        let mut failure_classes: HashMap<&str, usize> = HashMap::new();
        for t in &problem_traces {
            if t.outcome != "success" {
                let qclass = Self::classify(&t.query);
                *failure_classes.entry(qclass).or_insert(0) += 1;
            }
        }
        for (qclass, count) in &failure_classes {
            if *count >= 3 {
                recs.push(Recommendation {
                    rec_type: "routing".to_string(),
                    suggestion: format!(
                        "Query class '{}' has {} failures — consider different model or agent",
                        qclass, count,
                    ),
                    severity: "high".to_string(),
                });
            }
        }

        // Check for consistently slow traces
        let slow_count = problem_traces
            .iter()
            .filter(|t| t.total_latency_seconds > 10.0)
            .count();
        if slow_count as f64 > problem_traces.len() as f64 * 0.5 {
            recs.push(Recommendation {
                rec_type: "performance".to_string(),
                suggestion: format!(
                    "{} of {} problem traces exceed 10s latency — consider faster model or caching",
                    slow_count,
                    problem_traces.len(),
                ),
                severity: "high".to_string(),
            });
        }

        recs
    }

    /// Classify a query into a broad category.
    pub fn classify(query: &str) -> &'static str {
        let q = query.to_lowercase();
        if ["def ", "class ", "import "]
            .iter()
            .any(|kw| q.contains(kw))
        {
            return "code";
        }
        if ["solve", "equation"].iter().any(|kw| q.contains(kw)) {
            return "math";
        }
        "general"
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_classify() {
        assert_eq!(AgentAdvisorPolicy::classify("def hello():"), "code");
        assert_eq!(AgentAdvisorPolicy::classify("solve x=1"), "math");
        assert_eq!(AgentAdvisorPolicy::classify("what is weather?"), "general");
    }

    #[test]
    fn test_no_problems_no_recs() {
        let advisor = AgentAdvisorPolicy::new(50);
        let traces = vec![
            TraceInfo {
                outcome: "success".into(),
                query: "hello".into(),
                tool_call_count: 1,
                total_latency_seconds: 0.5,
            },
            TraceInfo {
                outcome: "success".into(),
                query: "world".into(),
                tool_call_count: 2,
                total_latency_seconds: 1.0,
            },
        ];
        let recs = advisor.analyze_patterns(&traces);
        assert!(recs.is_empty());
    }

    #[test]
    fn test_detects_excessive_tool_calls() {
        let advisor = AgentAdvisorPolicy::new(50);
        let traces: Vec<TraceInfo> = (0..5)
            .map(|i| TraceInfo {
                outcome: "failure".into(),
                query: format!("query {}", i),
                tool_call_count: 8,
                total_latency_seconds: 2.0,
            })
            .collect();
        let recs = advisor.analyze_patterns(&traces);
        assert!(
            recs.iter().any(|r| r.rec_type == "agent_structure"),
            "should detect excessive tool calls"
        );
    }

    #[test]
    fn test_detects_repeated_failures() {
        let advisor = AgentAdvisorPolicy::new(50);
        let traces: Vec<TraceInfo> = (0..5)
            .map(|i| TraceInfo {
                outcome: "failure".into(),
                query: format!("def func_{}():", i),
                tool_call_count: 2,
                total_latency_seconds: 1.0,
            })
            .collect();
        let recs = advisor.analyze_patterns(&traces);
        assert!(
            recs.iter().any(|r| r.rec_type == "routing" && r.suggestion.contains("code")),
            "should detect repeated code failures"
        );
    }
}
