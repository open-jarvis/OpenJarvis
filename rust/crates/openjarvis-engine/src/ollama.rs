//! Ollama inference engine backend.

use crate::traits::{InferenceEngine, TokenStream};
use openjarvis_core::error::{EngineError, OpenJarvisError};
use openjarvis_core::{GenerateResult, Message, ToolCall, Usage};
use serde_json::Value;

/// Ollama backend via its native HTTP API.
pub struct OllamaEngine {
    host: String,
    client: reqwest::blocking::Client,
    timeout: std::time::Duration,
}

impl OllamaEngine {
    pub fn new(host: &str, timeout_secs: f64) -> Self {
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
        Self::new("http://localhost:11434", 120.0)
    }
}

impl Default for OllamaEngine {
    fn default() -> Self {
        Self::with_defaults()
    }
}

#[async_trait::async_trait]
impl InferenceEngine for OllamaEngine {
    fn engine_id(&self) -> &str {
        "ollama"
    }

    fn generate(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<GenerateResult, OpenJarvisError> {
        let msg_dicts = crate::traits::messages_to_dicts(messages);
        let mut payload = serde_json::json!({
            "model": model,
            "messages": msg_dicts,
            "stream": false,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        });

        if let Some(extra_val) = extra {
            if let Some(tools) = extra_val.get("tools") {
                payload["tools"] = tools.clone();
            }
        }

        let resp = self
            .client
            .post(format!("{}/api/chat", self.host))
            .json(&payload)
            .send()
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(format!(
                    "Ollama not reachable at {}: {}",
                    self.host, e
                )))
            })?;

        if !resp.status().is_success() {
            return Err(OpenJarvisError::Engine(EngineError::Http(format!(
                "Ollama returned status {}",
                resp.status()
            ))));
        }

        let data: Value = resp.json().map_err(|e| {
            OpenJarvisError::Engine(EngineError::Deserialization(e.to_string()))
        })?;

        let prompt_tokens = data["prompt_eval_count"].as_i64().unwrap_or(0);
        let completion_tokens = data["eval_count"].as_i64().unwrap_or(0);
        let content = data["message"]["content"]
            .as_str()
            .unwrap_or("")
            .to_string();
        let model_name = data["model"].as_str().unwrap_or(model).to_string();
        let ttft = data["prompt_eval_duration"].as_f64().unwrap_or(0.0) / 1e9;

        let tool_calls = data["message"]["tool_calls"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .enumerate()
                    .map(|(i, tc)| {
                        let func = &tc["function"];
                        let args = if func["arguments"].is_object() {
                            serde_json::to_string(&func["arguments"]).unwrap_or_default()
                        } else {
                            func["arguments"]
                                .as_str()
                                .unwrap_or("{}")
                                .to_string()
                        };
                        ToolCall {
                            id: tc["id"]
                                .as_str()
                                .unwrap_or(&format!("call_{i}"))
                                .to_string(),
                            name: func["name"].as_str().unwrap_or("").to_string(),
                            arguments: args,
                        }
                    })
                    .collect()
            });

        Ok(GenerateResult {
            content,
            usage: Usage {
                prompt_tokens,
                completion_tokens,
                total_tokens: prompt_tokens + completion_tokens,
            },
            model: model_name,
            finish_reason: "stop".into(),
            tool_calls,
            ttft,
            cost_usd: 0.0,
            metadata: std::collections::HashMap::new(),
        })
    }

    async fn stream(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        _extra: Option<&Value>,
    ) -> Result<TokenStream, OpenJarvisError> {
        let msg_dicts = crate::traits::messages_to_dicts(messages);
        let payload = serde_json::json!({
            "model": model,
            "messages": msg_dicts,
            "stream": true,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        });

        let async_client = reqwest::Client::builder()
            .timeout(self.timeout)
            .build()
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(e.to_string()))
            })?;

        let resp = async_client
            .post(format!("{}/api/chat", self.host))
            .json(&payload)
            .send()
            .await
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(format!(
                    "Ollama not reachable at {}: {}",
                    self.host, e
                )))
            })?;

        if !resp.status().is_success() {
            return Err(OpenJarvisError::Engine(EngineError::Http(format!(
                "Ollama returned status {}",
                resp.status()
            ))));
        }

        let byte_stream = resp.bytes_stream();
        use futures::StreamExt;

        let token_stream = byte_stream.filter_map(|chunk_result| async {
            match chunk_result {
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    for line in text.lines() {
                        if line.trim().is_empty() {
                            continue;
                        }
                        if let Ok(chunk) = serde_json::from_str::<Value>(line) {
                            let content = chunk["message"]["content"]
                                .as_str()
                                .unwrap_or("")
                                .to_string();
                            if !content.is_empty() {
                                return Some(Ok(content));
                            }
                            if chunk["done"].as_bool().unwrap_or(false) {
                                return None;
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
        let resp = self
            .client
            .get(format!("{}/api/tags", self.host))
            .send()
            .map_err(|_| {
                OpenJarvisError::Engine(EngineError::Connection(
                    "Ollama not reachable".into(),
                ))
            })?;

        if !resp.status().is_success() {
            return Ok(vec![]);
        }

        let data: Value = resp.json().unwrap_or(Value::Null);
        let models = data["models"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|m| m["name"].as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        Ok(models)
    }

    fn health(&self) -> bool {
        self.client
            .get(format!("{}/api/tags", self.host))
            .timeout(std::time::Duration::from_secs(2))
            .send()
            .map(|r| r.status().is_success())
            .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ollama_default_host() {
        let engine = OllamaEngine::with_defaults();
        assert_eq!(engine.engine_id(), "ollama");
        assert_eq!(engine.host, "http://localhost:11434");
    }
}
