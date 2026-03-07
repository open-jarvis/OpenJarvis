//! Decorator-based registry for runtime discovery of pluggable components.
//!
//! Rust translation of `src/openjarvis/core/registry.py`.
//! Uses `parking_lot::RwLock` for thread-safe concurrent access.

use crate::error::RegistryError;
use parking_lot::RwLock;
use std::collections::HashMap;
use std::sync::Arc;

/// A thread-safe, typed registry for runtime component discovery.
///
/// Each registry instance stores entries keyed by string names.
/// This is the Rust equivalent of the Python `RegistryBase[T]` generic class.
pub struct TypedRegistry<T: Send + Sync + 'static> {
    entries: RwLock<HashMap<String, Arc<T>>>,
    name: &'static str,
}

impl<T: Send + Sync + 'static> TypedRegistry<T> {
    /// Create a new empty registry with the given name.
    pub fn new(name: &'static str) -> Self {
        Self {
            entries: RwLock::new(HashMap::new()),
            name,
        }
    }

    /// Register a value under the given key.
    ///
    /// Returns an error if the key is already registered.
    pub fn register(&self, key: &str, value: T) -> Result<(), RegistryError> {
        let mut entries = self.entries.write();
        if entries.contains_key(key) {
            return Err(RegistryError::DuplicateKey(
                key.to_string(),
                self.name,
            ));
        }
        entries.insert(key.to_string(), Arc::new(value));
        Ok(())
    }

    /// Register a value, replacing any existing entry with the same key.
    pub fn register_or_replace(&self, key: &str, value: T) {
        let mut entries = self.entries.write();
        entries.insert(key.to_string(), Arc::new(value));
    }

    /// Retrieve the entry for `key`.
    pub fn get(&self, key: &str) -> Result<Arc<T>, RegistryError> {
        let entries = self.entries.read();
        entries
            .get(key)
            .cloned()
            .ok_or_else(|| RegistryError::NotFound(key.to_string(), self.name))
    }

    /// Check whether `key` is registered.
    pub fn contains(&self, key: &str) -> bool {
        self.entries.read().contains_key(key)
    }

    /// Return all registered keys.
    pub fn keys(&self) -> Vec<String> {
        self.entries.read().keys().cloned().collect()
    }

    /// Return all `(key, entry)` pairs.
    pub fn items(&self) -> Vec<(String, Arc<T>)> {
        self.entries
            .read()
            .iter()
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect()
    }

    /// Remove all entries (useful in tests).
    pub fn clear(&self) {
        self.entries.write().clear();
    }

    /// Return the number of registered entries.
    pub fn len(&self) -> usize {
        self.entries.read().len()
    }

    /// Check if the registry is empty.
    pub fn is_empty(&self) -> bool {
        self.entries.read().is_empty()
    }

    /// The name of this registry (for error messages).
    pub fn name(&self) -> &'static str {
        self.name
    }
}

// ---------------------------------------------------------------------------
// Global registry instances — one per pillar
// ---------------------------------------------------------------------------

use crate::types::ModelSpec;
use once_cell::sync::Lazy;

/// Registry for `ModelSpec` objects.
pub static MODEL_REGISTRY: Lazy<TypedRegistry<ModelSpec>> =
    Lazy::new(|| TypedRegistry::new("ModelRegistry"));

/// Registry for engine factory functions.
/// Stores closures that create `dyn InferenceEngine` instances.
pub static ENGINE_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("EngineRegistry"));

/// Registry for agent factory functions.
pub static AGENT_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("AgentRegistry"));

/// Registry for tool specifications.
pub static TOOL_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("ToolRegistry"));

/// Registry for memory backend factories.
pub static MEMORY_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("MemoryRegistry"));

/// Registry for router policy factories.
pub static ROUTER_POLICY_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("RouterPolicyRegistry"));

/// Registry for benchmark implementations.
pub static BENCHMARK_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("BenchmarkRegistry"));

/// Registry for channel implementations.
pub static CHANNEL_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("ChannelRegistry"));

/// Registry for learning policies.
pub static LEARNING_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("LearningRegistry"));

/// Registry for skill manifests.
pub static SKILL_REGISTRY: Lazy<TypedRegistry<serde_json::Value>> =
    Lazy::new(|| TypedRegistry::new("SkillRegistry"));

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_register_and_get() {
        let reg: TypedRegistry<String> = TypedRegistry::new("TestRegistry");
        reg.register("hello", "world".to_string()).unwrap();
        let val = reg.get("hello").unwrap();
        assert_eq!(*val, "world");
    }

    #[test]
    fn test_duplicate_key_error() {
        let reg: TypedRegistry<String> = TypedRegistry::new("TestRegistry");
        reg.register("key", "val1".to_string()).unwrap();
        let err = reg.register("key", "val2".to_string()).unwrap_err();
        assert!(matches!(err, RegistryError::DuplicateKey(_, _)));
    }

    #[test]
    fn test_not_found_error() {
        let reg: TypedRegistry<String> = TypedRegistry::new("TestRegistry");
        let err = reg.get("missing").unwrap_err();
        assert!(matches!(err, RegistryError::NotFound(_, _)));
    }

    #[test]
    fn test_contains() {
        let reg: TypedRegistry<i32> = TypedRegistry::new("TestRegistry");
        assert!(!reg.contains("x"));
        reg.register("x", 42).unwrap();
        assert!(reg.contains("x"));
    }

    #[test]
    fn test_keys_and_items() {
        let reg: TypedRegistry<i32> = TypedRegistry::new("TestRegistry");
        reg.register("a", 1).unwrap();
        reg.register("b", 2).unwrap();
        let mut keys = reg.keys();
        keys.sort();
        assert_eq!(keys, vec!["a", "b"]);
        assert_eq!(reg.items().len(), 2);
    }

    #[test]
    fn test_clear() {
        let reg: TypedRegistry<i32> = TypedRegistry::new("TestRegistry");
        reg.register("a", 1).unwrap();
        reg.register("b", 2).unwrap();
        assert_eq!(reg.len(), 2);
        reg.clear();
        assert!(reg.is_empty());
    }

    #[test]
    fn test_register_or_replace() {
        let reg: TypedRegistry<String> = TypedRegistry::new("TestRegistry");
        reg.register("key", "v1".to_string()).unwrap();
        reg.register_or_replace("key", "v2".to_string());
        assert_eq!(*reg.get("key").unwrap(), "v2");
    }

    #[test]
    fn test_model_registry() {
        let reg = TypedRegistry::<ModelSpec>::new("TestModelRegistry");
        let spec = ModelSpec {
            model_id: "test:1b".into(),
            name: "Test 1B".into(),
            parameter_count_b: 1.0,
            context_length: 4096,
            active_parameter_count_b: None,
            quantization: crate::types::Quantization::None,
            min_vram_gb: 1.0,
            supported_engines: vec!["ollama".into()],
            provider: "".into(),
            requires_api_key: false,
            metadata: std::collections::HashMap::new(),
        };
        reg.register("test:1b", spec).unwrap();
        assert!(reg.contains("test:1b"));
    }
}
