//! vLLM inference engine backend.
//!
//! vLLM exposes an OpenAI-compatible API at `http://host:port/v1/`.

use crate::traits::{InferenceEngine, TokenStream};
use openjarvis_core::error::{EngineError, OpenJarvisError};
use openjarvis_core::{GenerateResult, Message, ToolCall, Usage};
use serde_json::Value;

/// vLLM backend via its OpenAI-compatible HTTP API.
pub struct VLLMEngine {
    host: String,
    client: reqwest::blocking::Client,
    api_key: Option<String>,
    timeout: std::time::Duration,
}

impl VLLMEngine {
    pub fn new(host: &str, port: u16, api_key: Option<String>, timeout_secs: f64) -> Self {
        let host = format!(
            "{}:{}",
            host.trim_end_matches('/').trim_end_matches(|c: char| c == ':' || c.is_ascii_digit()),
            port
        );
        // If the host doesn't start with http, prepend it.
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
            api_key,
            timeout,
        }
    }

    pub fn with_defaults() -> Self {
        Self::new("http://localhost", 8000, None, 120.0)
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
            api_key: None,
            timeout,
        }
    }

    fn build_headers(&self) -> reqwest::header::HeaderMap {
        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::CONTENT_TYPE,
            "application/json".parse().unwrap(),
        );
        if let Some(ref key) = self.api_key {
            headers.insert(
                reqwest::header::AUTHORIZATION,
                format!("Bearer {key}").parse().unwrap(),
            );
        }
        headers
    }
}

impl Default for VLLMEngine {
    fn default() -> Self {
        Self::with_defaults()
    }
}

#[async_trait::async_trait]
impl InferenceEngine for VLLMEngine {
    fn engine_id(&self) -> &str {
        "vllm"
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
            "temperature": temperature,
            "max_tokens": max_tokens,
        });

        if let Some(extra_val) = extra {
            if let Some(tools) = extra_val.get("tools") {
                payload["tools"] = tools.clone();
            }
            if let Some(obj) = extra_val.as_object() {
                for (k, v) in obj {
                    if k != "tools" {
                        payload[k] = v.clone();
                    }
                }
            }
        }

        let resp = self
            .client
            .post(format!("{}/v1/chat/completions", self.host))
            .headers(self.build_headers())
            .json(&payload)
            .send()
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(format!(
                    "vLLM not reachable at {}: {}",
                    self.host, e
                )))
            })?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().unwrap_or_default();
            return Err(OpenJarvisError::Engine(EngineError::Http(format!(
                "vLLM returned {status}: {body}"
            ))));
        }

        let data: Value = resp.json().map_err(|e| {
            OpenJarvisError::Engine(EngineError::Deserialization(e.to_string()))
        })?;

        let choice = &data["choices"][0];
        let content = choice["message"]["content"]
            .as_str()
            .unwrap_or("")
            .to_string();
        let finish_reason = choice["finish_reason"]
            .as_str()
            .unwrap_or("stop")
            .to_string();

        let usage_obj = &data["usage"];
        let usage = Usage {
            prompt_tokens: usage_obj["prompt_tokens"].as_i64().unwrap_or(0),
            completion_tokens: usage_obj["completion_tokens"].as_i64().unwrap_or(0),
            total_tokens: usage_obj["total_tokens"].as_i64().unwrap_or(0),
        };

        let model_name = data["model"].as_str().unwrap_or(model).to_string();

        let tool_calls = choice["message"]["tool_calls"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .map(|tc| {
                        let func = &tc["function"];
                        ToolCall {
                            id: tc["id"].as_str().unwrap_or("").to_string(),
                            name: func["name"].as_str().unwrap_or("").to_string(),
                            arguments: func["arguments"]
                                .as_str()
                                .unwrap_or("{}")
                                .to_string(),
                        }
                    })
                    .collect()
            });

        Ok(GenerateResult {
            content,
            usage,
            model: model_name,
            finish_reason,
            tool_calls,
            ttft: 0.0,
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
        extra: Option<&Value>,
    ) -> Result<TokenStream, OpenJarvisError> {
        let msg_dicts = crate::traits::messages_to_dicts(messages);
        let mut payload = serde_json::json!({
            "model": model,
            "messages": msg_dicts,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": true,
        });

        if let Some(extra_val) = extra {
            if let Some(tools) = extra_val.get("tools") {
                payload["tools"] = tools.clone();
            }
        }

        let async_client = reqwest::Client::builder()
            .timeout(self.timeout)
            .build()
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(e.to_string()))
            })?;

        let mut headers = reqwest::header::HeaderMap::new();
        headers.insert(
            reqwest::header::CONTENT_TYPE,
            "application/json".parse().unwrap(),
        );
        if let Some(ref key) = self.api_key {
            headers.insert(
                reqwest::header::AUTHORIZATION,
                format!("Bearer {key}").parse().unwrap(),
            );
        }

        let resp = async_client
            .post(format!("{}/v1/chat/completions", self.host))
            .headers(headers)
            .json(&payload)
            .send()
            .await
            .map_err(|e| {
                OpenJarvisError::Engine(EngineError::Connection(format!(
                    "vLLM not reachable at {}: {}",
                    self.host, e
                )))
            })?;

        if !resp.status().is_success() {
            return Err(OpenJarvisError::Engine(EngineError::Http(format!(
                "vLLM returned {}",
                resp.status()
            ))));
        }

        use futures::StreamExt;
        let byte_stream = resp.bytes_stream();

        let token_stream = byte_stream.filter_map(|chunk_result| async {
            match chunk_result {
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    for line in text.lines() {
                        let line = line.trim();
                        if line.is_empty() || line == "data: [DONE]" {
                            continue;
                        }
                        let json_str = line.strip_prefix("data: ").unwrap_or(line);
                        if let Ok(chunk) = serde_json::from_str::<Value>(json_str) {
                            let content = chunk["choices"][0]["delta"]["content"]
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
        let resp = self
            .client
            .get(format!("{}/v1/models", self.host))
            .headers(self.build_headers())
            .send()
            .map_err(|_| {
                OpenJarvisError::Engine(EngineError::Connection(
                    "vLLM not reachable".into(),
                ))
            })?;

        if !resp.status().is_success() {
            return Ok(vec![]);
        }

        let data: Value = resp.json().unwrap_or(Value::Null);
        let models = data["data"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .filter_map(|m| m["id"].as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();
        Ok(models)
    }

    fn health(&self) -> bool {
        // vLLM exposes /health; fall back to /v1/models if needed.
        let health_ok = self
            .client
            .get(format!("{}/health", self.host))
            .timeout(std::time::Duration::from_secs(2))
            .send()
            .map(|r| r.status().is_success())
            .unwrap_or(false);

        if health_ok {
            return true;
        }

        self.client
            .get(format!("{}/v1/models", self.host))
            .headers(self.build_headers())
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
    fn test_vllm_default_host() {
        let engine = VLLMEngine::with_defaults();
        assert_eq!(engine.engine_id(), "vllm");
        assert_eq!(engine.host, "http://localhost:8000");
    }

    #[test]
    fn test_vllm_from_host() {
        let engine = VLLMEngine::from_host("http://gpu-server:8000");
        assert_eq!(engine.engine_id(), "vllm");
        assert_eq!(engine.host, "http://gpu-server:8000");
    }

    #[test]
    fn test_vllm_with_api_key() {
        let engine = VLLMEngine::new("http://localhost", 8000, Some("sk-test".into()), 60.0);
        assert!(engine.api_key.is_some());
    }
}
