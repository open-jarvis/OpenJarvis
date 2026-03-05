//! GuardrailsEngine — security-aware inference engine wrapper.

use crate::scanner::{PIIScanner, SecretScanner};
use crate::types::{RedactionMode, ScanResult};
use openjarvis_core::error::{EngineError, OpenJarvisError};
use openjarvis_core::{EventBus, EventType, GenerateResult, Message};
use openjarvis_engine::traits::{InferenceEngine, TokenStream};
use serde_json::Value;
use std::sync::Arc;

/// Wraps an existing `InferenceEngine` with security scanning on I/O.
///
/// Generic over `E` for static dispatch when the engine type is known.
pub struct GuardrailsEngine<E: InferenceEngine> {
    engine: E,
    secret_scanner: SecretScanner,
    pii_scanner: PIIScanner,
    mode: RedactionMode,
    scan_input: bool,
    scan_output: bool,
    bus: Option<Arc<EventBus>>,
}

impl<E: InferenceEngine> GuardrailsEngine<E> {
    pub fn new(
        engine: E,
        mode: RedactionMode,
        scan_input: bool,
        scan_output: bool,
        bus: Option<Arc<EventBus>>,
    ) -> Self {
        Self {
            engine,
            secret_scanner: SecretScanner::new(),
            pii_scanner: PIIScanner::new(),
            mode,
            scan_input,
            scan_output,
            bus,
        }
    }

    fn scan_text(&self, text: &str) -> ScanResult {
        let mut result = self.secret_scanner.scan(text);
        let pii_result = self.pii_scanner.scan(text);
        result.findings.extend(pii_result.findings);
        result
    }

    fn redact_text(&self, text: &str) -> String {
        let r = self.secret_scanner.redact(text);
        self.pii_scanner.redact(&r)
    }

    fn handle_findings(
        &self,
        text: &str,
        result: &ScanResult,
        direction: &str,
    ) -> Result<String, OpenJarvisError> {
        let finding_dicts: Vec<Value> = result
            .findings
            .iter()
            .map(|f| {
                serde_json::json!({
                    "pattern": f.pattern_name,
                    "threat": f.threat_level.to_string(),
                    "description": f.description,
                })
            })
            .collect();

        match self.mode {
            RedactionMode::Warn => {
                if let Some(ref bus) = self.bus {
                    let mut data = std::collections::HashMap::new();
                    data.insert(
                        "direction".to_string(),
                        Value::String(direction.to_string()),
                    );
                    data.insert("findings".to_string(), Value::Array(finding_dicts));
                    data.insert("mode".to_string(), Value::String("warn".to_string()));
                    bus.publish(EventType::SecurityAlert, data);
                }
                Ok(text.to_string())
            }
            RedactionMode::Redact => {
                if let Some(ref bus) = self.bus {
                    let mut data = std::collections::HashMap::new();
                    data.insert(
                        "direction".to_string(),
                        Value::String(direction.to_string()),
                    );
                    data.insert("findings".to_string(), Value::Array(finding_dicts));
                    data.insert(
                        "mode".to_string(),
                        Value::String("redact".to_string()),
                    );
                    bus.publish(EventType::SecurityAlert, data);
                }
                Ok(self.redact_text(text))
            }
            RedactionMode::Block => {
                if let Some(ref bus) = self.bus {
                    let mut data = std::collections::HashMap::new();
                    data.insert(
                        "direction".to_string(),
                        Value::String(direction.to_string()),
                    );
                    data.insert("findings".to_string(), Value::Array(finding_dicts));
                    data.insert(
                        "mode".to_string(),
                        Value::String("block".to_string()),
                    );
                    bus.publish(EventType::SecurityBlock, data);
                }
                Err(OpenJarvisError::Security(
                    openjarvis_core::error::SecurityError::Blocked(format!(
                        "Security scan blocked {}: {} finding(s) detected",
                        direction,
                        result.findings.len()
                    )),
                ))
            }
        }
    }
}

#[async_trait::async_trait]
impl<E: InferenceEngine> InferenceEngine for GuardrailsEngine<E> {
    fn engine_id(&self) -> &str {
        self.engine.engine_id()
    }

    fn generate(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<GenerateResult, OpenJarvisError> {
        if self.scan_input {
            for msg in messages {
                if !msg.content.is_empty() {
                    let result = self.scan_text(&msg.content);
                    if !result.clean() {
                        self.handle_findings(&msg.content, &result, "input")?;
                    }
                }
            }
        }

        let mut response = self
            .engine
            .generate(messages, model, temperature, max_tokens, extra)?;

        if self.scan_output && !response.content.is_empty() {
            let result = self.scan_text(&response.content);
            if !result.clean() {
                response.content =
                    self.handle_findings(&response.content, &result, "output")?;
            }
        }

        Ok(response)
    }

    async fn stream(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<TokenStream, OpenJarvisError> {
        self.engine
            .stream(messages, model, temperature, max_tokens, extra)
            .await
    }

    fn list_models(&self) -> Result<Vec<String>, OpenJarvisError> {
        self.engine.list_models()
    }

    fn health(&self) -> bool {
        self.engine.health()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MockEngine;

    #[async_trait::async_trait]
    impl InferenceEngine for MockEngine {
        fn engine_id(&self) -> &str {
            "mock"
        }
        fn generate(
            &self,
            _messages: &[Message],
            model: &str,
            _temperature: f64,
            _max_tokens: i64,
            _extra: Option<&Value>,
        ) -> Result<GenerateResult, OpenJarvisError> {
            Ok(GenerateResult {
                content: "Response with sk-test1234567890abcdefghij".into(),
                model: model.into(),
                ..Default::default()
            })
        }
        async fn stream(
            &self,
            _messages: &[Message],
            _model: &str,
            _temperature: f64,
            _max_tokens: i64,
            _extra: Option<&Value>,
        ) -> Result<TokenStream, OpenJarvisError> {
            Ok(Box::pin(futures::stream::empty()))
        }
        fn list_models(&self) -> Result<Vec<String>, OpenJarvisError> {
            Ok(vec!["mock-model".into()])
        }
        fn health(&self) -> bool {
            true
        }
    }

    #[test]
    fn test_guardrails_warn_mode() {
        let engine = MockEngine;
        let guardrails =
            GuardrailsEngine::new(engine, RedactionMode::Warn, false, true, None);
        let result = guardrails
            .generate(&[Message::user("Hi")], "mock", 0.7, 100, None)
            .unwrap();
        assert!(result.content.contains("sk-test"));
    }

    #[test]
    fn test_guardrails_redact_mode() {
        let engine = MockEngine;
        let guardrails =
            GuardrailsEngine::new(engine, RedactionMode::Redact, false, true, None);
        let result = guardrails
            .generate(&[Message::user("Hi")], "mock", 0.7, 100, None)
            .unwrap();
        assert!(result.content.contains("[REDACTED:"));
        assert!(!result.content.contains("sk-test"));
    }

    #[test]
    fn test_guardrails_block_mode() {
        let engine = MockEngine;
        let guardrails =
            GuardrailsEngine::new(engine, RedactionMode::Block, false, true, None);
        let err = guardrails
            .generate(&[Message::user("Hi")], "mock", 0.7, 100, None)
            .unwrap_err();
        assert!(matches!(err, OpenJarvisError::Security(_)));
    }
}
