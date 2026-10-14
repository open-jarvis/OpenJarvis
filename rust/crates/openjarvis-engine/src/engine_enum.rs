//! Engine enum — static dispatch over all engine backends.
//!
//! Avoids `dyn InferenceEngine` for the hot path. Each variant holds a
//! concrete engine so the compiler can inline and devirtualize.

use crate::llamacpp::LlamaCppEngine;
use crate::ollama::OllamaEngine;
use crate::openai_compat::OpenAICompatEngine;
use crate::sglang::SGLangEngine;
use crate::vllm::VLLMEngine;
use crate::traits::{InferenceEngine, TokenStream};
use openjarvis_core::error::OpenJarvisError;
use openjarvis_core::{GenerateResult, Message};
use serde_json::Value;

/// Closed enum of all supported inference engine backends.
///
/// Static dispatch at compile-time — no vtable overhead on the hot path.
pub enum Engine {
    Ollama(OllamaEngine),
    /// Dedicated vLLM engine with OpenAI-compatible API.
    VLLM(VLLMEngine),
    /// Dedicated SGLang engine with OpenAI-compatible API.
    SGLang(SGLangEngine),
    /// Dedicated llama.cpp engine with native `/completion` API.
    LlamaCppNative(LlamaCppEngine),
    /// Legacy: vLLM via generic OpenAI-compatible engine.
    Vllm(OpenAICompatEngine),
    /// Legacy: SGLang via generic OpenAI-compatible engine.
    Sglang(OpenAICompatEngine),
    /// Legacy: llama.cpp via generic OpenAI-compatible engine.
    LlamaCpp(OpenAICompatEngine),
    Mlx(OpenAICompatEngine),
    LmStudio(OpenAICompatEngine),
    Exo(OpenAICompatEngine),
    Nexa(OpenAICompatEngine),
    Uzu(OpenAICompatEngine),
    AppleFm(OpenAICompatEngine),
    FoundryLocal(OpenAICompatEngine),
}

macro_rules! delegate_engine {
    ($self:expr, $method:ident $(, $arg:expr)*) => {
        match $self {
            Engine::Ollama(e) => e.$method($($arg),*),
            Engine::VLLM(e) => e.$method($($arg),*),
            Engine::SGLang(e) => e.$method($($arg),*),
            Engine::LlamaCppNative(e) => e.$method($($arg),*),
            Engine::Vllm(e) => e.$method($($arg),*),
            Engine::Sglang(e) => e.$method($($arg),*),
            Engine::LlamaCpp(e) => e.$method($($arg),*),
            Engine::Mlx(e) => e.$method($($arg),*),
            Engine::LmStudio(e) => e.$method($($arg),*),
            Engine::Exo(e) => e.$method($($arg),*),
            Engine::Nexa(e) => e.$method($($arg),*),
            Engine::Uzu(e) => e.$method($($arg),*),
            Engine::AppleFm(e) => e.$method($($arg),*),
            Engine::FoundryLocal(e) => e.$method($($arg),*),
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
            Engine::VLLM(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::SGLang(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::LlamaCppNative(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Vllm(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Sglang(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::LlamaCpp(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Mlx(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::LmStudio(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Exo(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Nexa(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::Uzu(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::AppleFm(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
            Engine::FoundryLocal(e) => e.stream(messages, model, temperature, max_tokens, extra).await,
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
            Engine::VLLM(_) => "vllm",
            Engine::SGLang(_) => "sglang",
            Engine::LlamaCppNative(_) => "llamacpp",
            Engine::Vllm(_) => "vllm",
            Engine::Sglang(_) => "sglang",
            Engine::LlamaCpp(_) => "llamacpp",
            Engine::Mlx(_) => "mlx",
            Engine::LmStudio(_) => "lmstudio",
            Engine::Exo(_) => "exo",
            Engine::Nexa(_) => "nexa",
            Engine::Uzu(_) => "uzu",
            Engine::AppleFm(_) => "apple_fm",
            Engine::FoundryLocal(_) => "foundry_local",
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

    #[test]
    fn test_engine_exo_variant() {
        let e = Engine::Exo(OpenAICompatEngine::exo("http://localhost:52415"));
        assert_eq!(e.variant_key(), "exo");
        assert_eq!(e.engine_id(), "exo");
    }

    #[test]
    fn test_engine_nexa_variant() {
        let e = Engine::Nexa(OpenAICompatEngine::nexa("http://localhost:18181"));
        assert_eq!(e.variant_key(), "nexa");
        assert_eq!(e.engine_id(), "nexa");
    }

    #[test]
    fn test_engine_uzu_variant() {
        let e = Engine::Uzu(OpenAICompatEngine::uzu("http://localhost:8080"));
        assert_eq!(e.variant_key(), "uzu");
        assert_eq!(e.engine_id(), "uzu");
    }

    #[test]
    fn test_engine_apple_fm_variant() {
        let e = Engine::AppleFm(OpenAICompatEngine::apple_fm("http://localhost:8079"));
        assert_eq!(e.variant_key(), "apple_fm");
        assert_eq!(e.engine_id(), "apple_fm");
    }

    #[test]
    fn test_engine_foundry_local_variant() {
        let e = Engine::FoundryLocal(OpenAICompatEngine::foundry_local(
            "http://localhost:5273",
        ));
        assert_eq!(e.variant_key(), "foundry_local");
        assert_eq!(e.engine_id(), "foundry_local");
    }

    #[test]
    fn test_engine_vllm_native_variant() {
        let e = Engine::VLLM(VLLMEngine::with_defaults());
        assert_eq!(e.variant_key(), "vllm");
        assert_eq!(e.engine_id(), "vllm");
    }

    #[test]
    fn test_engine_sglang_native_variant() {
        let e = Engine::SGLang(SGLangEngine::with_defaults());
        assert_eq!(e.variant_key(), "sglang");
        assert_eq!(e.engine_id(), "sglang");
    }

    #[test]
    fn test_engine_llamacpp_native_variant() {
        let e = Engine::LlamaCppNative(LlamaCppEngine::with_defaults());
        assert_eq!(e.variant_key(), "llamacpp");
        assert_eq!(e.engine_id(), "llamacpp");
    }
}
