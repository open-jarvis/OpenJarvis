//! Canonical data types shared across all FridayAI primitives.
//!
//! Direct Rust translation of `src/friday_ai/core/types.py`.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/// Chat message roles (OpenAI-compatible).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    System,
    User,
    Assistant,
    Tool,
}

impl std::fmt::Display for Role {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Role::System => write!(f, "system"),
            Role::User => write!(f, "user"),
            Role::Assistant => write!(f, "assistant"),
            Role::Tool => write!(f, "tool"),
        }
    }
}

impl std::str::FromStr for Role {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "system" => Ok(Role::System),
            "user" => Ok(Role::User),
            "assistant" => Ok(Role::Assistant),
            "tool" => Ok(Role::Tool),
            _ => Err(format!("Unknown role: {s}")),
        }
    }
}

/// Model quantization formats.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum Quantization {
    #[default]
    None,
    Fp8,
    Fp4,
    Int8,
    Int4,
    GgufQ4,
    GgufQ8,
}

impl std::fmt::Display for Quantization {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = serde_json::to_value(self)
            .ok()
            .and_then(|v| v.as_str().map(String::from))
            .unwrap_or_else(|| "none".into());
        write!(f, "{s}")
    }
}

/// Types of steps within an agent trace.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StepType {
    Route,
    Retrieve,
    Generate,
    ToolCall,
    Respond,
}

impl std::fmt::Display for StepType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StepType::Route => write!(f, "route"),
            StepType::Retrieve => write!(f, "retrieve"),
            StepType::Generate => write!(f, "generate"),
            StepType::ToolCall => write!(f, "tool_call"),
            StepType::Respond => write!(f, "respond"),
        }
    }
}

// ---------------------------------------------------------------------------
// Message types
// ---------------------------------------------------------------------------

/// A single tool invocation request embedded in an assistant message.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    /// JSON-encoded arguments string.
    pub arguments: String,
}

/// A single chat message (OpenAI-compatible structure).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub role: Role,
    #[serde(default)]
    pub content: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_calls: Option<Vec<ToolCall>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_call_id: Option<String>,
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, serde_json::Value>,
}

impl Message {
    /// Create a new message with the given role and content.
    pub fn new(role: Role, content: impl Into<String>) -> Self {
        Self {
            role,
            content: content.into(),
            name: None,
            tool_calls: None,
            tool_call_id: None,
            metadata: HashMap::new(),
        }
    }

    /// Create a system message.
    pub fn system(content: impl Into<String>) -> Self {
        Self::new(Role::System, content)
    }

    /// Create a user message.
    pub fn user(content: impl Into<String>) -> Self {
        Self::new(Role::User, content)
    }

    /// Create an assistant message.
    pub fn assistant(content: impl Into<String>) -> Self {
        Self::new(Role::Assistant, content)
    }

    /// Create a tool response message.
    pub fn tool(content: impl Into<String>, tool_call_id: impl Into<String>) -> Self {
        Self {
            role: Role::Tool,
            content: content.into(),
            name: None,
            tool_calls: None,
            tool_call_id: Some(tool_call_id.into()),
            metadata: HashMap::new(),
        }
    }
}

/// Ordered list of messages with an optional sliding-window cap.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Conversation {
    #[serde(default)]
    pub messages: Vec<Message>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_messages: Option<usize>,
}

impl Conversation {
    pub fn new(max_messages: Option<usize>) -> Self {
        Self {
            messages: Vec::new(),
            max_messages,
        }
    }

    /// Append a message, trimming oldest if `max_messages` is set.
    pub fn add(&mut self, message: Message) {
        self.messages.push(message);
        if let Some(max) = self.max_messages {
            if self.messages.len() > max {
                let start = self.messages.len() - max;
                self.messages = self.messages[start..].to_vec();
            }
        }
    }

    /// Return the last `n` messages.
    pub fn window(&self, n: usize) -> &[Message] {
        let start = self.messages.len().saturating_sub(n);
        &self.messages[start..]
    }
}

// ---------------------------------------------------------------------------
// Model / tool / telemetry records
// ---------------------------------------------------------------------------

