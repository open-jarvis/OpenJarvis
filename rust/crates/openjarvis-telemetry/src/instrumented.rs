//! InstrumentedEngine — wraps any InferenceEngine with telemetry recording.

use crate::store::TelemetryStore;
use openjarvis_core::error::OpenJarvisError;
use openjarvis_core::{GenerateResult, Message, TelemetryRecord};
use openjarvis_engine::traits::{InferenceEngine, TokenStream};
use serde_json::Value;
use std::sync::Arc;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

/// Wraps any `InferenceEngine` with telemetry recording.
///
/// Generic over `E` for static dispatch when the engine type is known.
pub struct InstrumentedEngine<E: InferenceEngine> {
    inner: E,
    store: Arc<TelemetryStore>,
    agent_name: String,
}

impl<E: InferenceEngine> InstrumentedEngine<E> {
    pub fn new(
        inner: E,
        store: Arc<TelemetryStore>,
        agent_name: String,
    ) -> Self {
        Self {
            inner,
            store,
            agent_name,
        }
    }

    fn now_timestamp() -> f64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64()
    }
}

#[async_trait::async_trait]
impl<E: InferenceEngine> InferenceEngine for InstrumentedEngine<E> {
    fn engine_id(&self) -> &str {
        self.inner.engine_id()
    }

    fn generate(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<GenerateResult, OpenJarvisError> {
        let start = Instant::now();
        let result = self
            .inner
            .generate(messages, model, temperature, max_tokens, extra)?;
        let elapsed = start.elapsed().as_secs_f64();

        let throughput = if elapsed > 0.0 {
            result.usage.completion_tokens as f64 / elapsed
        } else {
            0.0
        };

        let rec = TelemetryRecord {
            timestamp: Self::now_timestamp(),
            model_id: model.to_string(),
            prompt_tokens: result.usage.prompt_tokens,
            completion_tokens: result.usage.completion_tokens,
            total_tokens: result.usage.total_tokens,
            latency_seconds: elapsed,
            ttft: result.ttft,
            cost_usd: result.cost_usd,
            throughput_tok_per_sec: throughput,
            engine: self.inner.engine_id().to_string(),
            agent: self.agent_name.clone(),
            ..Default::default()
        };

        if let Err(e) = self.store.record(&rec) {
            tracing::warn!("Failed to record telemetry: {}", e);
        }

        Ok(result)
    }

    async fn stream(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<TokenStream, OpenJarvisError> {
        self.inner
            .stream(messages, model, temperature, max_tokens, extra)
            .await
    }

    fn list_models(&self) -> Result<Vec<String>, OpenJarvisError> {
        self.inner.list_models()
    }

    fn health(&self) -> bool {
        self.inner.health()
    }

    fn close(&self) {
        self.inner.close();
    }

    fn prepare(&self, model: &str) {
        self.inner.prepare(model);
    }
}
