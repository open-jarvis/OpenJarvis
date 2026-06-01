//! llama.cpp inference engine backend.
//!
//! llama.cpp server exposes `/completion` (not `/v1/chat/completions`)
//! with a different request/response format.

use crate::traits::{InferenceEngine, TokenStream};
use openjarvis_core::error::{EngineError, OpenJarvisError};
use openjarvis_core::{GenerateResult, Message, Usage};
use serde_json::Value;

/// llama.cpp server backend via its native HTTP API.
///
/// Unlike vLLM/SGLang, llama.cpp uses `/completion` with a prompt-based
/// request format rather than the OpenAI chat completions format.
pub struct LlamaCppEngine {
    host: String,
    client: reqwest::blocking::Client,
    timeout: std::time::Duration,
}

impl LlamaCppEngine {
    pub fn new(host: &str, port: u16, timeout_secs: f64) -> Self {
        let host = format!(
            "{}:{}",
            host.trim_end_matches('/').trim_end_matches(|c: char| c == ':' || c.is_ascii_digit()),
            port
        );
        let host = if host.starts_with("http") {
            host
        } else {
            format!("http://{host}")
        };
        let host = host.trim_end_matches('/').to_string();
        let timeout = std::time::Duration::from_secs_f64(timeout_secs);
        let client = reqwest::blocking::Client::builder()
            .timeout(timeout)
            .build()
            .unwrap_or_default();
        Self {
            host,
            client,
            timeout,
        }
    }

    pub fn with_defaults() -> Self {
        Self::new("http://localhost", 8080, 120.0)
    }

    pub fn from_host(host: &str) -> Self {
        let host = host.trim_end_matches('/').to_string();
        let timeout = std::time::Duration::from_secs_f64(120.0);
        let client = reqwest::blocking::Client::builder()
            .timeout(timeout)
            .build()
            .unwrap_or_default();
        Self {
            host,
            client,
            timeout,
        }
    }

    /// Format chat messages into a single prompt string for llama.cpp.
    ///
    /// Uses a simple ChatML-style format:
    /// `<|system|>\n{content}\n<|user|>\n{content}\n<|assistant|>\n`
    fn messages_to_prompt(messages: &[Message]) -> String {
        let mut prompt = String::new();
        for msg in messages {
            let role = msg.role.to_string();
            prompt.push_str(&format!("<|{}|>\n{}\n", role, msg.content));
        }
        prompt.push_str("<|assistant|>\n");
        prompt
    }
}

impl Default for LlamaCppEngine {
    fn default() -> Self {
        Self::with_defaults()
    }
}

#[async_trait::async_trait]
impl InferenceEngine for LlamaCppEngine {
    fn engine_id(&self) -> &str {
        "llamacpp"
    }

