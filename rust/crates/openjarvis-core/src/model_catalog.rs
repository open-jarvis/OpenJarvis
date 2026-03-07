//! Built-in model catalog with well-known ModelSpec entries.
//!
//! Rust translation of `src/openjarvis/intelligence/model_catalog.py`.

use once_cell::sync::Lazy;
use std::collections::HashMap;

use crate::registry::MODEL_REGISTRY;
use crate::types::{ModelSpec, Quantization};

/// Built-in catalog of common open models.
pub static BUILTIN_MODELS: Lazy<Vec<ModelSpec>> = Lazy::new(|| {
    vec![
        // Qwen3 family
        ModelSpec {
            model_id: "qwen3:0.6b".into(),
            name: "Qwen3 0.6B".into(),
            parameter_count_b: 0.6,
            context_length: 32768,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 0.5,
            supported_engines: vec!["ollama".into(), "llamacpp".into()],
            provider: "alibaba".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        ModelSpec {
            model_id: "qwen3:1.7b".into(),
            name: "Qwen3 1.7B".into(),
            parameter_count_b: 1.7,
            context_length: 32768,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 1.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "alibaba".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        ModelSpec {
            model_id: "qwen3:4b".into(),
            name: "Qwen3 4B".into(),
            parameter_count_b: 4.0,
            context_length: 32768,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 2.5,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "alibaba".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        ModelSpec {
            model_id: "qwen3:8b".into(),
            name: "Qwen3 8B".into(),
            parameter_count_b: 8.2,
            context_length: 32768,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 5.0,
            supported_engines: vec![
                "ollama".into(),
                "vllm".into(),
                "llamacpp".into(),
                "sglang".into(),
            ],
            provider: "alibaba".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        ModelSpec {
            model_id: "qwen3:14b".into(),
            name: "Qwen3 14B".into(),
            parameter_count_b: 14.8,
            context_length: 32768,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 10.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "alibaba".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        ModelSpec {
            model_id: "qwen3:32b".into(),
            name: "Qwen3 32B".into(),
            parameter_count_b: 32.0,
            context_length: 32768,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 20.0,
            supported_engines: vec!["ollama".into(), "vllm".into()],
            provider: "alibaba".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        // Llama
        ModelSpec {
            model_id: "llama3.3:latest".into(),
            name: "Llama 3.3".into(),
            parameter_count_b: 8.0,
            context_length: 131072,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 5.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "meta".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        // DeepSeek R1
        ModelSpec {
            model_id: "deepseek-r1:7b".into(),
            name: "DeepSeek R1 7B".into(),
            parameter_count_b: 7.0,
            context_length: 65536,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 5.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "deepseek".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        ModelSpec {
            model_id: "deepseek-r1:14b".into(),
            name: "DeepSeek R1 14B".into(),
            parameter_count_b: 14.0,
            context_length: 65536,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 10.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "deepseek".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        // Gemma
        ModelSpec {
            model_id: "gemma3:4b".into(),
            name: "Gemma 3 4B".into(),
            parameter_count_b: 4.0,
            context_length: 8192,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 2.5,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "google".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        ModelSpec {
            model_id: "gemma3:12b".into(),
            name: "Gemma 3 12B".into(),
            parameter_count_b: 12.0,
            context_length: 8192,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 8.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "google".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        // Phi
        ModelSpec {
            model_id: "phi-4:14b".into(),
            name: "Phi 4 14B".into(),
            parameter_count_b: 14.0,
            context_length: 16384,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 10.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "microsoft".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        // Mistral
        ModelSpec {
            model_id: "mistral:7b".into(),
            name: "Mistral 7B".into(),
            parameter_count_b: 7.0,
            context_length: 32768,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 5.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "mistral".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
        // Code Llama
        ModelSpec {
            model_id: "codellama:7b".into(),
            name: "Code Llama 7B".into(),
            parameter_count_b: 7.0,
            context_length: 16384,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 5.0,
            supported_engines: vec!["ollama".into(), "vllm".into(), "llamacpp".into()],
            provider: "meta".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        },
    ]
});

/// Register all built-in models into `MODEL_REGISTRY`.
/// Safe to call multiple times; uses `register_or_replace` so existing entries are updated.
pub fn register_builtin_models() {
    for spec in BUILTIN_MODELS.iter() {
        MODEL_REGISTRY.register_or_replace(&spec.model_id, spec.clone());
    }
}

/// Create minimal `ModelSpec` entries for models discovered by an engine that are not
/// already in the registry.
pub fn merge_discovered_models(engine_key: &str, model_ids: &[String]) {
    for model_id in model_ids {
        if !MODEL_REGISTRY.contains(model_id) {
            let spec = ModelSpec {
                model_id: model_id.clone(),
                name: model_id.clone(),
                parameter_count_b: 0.0,
                context_length: 8192,
                active_parameter_count_b: None,
                quantization: Quantization::None,
                min_vram_gb: 0.0,
                supported_engines: vec![engine_key.to_string()],
                provider: String::new(),
                requires_api_key: false,
                metadata: HashMap::new(),
            };
            MODEL_REGISTRY.register_or_replace(model_id, spec);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::registry::TypedRegistry;

    #[test]
    fn test_builtin_models_count_and_key_models() {
        assert!(
            BUILTIN_MODELS.len() >= 14,
            "expected at least 14 builtin models, got {}",
            BUILTIN_MODELS.len()
        );
        let ids: Vec<&str> = BUILTIN_MODELS.iter().map(|s| s.model_id.as_str()).collect();
        assert!(ids.contains(&"qwen3:8b"), "missing qwen3:8b");
        assert!(ids.contains(&"llama3.3:latest"), "missing llama3.3:latest");
        assert!(ids.contains(&"deepseek-r1:7b"), "missing deepseek-r1:7b");
        assert!(ids.contains(&"mistral:7b"), "missing mistral:7b");
    }

    #[test]
    fn test_register_builtin_models() {
        let reg = TypedRegistry::<ModelSpec>::new("TestModelReg");
        for spec in BUILTIN_MODELS.iter() {
            reg.register_or_replace(&spec.model_id, spec.clone());
        }
        for spec in BUILTIN_MODELS.iter() {
            assert!(
                reg.contains(&spec.model_id),
                "model {} not registered",
                spec.model_id
            );
        }
        for spec in BUILTIN_MODELS.iter() {
            reg.register_or_replace(&spec.model_id, spec.clone());
        }
        for spec in BUILTIN_MODELS.iter() {
            assert!(
                reg.contains(&spec.model_id),
                "model {} not registered after second call",
                spec.model_id
            );
        }
    }

    #[test]
    fn test_merge_discovered_models_adds_new_only() {
        MODEL_REGISTRY.clear();
        register_builtin_models();
        merge_discovered_models(
            "ollama",
            &[
                "qwen3:8b".into(),
                "custom-model:1b".into(),
                "another-unknown".into(),
            ],
        );
        assert!(MODEL_REGISTRY.contains("custom-model:1b"));
        assert!(MODEL_REGISTRY.contains("another-unknown"));
        let custom = MODEL_REGISTRY.get("custom-model:1b").unwrap();
        assert_eq!(custom.supported_engines, vec!["ollama"]);
        assert_eq!(custom.context_length, 8192);
        assert_eq!(custom.name, "custom-model:1b");
        MODEL_REGISTRY.clear();
    }
}
