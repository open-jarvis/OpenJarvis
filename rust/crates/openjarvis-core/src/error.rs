//! Error types for OpenJarvis.

use thiserror::Error;

/// Top-level error type for all OpenJarvis operations.
#[derive(Error, Debug)]
pub enum OpenJarvisError {
    #[error("Registry error: {0}")]
    Registry(#[from] RegistryError),

    #[error("Config error: {0}")]
    Config(#[from] ConfigError),

    #[error("Engine error: {0}")]
    Engine(#[from] EngineError),

    #[error("Tool error: {0}")]
    Tool(#[from] ToolError),

    #[error("Security error: {0}")]
    Security(#[from] SecurityError),

    #[error("Storage error: {0}")]
    Storage(#[from] StorageError),

    #[error("Agent error: {0}")]
    Agent(#[from] AgentError),

    #[error("Trace error: {0}")]
    Trace(#[from] TraceError),

    #[error("Telemetry error: {0}")]
    Telemetry(#[from] TelemetryError),

    #[error("Learning error: {0}")]
    Learning(#[from] LearningError),

    #[error("MCP error: {0}")]
    Mcp(#[from] McpError),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
}

/// Registry-specific errors.
#[derive(Error, Debug)]
pub enum RegistryError {
    #[error("Duplicate key '{0}' in {1}")]
    DuplicateKey(String, &'static str),

    #[error("Key '{0}' not found in {1}")]
    NotFound(String, &'static str),

    #[error("Entry '{0}' in {1} is not callable")]
    NotCallable(String, &'static str),
}

/// Config loading errors.
#[derive(Error, Debug)]
pub enum ConfigError {
    #[error("Failed to read config file: {0}")]
    ReadFile(#[from] std::io::Error),

    #[error("Failed to parse TOML: {0}")]
    ParseToml(#[from] toml::de::Error),

    #[error("Invalid config value: {0}")]
    InvalidValue(String),

    #[error("Config path not found: {0}")]
    PathNotFound(String),
}

/// Inference engine errors.
#[derive(Error, Debug)]
pub enum EngineError {
    #[error("Connection failed: {0}")]
    Connection(String),

    #[error("Generation failed: {0}")]
    Generation(String),

    #[error("Model not found: {0}")]
    ModelNotFound(String),

    #[error("Engine not healthy: {0}")]
    NotHealthy(String),

    #[error("Streaming error: {0}")]
    Streaming(String),

    #[error("HTTP error: {0}")]
    Http(String),

    #[error("Deserialization error: {0}")]
    Deserialization(String),

    #[error("Timeout after {0}s")]
    Timeout(f64),
}

/// Tool execution errors.
#[derive(Error, Debug)]
pub enum ToolError {
    #[error("Tool not found: {0}")]
    NotFound(String),

    #[error("Execution failed: {0}")]
    Execution(String),

    #[error("Timeout after {0}s for tool '{1}'")]
    Timeout(f64, String),

    #[error("Capability denied: agent '{0}' lacks '{1}'")]
    CapabilityDenied(String, String),

    #[error("Taint violation: tool '{0}' cannot process {1} data")]
    TaintViolation(String, String),

    #[error("Confirmation required for tool '{0}'")]
    ConfirmationRequired(String),

    #[error("Invalid parameters: {0}")]
    InvalidParams(String),
}

/// Security-related errors.
#[derive(Error, Debug)]
pub enum SecurityError {
    #[error("Content blocked: {0}")]
    Blocked(String),

    #[error("SSRF attempt blocked: {0}")]
    SsrfBlocked(String),

    #[error("Rate limit exceeded for key '{0}'")]
    RateLimited(String),

    #[error("Injection detected: {0}")]
    InjectionDetected(String),

    #[error("Taint violation: {0}")]
    TaintViolation(String),

    #[error("Audit error: {0}")]
    Audit(String),

    #[error("Signing error: {0}")]
    Signing(String),
}

/// Storage / memory backend errors.
#[derive(Error, Debug)]
pub enum StorageError {
    #[error("SQLite error: {0}")]
    Sqlite(String),

    #[error("Document not found: {0}")]
    DocumentNotFound(String),

    #[error("Index error: {0}")]
    Index(String),

    #[error("Backend not available: {0}")]
    BackendNotAvailable(String),
}

/// Agent errors.
#[derive(Error, Debug)]
pub enum AgentError {
    #[error("Agent not found: {0}")]
    NotFound(String),

    #[error("Max turns ({0}) exceeded")]
    MaxTurnsExceeded(usize),

    #[error("Loop detected: {0}")]
    LoopDetected(String),

    #[error("Engine error: {0}")]
    Engine(#[from] EngineError),

    #[error("Tool error: {0}")]
    Tool(#[from] ToolError),

    #[error("Context overflow")]
    ContextOverflow,

    #[error("Execution error: {0}")]
    Execution(String),
}

/// Trace recording errors.
#[derive(Error, Debug)]
pub enum TraceError {
    #[error("Storage error: {0}")]
    Storage(String),

    #[error("Trace not found: {0}")]
    NotFound(String),
}

/// Telemetry errors.
#[derive(Error, Debug)]
pub enum TelemetryError {
    #[error("Storage error: {0}")]
    Storage(String),

    #[error("Energy monitor error: {0}")]
    EnergyMonitor(String),
}

/// Learning policy errors.
#[derive(Error, Debug)]
pub enum LearningError {
    #[error("Policy error: {0}")]
    Policy(String),

    #[error("No models available for routing")]
    NoModels,

    #[error("Training error: {0}")]
    Training(String),
}

/// MCP protocol errors.
#[derive(Error, Debug)]
pub enum McpError {
    #[error("Protocol error: {0}")]
    Protocol(String),

    #[error("Transport error: {0}")]
    Transport(String),

    #[error("Method not found: {0}")]
    MethodNotFound(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_display() {
        let e = RegistryError::NotFound("ollama".into(), "EngineRegistry");
        assert_eq!(
            e.to_string(),
            "Key 'ollama' not found in EngineRegistry"
        );
    }

    #[test]
    fn test_error_from_registry() {
        let e: OpenJarvisError =
            RegistryError::DuplicateKey("foo".into(), "ToolRegistry").into();
        assert!(matches!(e, OpenJarvisError::Registry(_)));
    }

    #[test]
    fn test_engine_error_variants() {
        let e = EngineError::Timeout(30.0);
        assert_eq!(e.to_string(), "Timeout after 30s");
    }
}