    fn generate(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        _extra: Option<&Value>,
    ) -> Result<GenerateResult, OpenJarvisError> {
        let prompt = Self::messages_to_prompt(messages);
        let payload = serde_json::json!({
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stream": false,
        });

        let resp = self
            .client
            .post(format!("{}/completion", self.host))
            .json(&payload)
            .send()
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(format!(
                    "llama.cpp not reachable at {}: {}",
                    self.host, e
                )))
            })?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().unwrap_or_default();
            return Err(OpenJarvisError::Engine(EngineError::Http(format!(
                "llama.cpp returned {status}: {body}"
            ))));
        }

        let data: Value = resp.json().map_err(|e| {
            OpenJarvisError::Engine(EngineError::Deserialization(e.to_string()))
        })?;

        let content = data["content"]
            .as_str()
            .unwrap_or("")
            .to_string();
        let tokens_evaluated = data["tokens_evaluated"].as_i64().unwrap_or(0);
        let tokens_predicted = data["tokens_predicted"].as_i64().unwrap_or(0);

        let stop_type = data["stop_type"]
            .as_str()
            .unwrap_or("stop");
        let finish_reason = if stop_type == "limit" {
            "length".to_string()
        } else {
            "stop".to_string()
        };

        Ok(GenerateResult {
            content,
            usage: Usage {
                prompt_tokens: tokens_evaluated,
                completion_tokens: tokens_predicted,
                total_tokens: tokens_evaluated + tokens_predicted,
            },
            model: model.to_string(),
            finish_reason,
            tool_calls: None,
            ttft: 0.0,
            cost_usd: 0.0,
            metadata: std::collections::HashMap::new(),
        })
    }

    async fn stream(
        &self,
        messages: &[Message],
        _model: &str,
        temperature: f64,
        max_tokens: i64,
        _extra: Option<&Value>,
    ) -> Result<TokenStream, OpenJarvisError> {
        let prompt = Self::messages_to_prompt(messages);
        let payload = serde_json::json!({
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stream": true,
        });

        let async_client = reqwest::Client::builder()
            .timeout(self.timeout)
            .build()
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(e.to_string()))
            })?;

        let resp = async_client
            .post(format!("{}/completion", self.host))
            .json(&payload)
            .send()
            .await
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(format!(
                    "llama.cpp not reachable at {}: {}",
                    self.host, e
                )))
            })?;

        if !resp.status().is_success() {
            return Err(OpenJarvisError::Engine(EngineError::Http(format!(
                "llama.cpp returned {}",
                resp.status()
            ))));
        }

        use futures::StreamExt;
        let byte_stream = resp.bytes_stream();

        // llama.cpp streams SSE lines: `data: {"content": "token", ...}`
        let token_stream = byte_stream.filter_map(|chunk_result| async {
            match chunk_result {
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    for line in text.lines() {
                        let line = line.trim();
                        if line.is_empty() {
                            continue;
                        }
                        let json_str = line.strip_prefix("data: ").unwrap_or(line);
                        if let Ok(chunk) = serde_json::from_str::<Value>(json_str) {
                            // Check if this is the final chunk
                            if chunk["stop"].as_bool().unwrap_or(false) {
                                return None;
                            }
                            let content = chunk["content"]
                                .as_str()
                                .unwrap_or("")
                                .to_string();
                            if !content.is_empty() {
                                return Some(Ok(content));
                            }
                        }
                    }
                    None
                }
                Err(e) => Some(Err(OpenJarvisError::Engine(EngineError::Streaming(
                    e.to_string(),
                )))),
            }
        });

        Ok(Box::pin(token_stream))
    }

    fn list_models(&self) -> Result<Vec<String>, OpenJarvisError> {
        // llama.cpp server loads a single model; try /v1/models first,
        // then fall back to /props which returns model metadata.
        let resp = self
            .client
            .get(format!("{}/v1/models", self.host))
            .send();

        if let Ok(resp) = resp {
            if resp.status().is_success() {
                let data: Value = resp.json().unwrap_or(Value::Null);
                let models: Vec<String> = data["data"]
                    .as_array()
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|m| m["id"].as_str().map(String::from))
                            .collect()
                    })
                    .unwrap_or_default();
                if !models.is_empty() {
                    return Ok(models);
                }
            }
        }

        // Fallback: /props endpoint
        let resp = self
            .client
            .get(format!("{}/props", self.host))
            .send()
            .map_err(|_| {
                OpenJarvisError::Engine(EngineError::Connection(
                    "llama.cpp not reachable".into(),
                ))
            })?;

        if !resp.status().is_success() {
            return Ok(vec![]);
        }

        let data: Value = resp.json().unwrap_or(Value::Null);
        if let Some(model) = data["default_generation_settings"]["model"]
            .as_str()
            .map(String::from)
        {
            Ok(vec![model])
        } else {
            Ok(vec![])
        }
    }

    fn health(&self) -> bool {
        self.client
            .get(format!("{}/health", self.host))
            .timeout(std::time::Duration::from_secs(2))
            .send()
            .map(|r| r.status().is_success())
            .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use openjarvis_core::Message;

    #[test]
    fn test_llamacpp_default_host() {
        let engine = LlamaCppEngine::with_defaults();
        assert_eq!(engine.engine_id(), "llamacpp");
        assert_eq!(engine.host, "http://localhost:8080");
    }

    #[test]
    fn test_llamacpp_from_host() {
        let engine = LlamaCppEngine::from_host("http://gpu-server:8080");
        assert_eq!(engine.engine_id(), "llamacpp");
        assert_eq!(engine.host, "http://gpu-server:8080");
    }

    #[test]
    fn test_messages_to_prompt() {
        let messages = vec![
            Message::system("You are helpful"),
            Message::user("Hello"),
        ];
        let prompt = LlamaCppEngine::messages_to_prompt(&messages);
        assert!(prompt.contains("<|system|>"));
        assert!(prompt.contains("You are helpful"));
        assert!(prompt.contains("<|user|>"));
        assert!(prompt.contains("Hello"));
        assert!(prompt.ends_with("<|assistant|>\n"));
    }
}
