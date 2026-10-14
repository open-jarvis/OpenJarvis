//! Configuration loading and TOML deserialization.
//!
//! Rust translation of `src/openjarvis/core/config.py`.
//! All config structs use `#[serde(default)]` for backward compatibility.

use crate::error::ConfigError;
use crate::hardware::{detect_hardware, recommend_engine, HardwareInfo};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// Default config directory: `~/.openjarvis/`
pub fn default_config_dir() -> PathBuf {
    dirs_home().join(".openjarvis")
}

/// Default config file path: `~/.openjarvis/config.toml`
pub fn default_config_path() -> PathBuf {
    default_config_dir().join("config.toml")
}

fn dirs_home() -> PathBuf {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("."))
}

fn default_config_dir_str() -> String {
    default_config_dir().to_string_lossy().into_owned()
}

// ---------------------------------------------------------------------------
// Per-engine configs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OllamaEngineConfig {
    #[serde(default = "default_ollama_host")]
    pub host: String,
}

fn default_ollama_host() -> String {
    "http://localhost:11434".into()
}

impl Default for OllamaEngineConfig {
    fn default() -> Self {
        Self { host: default_ollama_host() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VLLMEngineConfig {
    #[serde(default = "default_vllm_host")]
    pub host: String,
}

fn default_vllm_host() -> String {
    "http://localhost:8000".into()
}

impl Default for VLLMEngineConfig {
    fn default() -> Self {
        Self { host: default_vllm_host() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SGLangEngineConfig {
    #[serde(default = "default_sglang_host")]
    pub host: String,
}

fn default_sglang_host() -> String {
    "http://localhost:30000".into()
}

impl Default for SGLangEngineConfig {
    fn default() -> Self {
        Self { host: default_sglang_host() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlamaCppEngineConfig {
    #[serde(default = "default_llamacpp_host")]
    pub host: String,
    #[serde(default)]
    pub binary_path: String,
}

fn default_llamacpp_host() -> String {
    "http://localhost:8080".into()
}

impl Default for LlamaCppEngineConfig {
    fn default() -> Self {
        Self {
            host: default_llamacpp_host(),
            binary_path: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MLXEngineConfig {
    #[serde(default = "default_mlx_host")]
    pub host: String,
}

fn default_mlx_host() -> String {
    "http://localhost:8080".into()
}

impl Default for MLXEngineConfig {
    fn default() -> Self {
        Self { host: default_mlx_host() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LMStudioEngineConfig {
    #[serde(default = "default_lmstudio_host")]
    pub host: String,
}

fn default_lmstudio_host() -> String {
    "http://localhost:1234".into()
}

impl Default for LMStudioEngineConfig {
    fn default() -> Self {
        Self { host: default_lmstudio_host() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExoEngineConfig {
    #[serde(default = "default_exo_host")]
    pub host: String,
}

fn default_exo_host() -> String {
    "http://localhost:52415".into()
}

impl Default for ExoEngineConfig {
    fn default() -> Self {
        Self { host: default_exo_host() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NexaEngineConfig {
    #[serde(default = "default_nexa_host")]
    pub host: String,
    #[serde(default)]
    pub device: String,
}

fn default_nexa_host() -> String {
    "http://localhost:18181".into()
}

impl Default for NexaEngineConfig {
    fn default() -> Self {
        Self {
            host: default_nexa_host(),
            device: String::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UzuEngineConfig {
    #[serde(default = "default_uzu_host")]
    pub host: String,
}

fn default_uzu_host() -> String {
    "http://localhost:8080".into()
}

impl Default for UzuEngineConfig {
    fn default() -> Self {
        Self { host: default_uzu_host() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppleFmEngineConfig {
    #[serde(default = "default_apple_fm_host")]
    pub host: String,
}

fn default_apple_fm_host() -> String {
    "http://localhost:8079".into()
}

impl Default for AppleFmEngineConfig {
    fn default() -> Self {
        Self { host: default_apple_fm_host() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FoundryLocalEngineConfig {
    #[serde(default = "default_foundry_local_host")]
    pub host: String,
}

fn default_foundry_local_host() -> String {
    "http://localhost:5273".into()
}

impl Default for FoundryLocalEngineConfig {
    fn default() -> Self {
        Self {
            host: default_foundry_local_host(),
        }
    }
}

// ---------------------------------------------------------------------------
// Engine config
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineConfig {
    #[serde(default = "default_engine_name")]
    pub default: String,
    #[serde(default)]
    pub ollama: OllamaEngineConfig,
    #[serde(default)]
    pub vllm: VLLMEngineConfig,
    #[serde(default)]
    pub sglang: SGLangEngineConfig,
    #[serde(default)]
    pub llamacpp: LlamaCppEngineConfig,
    #[serde(default)]
    pub mlx: MLXEngineConfig,
    #[serde(default)]
    pub lmstudio: LMStudioEngineConfig,
    #[serde(default)]
    pub exo: ExoEngineConfig,
    #[serde(default)]
    pub nexa: NexaEngineConfig,
    #[serde(default)]
    pub uzu: UzuEngineConfig,
    #[serde(default)]
    pub apple_fm: AppleFmEngineConfig,
    #[serde(default)]
    pub foundry_local: FoundryLocalEngineConfig,
    #[serde(default)]
    pub allow_cloud: bool,
}

fn default_engine_name() -> String {
    "ollama".into()
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            default: default_engine_name(),
            ollama: OllamaEngineConfig::default(),
            vllm: VLLMEngineConfig::default(),
            sglang: SGLangEngineConfig::default(),
            llamacpp: LlamaCppEngineConfig::default(),
            mlx: MLXEngineConfig::default(),
            lmstudio: LMStudioEngineConfig::default(),
            exo: ExoEngineConfig::default(),
            nexa: NexaEngineConfig::default(),
            uzu: UzuEngineConfig::default(),
            apple_fm: AppleFmEngineConfig::default(),
            foundry_local: FoundryLocalEngineConfig::default(),
            allow_cloud: false,
        }
    }
}

// ---------------------------------------------------------------------------
// Intelligence config
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IntelligenceConfig {
    #[serde(default)]
    pub default_model: String,
    #[serde(default)]
    pub fallback_model: String,
    #[serde(default)]
    pub model_path: String,
    #[serde(default)]
    pub checkpoint_path: String,
    #[serde(default = "default_quantization_str")]
    pub quantization: String,
    #[serde(default)]
    pub preferred_engine: String,
    #[serde(default)]
    pub provider: String,
    #[serde(default = "default_temperature")]
    pub temperature: f64,
    #[serde(default = "default_max_tokens")]
    pub max_tokens: i64,
    #[serde(default = "default_top_p")]
    pub top_p: f64,
    #[serde(default = "default_top_k")]
    pub top_k: i64,
    #[serde(default = "default_repetition_penalty")]
    pub repetition_penalty: f64,
    #[serde(default)]
    pub stop_sequences: String,
}

fn default_quantization_str() -> String { "none".into() }
fn default_temperature() -> f64 { 0.7 }
fn default_max_tokens() -> i64 { 1024 }
fn default_top_p() -> f64 { 0.9 }
fn default_top_k() -> i64 { 40 }
fn default_repetition_penalty() -> f64 { 1.0 }

impl Default for IntelligenceConfig {
    fn default() -> Self {
        Self {
            default_model: String::new(),
            fallback_model: String::new(),
            model_path: String::new(),
            checkpoint_path: String::new(),
            quantization: default_quantization_str(),
            preferred_engine: String::new(),
            provider: String::new(),
            temperature: default_temperature(),
            max_tokens: default_max_tokens(),
            top_p: default_top_p(),
            top_k: default_top_k(),
            repetition_penalty: default_repetition_penalty(),
            stop_sequences: String::new(),
        }
    }
}

// ---------------------------------------------------------------------------
// Learning config hierarchy
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoutingLearningConfig {
    #[serde(default = "default_heuristic")]
    pub policy: String,
    #[serde(default = "default_min_samples")]
    pub min_samples: i64,
}

fn default_heuristic() -> String { "heuristic".into() }
fn default_min_samples() -> i64 { 5 }

impl Default for RoutingLearningConfig {
    fn default() -> Self {
        Self { policy: default_heuristic(), min_samples: default_min_samples() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct IntelligenceLearningConfig {
    #[serde(default = "default_none_str")]
    pub policy: String,
}

fn default_none_str() -> String { "none".into() }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentLearningConfig {
    #[serde(default = "default_none_str")]
    pub policy: String,
    #[serde(default = "default_max_icl")]
    pub max_icl_examples: i64,
    #[serde(default = "default_advisor_threshold")]
    pub advisor_confidence_threshold: f64,
}

fn default_max_icl() -> i64 { 20 }
fn default_advisor_threshold() -> f64 { 0.7 }

impl Default for AgentLearningConfig {
    fn default() -> Self {
        Self {
            policy: default_none_str(),
            max_icl_examples: default_max_icl(),
            advisor_confidence_threshold: default_advisor_threshold(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MetricsConfig {
    #[serde(default = "default_accuracy_weight")]
    pub accuracy_weight: f64,
    #[serde(default = "default_latency_weight")]
    pub latency_weight: f64,
    #[serde(default = "default_cost_weight")]
    pub cost_weight: f64,
    #[serde(default = "default_efficiency_weight")]
    pub efficiency_weight: f64,
}

fn default_accuracy_weight() -> f64 { 0.6 }
fn default_latency_weight() -> f64 { 0.2 }
fn default_cost_weight() -> f64 { 0.1 }
fn default_efficiency_weight() -> f64 { 0.1 }

impl Default for MetricsConfig {
    fn default() -> Self {
        Self {
            accuracy_weight: default_accuracy_weight(),
            latency_weight: default_latency_weight(),
            cost_weight: default_cost_weight(),
            efficiency_weight: default_efficiency_weight(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LearningConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_update_interval")]
    pub update_interval: i64,
    #[serde(default)]
    pub auto_update: bool,
    #[serde(default)]
    pub routing: RoutingLearningConfig,
    #[serde(default)]
    pub intelligence: IntelligenceLearningConfig,
    #[serde(default)]
    pub agent: AgentLearningConfig,
    #[serde(default)]
    pub metrics: MetricsConfig,
    #[serde(default)]
    pub training_enabled: bool,
    #[serde(default)]
    pub training_schedule: String,
    #[serde(default = "default_lora_rank")]
    pub lora_rank: i64,
    #[serde(default = "default_lora_alpha")]
    pub lora_alpha: i64,
    #[serde(default = "default_min_sft_pairs")]
    pub min_sft_pairs: i64,
    #[serde(default = "default_min_improvement")]
    pub min_improvement: f64,
}

fn default_update_interval() -> i64 { 100 }
fn default_lora_rank() -> i64 { 16 }
fn default_lora_alpha() -> i64 { 32 }
fn default_min_sft_pairs() -> i64 { 50 }
fn default_min_improvement() -> f64 { 0.02 }

impl Default for LearningConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            update_interval: default_update_interval(),
            auto_update: false,
            routing: RoutingLearningConfig::default(),
            intelligence: IntelligenceLearningConfig::default(),
            agent: AgentLearningConfig::default(),
            metrics: MetricsConfig::default(),
            training_enabled: false,
            training_schedule: String::new(),
            lora_rank: default_lora_rank(),
            lora_alpha: default_lora_alpha(),
            min_sft_pairs: default_min_sft_pairs(),
            min_improvement: default_min_improvement(),
        }
    }
}

// ---------------------------------------------------------------------------
// Tools config
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageConfig {
    #[serde(default = "default_sqlite")]
    pub default_backend: String,
    #[serde(default = "default_memory_db_path")]
    pub db_path: String,
    #[serde(default = "default_context_top_k")]
    pub context_top_k: i64,
    #[serde(default = "default_context_min_score")]
    pub context_min_score: f64,
    #[serde(default = "default_context_max_tokens")]
    pub context_max_tokens: i64,
    #[serde(default = "default_chunk_size")]
    pub chunk_size: i64,
    #[serde(default = "default_chunk_overlap")]
    pub chunk_overlap: i64,
}

fn default_sqlite() -> String { "sqlite".into() }
fn default_memory_db_path() -> String { format!("{}/memory.db", default_config_dir_str()) }
fn default_context_top_k() -> i64 { 5 }
fn default_context_min_score() -> f64 { 0.1 }
fn default_context_max_tokens() -> i64 { 2048 }
fn default_chunk_size() -> i64 { 512 }
fn default_chunk_overlap() -> i64 { 64 }

impl Default for StorageConfig {
    fn default() -> Self {
        Self {
            default_backend: default_sqlite(),
            db_path: default_memory_db_path(),
            context_top_k: default_context_top_k(),
            context_min_score: default_context_min_score(),
            context_max_tokens: default_context_max_tokens(),
            chunk_size: default_chunk_size(),
            chunk_overlap: default_chunk_overlap(),
        }
    }
}

/// Backward-compat alias.
pub type MemoryConfig = StorageConfig;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MCPConfig {
    #[serde(default = "default_true_val")]
    pub enabled: bool,
    #[serde(default)]
    pub servers: String,
}

fn default_true_val() -> bool { true }

impl Default for MCPConfig {
    fn default() -> Self {
        Self { enabled: true, servers: String::new() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BrowserConfig {
    #[serde(default = "default_true_val")]
    pub headless: bool,
    #[serde(default = "default_browser_timeout")]
    pub timeout_ms: i64,
    #[serde(default = "default_viewport_width")]
    pub viewport_width: i64,
    #[serde(default = "default_viewport_height")]
    pub viewport_height: i64,
}

fn default_browser_timeout() -> i64 { 30000 }
fn default_viewport_width() -> i64 { 1280 }
fn default_viewport_height() -> i64 { 720 }

impl Default for BrowserConfig {
    fn default() -> Self {
        Self {
            headless: true,
            timeout_ms: default_browser_timeout(),
            viewport_width: default_viewport_width(),
            viewport_height: default_viewport_height(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ToolsConfig {
    #[serde(default)]
    pub storage: StorageConfig,
    #[serde(default)]
    pub mcp: MCPConfig,
    #[serde(default)]
    pub browser: BrowserConfig,
    #[serde(default)]
    pub enabled: String,
}

// ---------------------------------------------------------------------------
// Agent config
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentConfig {
    #[serde(default = "default_simple")]
    pub default_agent: String,
    #[serde(default = "default_max_turns")]
    pub max_turns: i64,
    #[serde(default)]
    pub tools: String,
    #[serde(default)]
    pub objective: String,
    #[serde(default)]
    pub system_prompt: String,
    #[serde(default)]
    pub system_prompt_path: String,
    #[serde(default = "default_true_val")]
    pub context_from_memory: bool,
}

fn default_simple() -> String { "simple".into() }
fn default_max_turns() -> i64 { 10 }

impl Default for AgentConfig {
    fn default() -> Self {
        Self {
            default_agent: default_simple(),
            max_turns: default_max_turns(),
            tools: String::new(),
            objective: String::new(),
            system_prompt: String::new(),
            system_prompt_path: String::new(),
            context_from_memory: true,
        }
    }
}

// ---------------------------------------------------------------------------
// Server, telemetry, traces, security, etc.
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerConfig {
    #[serde(default = "default_server_host")]
    pub host: String,
    #[serde(default = "default_server_port")]
    pub port: i64,
    #[serde(default = "default_orchestrator")]
    pub agent: String,
    #[serde(default)]
    pub model: String,
    #[serde(default = "default_one")]
    pub workers: i64,
}

fn default_server_host() -> String { "0.0.0.0".into() }
fn default_server_port() -> i64 { 8000 }
fn default_orchestrator() -> String { "orchestrator".into() }
fn default_one() -> i64 { 1 }

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            host: default_server_host(),
            port: default_server_port(),
            agent: default_orchestrator(),
            model: String::new(),
            workers: default_one(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryConfig {
    #[serde(default = "default_true_val")]
    pub enabled: bool,
    #[serde(default = "default_telemetry_db")]
    pub db_path: String,
    #[serde(default)]
    pub gpu_metrics: bool,
    #[serde(default = "default_gpu_poll")]
    pub gpu_poll_interval_ms: i64,
    #[serde(default)]
    pub energy_vendor: String,
    #[serde(default)]
    pub warmup_samples: i64,
    #[serde(default = "default_ss_window")]
    pub steady_state_window: i64,
    #[serde(default = "default_ss_threshold")]
    pub steady_state_threshold: f64,
}

fn default_telemetry_db() -> String { format!("{}/telemetry.db", default_config_dir_str()) }
fn default_gpu_poll() -> i64 { 50 }
fn default_ss_window() -> i64 { 5 }
fn default_ss_threshold() -> f64 { 0.05 }

impl Default for TelemetryConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            db_path: default_telemetry_db(),
            gpu_metrics: false,
            gpu_poll_interval_ms: default_gpu_poll(),
            energy_vendor: String::new(),
            warmup_samples: 0,
            steady_state_window: default_ss_window(),
            steady_state_threshold: default_ss_threshold(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TracesConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_traces_db")]
    pub db_path: String,
}

fn default_traces_db() -> String { format!("{}/traces.db", default_config_dir_str()) }

impl Default for TracesConfig {
    fn default() -> Self {
        Self { enabled: false, db_path: default_traces_db() }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct CapabilitiesConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub policy_path: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecurityConfig {
    #[serde(default = "default_true_val")]
    pub enabled: bool,
    #[serde(default = "default_true_val")]
    pub scan_input: bool,
    #[serde(default = "default_true_val")]
    pub scan_output: bool,
    #[serde(default = "default_warn")]
    pub mode: String,
    #[serde(default = "default_true_val")]
    pub secret_scanner: bool,
    #[serde(default = "default_true_val")]
    pub pii_scanner: bool,
    #[serde(default = "default_audit_log")]
    pub audit_log_path: String,
    #[serde(default = "default_true_val")]
    pub enforce_tool_confirmation: bool,
    #[serde(default = "default_true_val")]
    pub merkle_audit: bool,
    #[serde(default)]
    pub signing_key_path: String,
    #[serde(default = "default_true_val")]
    pub ssrf_protection: bool,
    #[serde(default)]
    pub rate_limit_enabled: bool,
    #[serde(default = "default_rpm")]
    pub rate_limit_rpm: i64,
    #[serde(default = "default_burst")]
    pub rate_limit_burst: i64,
    #[serde(default)]
    pub capabilities: CapabilitiesConfig,
}

fn default_warn() -> String { "warn".into() }
fn default_audit_log() -> String { format!("{}/audit.db", default_config_dir_str()) }
fn default_rpm() -> i64 { 60 }
fn default_burst() -> i64 { 10 }

impl Default for SecurityConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            scan_input: true,
            scan_output: true,
            mode: default_warn(),
            secret_scanner: true,
            pii_scanner: true,
            audit_log_path: default_audit_log(),
            enforce_tool_confirmation: true,
            merkle_audit: true,
            signing_key_path: String::new(),
            ssrf_protection: true,
            rate_limit_enabled: false,
            rate_limit_rpm: default_rpm(),
            rate_limit_burst: default_burst(),
            capabilities: CapabilitiesConfig::default(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SandboxConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_sandbox_image")]
    pub image: String,
    #[serde(default = "default_sandbox_timeout")]
    pub timeout: i64,
    #[serde(default)]
    pub workspace: String,
    #[serde(default)]
    pub mount_allowlist_path: String,
    #[serde(default = "default_max_concurrent")]
    pub max_concurrent: i64,
    #[serde(default = "default_docker")]
    pub runtime: String,
    #[serde(default = "default_wasm_fuel")]
    pub wasm_fuel_limit: i64,
    #[serde(default = "default_wasm_mem")]
    pub wasm_memory_limit_mb: i64,
}

fn default_sandbox_image() -> String { "openjarvis-sandbox:latest".into() }
fn default_sandbox_timeout() -> i64 { 300 }
fn default_max_concurrent() -> i64 { 5 }
fn default_docker() -> String { "docker".into() }
fn default_wasm_fuel() -> i64 { 1_000_000 }
fn default_wasm_mem() -> i64 { 256 }

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SchedulerConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_poll_interval")]
    pub poll_interval: i64,
    #[serde(default)]
    pub db_path: String,
}

fn default_poll_interval() -> i64 { 60 }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkflowConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_max_parallel")]
    pub max_parallel: i64,
    #[serde(default = "default_node_timeout")]
    pub default_node_timeout: i64,
}

fn default_max_parallel() -> i64 { 4 }
fn default_node_timeout() -> i64 { 300 }

impl Default for WorkflowConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            max_parallel: default_max_parallel(),
            default_node_timeout: default_node_timeout(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_max_age")]
    pub max_age_hours: f64,
    #[serde(default = "default_consolidation")]
    pub consolidation_threshold: i64,
    #[serde(default = "default_sessions_db")]
    pub db_path: String,
}

fn default_max_age() -> f64 { 24.0 }
fn default_consolidation() -> i64 { 100 }
fn default_sessions_db() -> String { format!("{}/sessions.db", default_config_dir_str()) }

impl Default for SessionConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            max_age_hours: default_max_age(),
            consolidation_threshold: default_consolidation(),
            db_path: default_sessions_db(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct A2AConfig {
    #[serde(default)]
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct OperatorsConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default = "default_operators_dir")]
    pub manifests_dir: String,
    #[serde(default)]
    pub auto_activate: String,
}

fn default_operators_dir() -> String { "~/.openjarvis/operators".into() }

// ---------------------------------------------------------------------------
// Channel configs (kept minimal — channels stay in Python)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ChannelConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub default_channel: String,
    #[serde(default = "default_simple")]
    pub default_agent: String,
    // Channel sub-configs are flattened as serde_json::Value since
    // channels stay in Python. Only the top-level fields matter for Rust.
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, serde_json::Value>,
}

// ---------------------------------------------------------------------------
// Top-level JarvisConfig
// ---------------------------------------------------------------------------

/// Top-level configuration for OpenJarvis.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct JarvisConfig {
    #[serde(skip)]
    pub hardware: HardwareInfo,
    #[serde(default)]
    pub engine: EngineConfig,
    #[serde(default)]
    pub intelligence: IntelligenceConfig,
    #[serde(default)]
    pub learning: LearningConfig,
    #[serde(default)]
    pub tools: ToolsConfig,
    #[serde(default)]
    pub agent: AgentConfig,
    #[serde(default)]
    pub server: ServerConfig,
    #[serde(default)]
    pub telemetry: TelemetryConfig,
    #[serde(default)]
    pub traces: TracesConfig,
    #[serde(default)]
    pub channel: ChannelConfig,
    #[serde(default)]
    pub security: SecurityConfig,
    #[serde(default)]
    pub sandbox: SandboxConfig,
    #[serde(default)]
    pub scheduler: SchedulerConfig,
    #[serde(default)]
    pub workflow: WorkflowConfig,
    #[serde(default)]
    pub sessions: SessionConfig,
    #[serde(default)]
    pub a2a: A2AConfig,
    #[serde(default)]
    pub operators: OperatorsConfig,
}

// ---------------------------------------------------------------------------
// TOML loading
// ---------------------------------------------------------------------------

/// Detect hardware, build defaults, overlay TOML overrides.
pub fn load_config(path: Option<&Path>) -> Result<JarvisConfig, ConfigError> {
    let hw = detect_hardware();
    let recommended_engine = recommend_engine(&hw);

    let config_path = path
        .map(PathBuf::from)
        .unwrap_or_else(default_config_path);

    let mut cfg = if config_path.exists() {
        let content = std::fs::read_to_string(&config_path)?;
        let mut cfg: JarvisConfig = toml::from_str(&content)?;
        // If the TOML didn't set a default engine, use the recommended one
        if cfg.engine.default == default_engine_name() || cfg.engine.default.is_empty() {
            cfg.engine.default = recommended_engine;
        }
        cfg
    } else {
        let mut cfg = JarvisConfig::default();
        cfg.engine.default = recommended_engine;
        cfg
    };

    cfg.hardware = hw;
    Ok(cfg)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let cfg = JarvisConfig::default();
        assert_eq!(cfg.engine.default, "ollama");
        assert_eq!(cfg.intelligence.temperature, 0.7);
        assert_eq!(cfg.intelligence.max_tokens, 1024);
        assert_eq!(cfg.agent.default_agent, "simple");
        assert_eq!(cfg.agent.max_turns, 10);
        assert!(cfg.security.enabled);
        assert_eq!(cfg.learning.routing.policy, "heuristic");
    }

    #[test]
    fn test_config_from_toml() {
        let toml_str = r#"
[engine]
default = "vllm"

[engine.ollama]
host = "http://custom:11434"

[intelligence]
temperature = 0.5
max_tokens = 2048

[agent]
default_agent = "orchestrator"
tools = "calculator,think"

[security]
mode = "block"
"#;
        let cfg: JarvisConfig = toml::from_str(toml_str).unwrap();
        assert_eq!(cfg.engine.default, "vllm");
        assert_eq!(cfg.engine.ollama.host, "http://custom:11434");
        assert_eq!(cfg.intelligence.temperature, 0.5);
        assert_eq!(cfg.intelligence.max_tokens, 2048);
        assert_eq!(cfg.agent.default_agent, "orchestrator");
        assert_eq!(cfg.agent.tools, "calculator,think");
        assert_eq!(cfg.security.mode, "block");
    }

    #[test]
    fn test_config_missing_sections_use_defaults() {
        let toml_str = r#"
[engine]
default = "mlx"
"#;
        let cfg: JarvisConfig = toml::from_str(toml_str).unwrap();
        assert_eq!(cfg.engine.default, "mlx");
        // Everything else should be defaults
        assert_eq!(cfg.intelligence.temperature, 0.7);
        assert!(cfg.telemetry.enabled);
        assert!(!cfg.traces.enabled);
    }

    #[test]
    fn test_nested_learning_config() {
        let toml_str = r#"
[learning]
enabled = true
update_interval = 50

[learning.routing]
policy = "grpo"

[learning.metrics]
accuracy_weight = 0.8
latency_weight = 0.1
"#;
        let cfg: JarvisConfig = toml::from_str(toml_str).unwrap();
        assert!(cfg.learning.enabled);
        assert_eq!(cfg.learning.update_interval, 50);
        assert_eq!(cfg.learning.routing.policy, "grpo");
        assert_eq!(cfg.learning.metrics.accuracy_weight, 0.8);
        assert_eq!(cfg.learning.metrics.latency_weight, 0.1);
        // Defaults preserved for unset fields
        assert_eq!(cfg.learning.metrics.cost_weight, 0.1);
    }

    #[test]
    fn test_storage_config() {
        let toml_str = r#"
[tools.storage]
default_backend = "faiss"
chunk_size = 256
"#;
        let cfg: JarvisConfig = toml::from_str(toml_str).unwrap();
        assert_eq!(cfg.tools.storage.default_backend, "faiss");
        assert_eq!(cfg.tools.storage.chunk_size, 256);
        assert_eq!(cfg.tools.storage.chunk_overlap, 64); // default
    }
}