/// Metadata describing a language model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelSpec {
    pub model_id: String,
    pub name: String,
    pub parameter_count_b: f64,
    pub context_length: i64,
    /// MoE active parameters (if applicable).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub active_parameter_count_b: Option<f64>,
    #[serde(default)]
    pub quantization: Quantization,
    #[serde(default)]
    pub min_vram_gb: f64,
    #[serde(default)]
    pub supported_engines: Vec<String>,
    #[serde(default)]
    pub provider: String,
    #[serde(default)]
    pub requires_api_key: bool,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

/// Result returned by a tool invocation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolResult {
    pub tool_name: String,
    pub content: String,
    #[serde(default = "default_true")]
    pub success: bool,
    #[serde(default)]
    pub usage: HashMap<String, serde_json::Value>,
    #[serde(default)]
    pub cost_usd: f64,
    #[serde(default)]
    pub latency_seconds: f64,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

fn default_true() -> bool {
    true
}

impl ToolResult {
    pub fn success(tool_name: impl Into<String>, content: impl Into<String>) -> Self {
        Self {
            tool_name: tool_name.into(),
            content: content.into(),
            success: true,
            usage: HashMap::new(),
            cost_usd: 0.0,
            latency_seconds: 0.0,
            metadata: HashMap::new(),
        }
    }

    pub fn failure(tool_name: impl Into<String>, error: impl Into<String>) -> Self {
        Self {
            tool_name: tool_name.into(),
            content: error.into(),
            success: false,
            usage: HashMap::new(),
            cost_usd: 0.0,
            latency_seconds: 0.0,
            metadata: HashMap::new(),
        }
    }
}

/// Single telemetry observation recorded after an inference call.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TelemetryRecord {
    pub timestamp: f64,
    pub model_id: String,
    #[serde(default)]
    pub prompt_tokens: i64,
    #[serde(default)]
    pub completion_tokens: i64,
    #[serde(default)]
    pub total_tokens: i64,
    #[serde(default)]
    pub latency_seconds: f64,
    /// Time to first token.
    #[serde(default)]
    pub ttft: f64,
    #[serde(default)]
    pub cost_usd: f64,
    #[serde(default)]
    pub energy_joules: f64,
    #[serde(default)]
    pub power_watts: f64,
    #[serde(default)]
    pub gpu_utilization_pct: f64,
    #[serde(default)]
    pub gpu_memory_used_gb: f64,
    #[serde(default)]
    pub gpu_temperature_c: f64,
    #[serde(default)]
    pub throughput_tok_per_sec: f64,
    #[serde(default)]
    pub energy_per_output_token_joules: f64,
    #[serde(default)]
    pub throughput_per_watt: f64,
    #[serde(default)]
    pub prefill_latency_seconds: f64,
    #[serde(default)]
    pub decode_latency_seconds: f64,
    #[serde(default)]
    pub prefill_energy_joules: f64,
    #[serde(default)]
    pub decode_energy_joules: f64,
    #[serde(default)]
    pub mean_itl_ms: f64,
    #[serde(default)]
    pub median_itl_ms: f64,
    #[serde(default)]
    pub p90_itl_ms: f64,
    #[serde(default)]
    pub p95_itl_ms: f64,
    #[serde(default)]
    pub p99_itl_ms: f64,
    #[serde(default)]
    pub std_itl_ms: f64,
    #[serde(default)]
    pub is_streaming: bool,
    #[serde(default)]
    pub engine: String,
    #[serde(default)]
    pub agent: String,
    #[serde(default)]
    pub energy_method: String,
    #[serde(default)]
    pub energy_vendor: String,
    #[serde(default)]
    pub batch_id: String,
    #[serde(default)]
    pub is_warmup: bool,
    #[serde(default)]
    pub cpu_energy_joules: f64,
    #[serde(default)]
    pub gpu_energy_joules: f64,
    #[serde(default)]
    pub dram_energy_joules: f64,
    #[serde(default)]
    pub tokens_per_joule: f64,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

// ---------------------------------------------------------------------------
// Trace types — full interaction-level recording
// ---------------------------------------------------------------------------

fn trace_id() -> String {
    Uuid::new_v4().simple().to_string()[..16].to_string()
}

/// A single step within an agent trace.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TraceStep {
    pub step_type: StepType,
    pub timestamp: f64,
    #[serde(default)]
    pub duration_seconds: f64,
    #[serde(default)]
    pub input: HashMap<String, serde_json::Value>,
    #[serde(default)]
    pub output: HashMap<String, serde_json::Value>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

