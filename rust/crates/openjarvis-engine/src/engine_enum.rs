//! Engine enum — static dispatch over all engine backends.
//!
//! Avoids `dyn InferenceEngine` for the hot path. Each variant holds a
//! concrete engine so the compiler can inline and devirtualize.

use crate::ollama::OllamaEngine;
use crate::openai_compat::OpenAICompatEngine;
use crate::traits::{InferenceEngine, TokenStream};
use openjarvis_core::error::OpenJarvisError;
use openjarvis_core::{GenerateResult, Message};
use serde_json::Value;

/// Closed enum of all supported inference engine backends.
///
/// Static dispatch at compile-time — no vtable overhead on the hot path.
pub enum Engine {
    Ollama(OllamaEngine),
    Vllm(OpenAICompatEngine),
    Sglang(OpenAICompatEngine),
    LlamaCpp(OpenAICompatEngine),
    Mlx(OpenAICompatEngine),
    LmStudio(OpenAICompatEngine),
}

macro_rules! delegate_engine {
    ($self:expr, $method:ident $(, $arg:expr)*) => {
        match $self {
            Engine::Ollama(e) => e.$method($($arg),*),
            Engine::Vllm(e) => e.$method($($arg),*),
            Engine::Sglang(e) => e.$method($($arg),*),
            Engine::LlamaCpp(e) => e.$method($($arg),*),
            Engine::Mlx(e) => e.$method($($arg),*),
            Engine::LmStudio(e) => e.$method($($arg),*),
        }
    };
}

#[async_trait::async_trait]
impl InferenceEngine for Engine {
    fn engine_id(&self) -> &str {
        delegate_engine!(self, engine_id)
    }

    fn generate(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<GenerateResult, OpenJarvisError> {
        delegate_engine!(self, generate, messages, model, temperature, max_tokens, extra)
    }

    async fn stream(
        &self,
        messages: &[Message],
        model: &str,
        temperature: f64,
        max_tokens: i64,
        extra: Option<&Value>,
    ) -> Result<TokenStream, OpenJarvisError> {
        match self {
            Engine::Ollama(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Vllm(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Sglang(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::LlamaCpp(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Mlx(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::LmStudio(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
        }
    }

    fn list_models(&self) -> Result<Vec<String>, OpenJarvisError> {
        delegate_engine!(self, list_models)
    }

    fn health(&self) -> bool {
        delegate_engine!(self, health)
    }

    fn close(&self) {
        delegate_engine!(self, close)
    }

    fn prepare(&self, model: &str) {
        delegate_engine!(self, prepare, model)
    }
}

impl Engine {
    /// Convenience: identify the engine variant key (e.g. "ollama", "vllm").
    pub fn variant_key(&self) -> &str {
        match self {
            Engine::Ollama(_) => "ollama",
            Engine::Vllm(_) => "vllm",
            Engine::Sglang(_) => "sglang",
            Engine::LlamaCpp(_) => "llamacpp",
            Engine::Mlx(_) => "mlx",
            Engine::LmStudio(_) => "lmstudio",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_engine_variant_key() {
        let e = Engine::Ollama(OllamaEngine::with_defaults());
        assert_eq!(e.variant_key(), "ollama");
        assert_eq!(e.engine_id(), "ollama");
    }

    #[test]
    fn test_engine_vllm_variant() {
        let e = Engine::Vllm(OpenAICompatEngine::vllm("http://localhost:8000"));
        assert_eq!(e.variant_key(), "vllm");
        assert_eq!(e.engine_id(), "vllm");
    }
}
