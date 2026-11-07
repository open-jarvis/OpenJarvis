//! Inference Engine primitive — LLM runtime management.
//!
//! Provides the `InferenceEngine` trait and concrete backends (Ollama,
//! cloud providers, OpenAI-compatible servers).

pub mod discovery;
pub mod engine_enum;
pub mod llamacpp;
pub mod ollama;
pub mod openai_compat;
pub mod rig_adapter;
pub mod sglang;
pub mod traits;
pub mod vllm;

pub use discovery::{discover_engines, get_engine_static};
pub use engine_enum::Engine;
pub use llamacpp::LlamaCppEngine;
pub use ollama::OllamaEngine;
pub use openai_compat::OpenAICompatEngine;
pub use sglang::SGLangEngine;
pub use traits::{InferenceEngine, messages_to_dicts};
pub use vllm::VLLMEngine;
