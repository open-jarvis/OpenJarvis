//! TraceAnalyzer — compute statistics from stored traces.

use crate::store::TraceStore;
use openjarvis_core::OpenJarvisError;
use std::collections::HashMap;

#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct TraceStats {
    pub count: usize,
    pub success_count: usize,
    pub failure_count: usize,
    pub avg_latency: f64,
    pub avg_tokens: f64,
    pub success_rate: f64,
}

pub struct TraceAnalyzer<'a> {
    store: &'a TraceStore,
}

impl<'a> TraceAnalyzer<'a> {
    pub fn new(store: &'a TraceStore) -> Self {
        Self { store }
    }

    pub fn overall_stats(&self) -> Result<TraceStats, OpenJarvisError> {
        let traces = self.store.list_traces(10000, 0)?;
        if traces.is_empty() {
            return Ok(TraceStats::default());
        }

        let count = traces.len();
        let success_count = traces
            .iter()
            .filter(|t| t.outcome.as_deref() == Some("success"))
            .count();
        let failure_count = traces
            .iter()
            .filter(|t| t.outcome.as_deref() == Some("failure"))
            .count();
        let avg_latency = traces.iter().map(|t| t.total_latency_seconds).sum::<f64>()
            / count as f64;
        let avg_tokens =
            traces.iter().map(|t| t.total_tokens as f64).sum::<f64>() / count as f64;
        let success_rate = if count > 0 {
            success_count as f64 / count as f64
        } else {
            0.0
        };

        Ok(TraceStats {
            count,
            success_count,
            failure_count,
            avg_latency,
            avg_tokens,
            success_rate,
        })
    }

    pub fn stats_by_agent(&self) -> Result<HashMap<String, TraceStats>, OpenJarvisError> {
        let traces = self.store.list_traces(10000, 0)?;
        let mut by_agent: HashMap<String, Vec<_>> = HashMap::new();

        for trace in &traces {
            by_agent
                .entry(trace.agent.clone())
                .or_default()
                .push(trace);
        }

        let mut result = HashMap::new();
        for (agent, agent_traces) in by_agent {
            let count = agent_traces.len();
            let success_count = agent_traces
                .iter()
                .filter(|t| t.outcome.as_deref() == Some("success"))
                .count();
            let failure_count = agent_traces
                .iter()
                .filter(|t| t.outcome.as_deref() == Some("failure"))
                .count();
            let avg_latency = agent_traces
                .iter()
                .map(|t| t.total_latency_seconds)
                .sum::<f64>()
                / count as f64;
            let avg_tokens = agent_traces
                .iter()
                .map(|t| t.total_tokens as f64)
                .sum::<f64>()
                / count as f64;

            result.insert(
                agent,
                TraceStats {
                    count,
                    success_count,
                    failure_count,
                    avg_latency,
                    avg_tokens,
                    success_rate: success_count as f64 / count as f64,
                },
            );
        }

        Ok(result)
    }

    pub fn stats_by_model(&self) -> Result<HashMap<String, TraceStats>, OpenJarvisError> {
        let traces = self.store.list_traces(10000, 0)?;
        let mut by_model: HashMap<String, Vec<_>> = HashMap::new();

        for trace in &traces {
            by_model
                .entry(trace.model.clone())
                .or_default()
                .push(trace);
        }

        let mut result = HashMap::new();
        for (model, model_traces) in by_model {
            let count = model_traces.len();
            let success_count = model_traces
                .iter()
                .filter(|t| t.outcome.as_deref() == Some("success"))
                .count();
            let avg_latency = model_traces
                .iter()
                .map(|t| t.total_latency_seconds)
                .sum::<f64>()
                / count as f64;

            result.insert(
                model,
                TraceStats {
                    count,
                    success_count,
                    failure_count: count - success_count,
                    avg_latency,
                    avg_tokens: model_traces
                        .iter()
                        .map(|t| t.total_tokens as f64)
                        .sum::<f64>()
                        / count as f64,
                    success_rate: success_count as f64 / count as f64,
                },
            );
        }

        Ok(result)
    }
}