/// Complete trace of an agent handling a query.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Trace {
    #[serde(default = "trace_id")]
    pub trace_id: String,
    #[serde(default)]
    pub query: String,
    #[serde(default)]
    pub agent: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub engine: String,
    #[serde(default)]
    pub steps: Vec<TraceStep>,
    #[serde(default)]
    pub result: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outcome: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub feedback: Option<f64>,
    #[serde(default)]
    pub started_at: f64,
    #[serde(default)]
    pub ended_at: f64,
    #[serde(default)]
    pub total_tokens: i64,
    #[serde(default)]
    pub total_latency_seconds: f64,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

impl Default for Trace {
    fn default() -> Self {
        Self {
            trace_id: trace_id(),
            query: String::new(),
            agent: String::new(),
            model: String::new(),
            engine: String::new(),
            steps: Vec::new(),
            result: String::new(),
            outcome: None,
            feedback: None,
            started_at: 0.0,
            ended_at: 0.0,
            total_tokens: 0,
            total_latency_seconds: 0.0,
            metadata: HashMap::new(),
        }
    }
}

impl Trace {
    /// Append a step and update running totals.
    pub fn add_step(&mut self, step: TraceStep) {
        self.total_latency_seconds += step.duration_seconds;
        if let Some(tokens) = step.output.get("tokens").and_then(|v| v.as_i64()) {
            self.total_tokens += tokens;
        }
        self.steps.push(step);
    }
}

/// Context describing a query for model routing decisions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoutingContext {
    #[serde(default)]
    pub query: String,
    #[serde(default)]
    pub query_length: usize,
    #[serde(default)]
    pub has_code: bool,
    #[serde(default)]
    pub has_math: bool,
    #[serde(default = "default_language")]
    pub language: String,
    #[serde(default = "default_urgency")]
    pub urgency: f64,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

impl Default for RoutingContext {
    fn default() -> Self {
        Self {
            query: String::new(),
            query_length: 0,
            has_code: false,
            has_math: false,
            language: default_language(),
            urgency: default_urgency(),
            metadata: HashMap::new(),
        }
    }
}

fn default_language() -> String {
    "en".into()
}

fn default_urgency() -> f64 {
    0.5
}

// ---------------------------------------------------------------------------
// Agent context and result types
// ---------------------------------------------------------------------------

/// Runtime context passed to an agent's `run()` method.
#[derive(Debug, Clone, Default)]
pub struct AgentContext {
    pub conversation: Conversation,
    pub tools: Vec<String>,
    pub memory_results: Vec<serde_json::Value>,
    pub metadata: HashMap<String, serde_json::Value>,
}

/// Result returned by an agent's `run()` method.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AgentResult {
    pub content: String,
    #[serde(default)]
    pub tool_results: Vec<ToolResult>,
    #[serde(default)]
    pub turns: usize,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

// ---------------------------------------------------------------------------
// Engine generate result
// ---------------------------------------------------------------------------

/// Token usage statistics from an inference call.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Usage {
    #[serde(default)]
    pub prompt_tokens: i64,
    #[serde(default)]
    pub completion_tokens: i64,
    #[serde(default)]
    pub total_tokens: i64,
}

/// Result of an `InferenceEngine::generate()` call.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GenerateResult {
    pub content: String,
    #[serde(default)]
    pub usage: Usage,
    #[serde(default)]
    pub model: String,
    #[serde(default = "default_finish_reason")]
    pub finish_reason: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_calls: Option<Vec<ToolCall>>,
    #[serde(default)]
    pub ttft: f64,
    #[serde(default)]
    pub cost_usd: f64,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

fn default_finish_reason() -> String {
    "stop".into()
}

