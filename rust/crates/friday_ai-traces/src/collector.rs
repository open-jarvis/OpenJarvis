//! TraceCollector — subscribes to EventBus and assembles traces.

use crate::store::TraceStore;
use friday_ai_core::{Trace, TraceStep};
use parking_lot::Mutex;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

pub struct TraceCollector {
    store: Arc<TraceStore>,
    active_traces: Arc<Mutex<HashMap<String, Trace>>>,
}

impl TraceCollector {
    pub fn new(store: Arc<TraceStore>) -> Self {
        Self {
            store,
            active_traces: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub fn start_trace(&self, trace_id: &str, query: &str, agent: &str, model: &str) {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        let trace = Trace {
            trace_id: trace_id.to_string(),
            query: query.to_string(),
            agent: agent.to_string(),
            model: model.to_string(),
            started_at: now,
            ..Default::default()
        };

        self.active_traces
            .lock()
            .insert(trace_id.to_string(), trace);
    }

    pub fn add_step(&self, trace_id: &str, step: TraceStep) {
        if let Some(trace) = self.active_traces.lock().get_mut(trace_id) {
            trace.add_step(step);
        }
    }

    pub fn end_trace(
        &self,
        trace_id: &str,
        result: &str,
        outcome: Option<&str>,
    ) -> Result<(), friday_ai_core::FridayAIError> {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();

        let mut traces = self.active_traces.lock();
        if let Some(mut trace) = traces.remove(trace_id) {
            trace.result = result.to_string();
            trace.outcome = outcome.map(String::from);
            trace.ended_at = now;
            self.store.save(&trace)?;
        }
        Ok(())
    }

    pub fn active_count(&self) -> usize {
        self.active_traces.lock().len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use friday_ai_core::StepType;

    #[test]
    fn test_collector_lifecycle() {
        let store = Arc::new(TraceStore::in_memory().unwrap());
        let collector = TraceCollector::new(store.clone());

        collector.start_trace("t1", "hello", "simple", "qwen3:8b");
        assert_eq!(collector.active_count(), 1);

        let step = TraceStep {
            step_type: StepType::Generate,
            timestamp: 1000.0,
            duration_seconds: 0.5,
            input: HashMap::new(),
            output: HashMap::new(),
            metadata: HashMap::new(),
        };
        collector.add_step("t1", step);
        collector.end_trace("t1", "world", Some("success")).unwrap();

        assert_eq!(collector.active_count(), 0);
        assert_eq!(store.count().unwrap(), 1);
    }
}
