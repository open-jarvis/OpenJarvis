//! Agents primitive — pluggable agent logic for queries, tool calls, memory.

pub mod helpers;
pub mod loop_guard;
pub mod monitor_operative;
pub mod native_openhands;
pub mod native_react;
pub mod orchestrator;
pub mod simple;
pub mod traits;
pub mod utils;

pub use helpers::AgentHelpers;
pub use loop_guard::LoopGuard;
pub use monitor_operative::{
    MemoryExtraction, MonitorConfig, MonitorOperativeAgent, ObservationCompression,
    RetrievalStrategy, TaskDecomposition,
};
pub use native_openhands::NativeOpenHandsAgent;
pub use native_react::NativeReActAgent;
pub use orchestrator::OrchestratorAgent;
pub use simple::SimpleAgent;
pub use traits::OjAgent;