impl Default for GenerateResult {
    fn default() -> Self {
        Self {
            content: String::new(),
            usage: Usage::default(),
            model: String::new(),
            finish_reason: default_finish_reason(),
            tool_calls: None,
            ttft: 0.0,
            cost_usd: 0.0,
            metadata: HashMap::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// Tool spec
// ---------------------------------------------------------------------------

/// Metadata describing a tool's capabilities and constraints.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolSpec {
    pub name: String,
    pub description: String,
    /// JSON Schema describing the tool's parameters.
    #[serde(default = "default_empty_object")]
    pub parameters: serde_json::Value,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub cost_estimate: f64,
    #[serde(default)]
    pub latency_estimate: f64,
    #[serde(default)]
    pub requires_confirmation: bool,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: f64,
    #[serde(default)]
    pub required_capabilities: Vec<String>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

fn default_empty_object() -> serde_json::Value {
    serde_json::json!({})
}

fn default_timeout() -> f64 {
    30.0
}

/// A single retrieval result from a memory backend.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetrievalResult {
    pub content: String,
    pub score: f64,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_role_serde_roundtrip() {
        let role = Role::Assistant;
        let json = serde_json::to_string(&role).unwrap();
        assert_eq!(json, "\"assistant\"");
        let parsed: Role = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed, role);
    }

    #[test]
    fn test_message_serde() {
        let msg = Message::user("Hello, world!");
        let json = serde_json::to_string(&msg).unwrap();
        let parsed: Message = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.role, Role::User);
        assert_eq!(parsed.content, "Hello, world!");
    }

    #[test]
    fn test_conversation_sliding_window() {
        let mut conv = Conversation::new(Some(3));
        for i in 0..5 {
            conv.add(Message::user(format!("msg {i}")));
        }
        assert_eq!(conv.messages.len(), 3);
        assert_eq!(conv.messages[0].content, "msg 2");
        assert_eq!(conv.messages[2].content, "msg 4");
    }

    #[test]
    fn test_conversation_window() {
        let mut conv = Conversation::new(None);
        for i in 0..5 {
            conv.add(Message::user(format!("msg {i}")));
        }
        let win = conv.window(2);
        assert_eq!(win.len(), 2);
        assert_eq!(win[0].content, "msg 3");
    }

    #[test]
    fn test_tool_result_success() {
        let r = ToolResult::success("calc", "42");
        assert!(r.success);
        assert_eq!(r.tool_name, "calc");
        assert_eq!(r.content, "42");
    }

    #[test]
    fn test_tool_result_failure() {
        let r = ToolResult::failure("calc", "division by zero");
        assert!(!r.success);
    }

    #[test]
    fn test_trace_add_step() {
        let mut trace = Trace::default();
        let step = TraceStep {
            step_type: StepType::Generate,
            timestamp: 1.0,
            duration_seconds: 0.5,
            input: HashMap::new(),
            output: {
                let mut m = HashMap::new();
                m.insert("tokens".into(), serde_json::json!(100));
                m
            },
            metadata: HashMap::new(),
        };
        trace.add_step(step);
        assert_eq!(trace.total_tokens, 100);
        assert!((trace.total_latency_seconds - 0.5).abs() < 1e-9);
        assert_eq!(trace.steps.len(), 1);
    }

    #[test]
    fn test_telemetry_record_default() {
        let rec = TelemetryRecord::default();
        assert_eq!(rec.prompt_tokens, 0);
        assert_eq!(rec.model_id, "");
    }

    #[test]
    fn test_model_spec_serde() {
        let spec = ModelSpec {
            model_id: "qwen3:8b".into(),
            name: "Qwen 3 8B".into(),
            parameter_count_b: 8.0,
            context_length: 32768,
            active_parameter_count_b: None,
            quantization: Quantization::GgufQ4,
            min_vram_gb: 5.0,
            supported_engines: vec!["ollama".into()],
            provider: "".into(),
            requires_api_key: false,
            metadata: HashMap::new(),
        };
        let json = serde_json::to_string(&spec).unwrap();
        let parsed: ModelSpec = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.model_id, "qwen3:8b");
        assert_eq!(parsed.quantization, Quantization::GgufQ4);
    }

    #[test]
    fn test_routing_context_defaults() {
        let ctx = RoutingContext::default();
        assert_eq!(ctx.language, "en");
        assert!((ctx.urgency - 0.5).abs() < 1e-9);
    }

    #[test]
    fn test_quantization_display() {
        assert_eq!(Quantization::None.to_string(), "none");
        assert_eq!(Quantization::GgufQ4.to_string(), "gguf_q4");
    }

    #[test]
    fn test_tool_spec_defaults() {
        let spec: ToolSpec = serde_json::from_str(
            r#"{"name": "test", "description": "test tool"}"#,
        )
        .unwrap();
        assert_eq!(spec.timeout_seconds, 30.0);
        assert!(!spec.requires_confirmation);
    }
}
