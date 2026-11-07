//! Optimization framework for FridayAI configuration tuning.
//!
//! Provides LLM-guided search over the 5-primitive configuration space,
//! with SQLite-backed trial persistence and Pareto frontier computation.

pub mod engine;
pub mod llm_optimizer;
pub mod search_space;
pub mod store;
pub mod types;

// Re-export key types for convenience.
pub use engine::{compute_pareto_frontier, OptimizationEngine, TrialRunner};
pub use llm_optimizer::{LLMOptimizer, OptimizerBackend};
pub use search_space::{build_search_space, default_search_space};
pub use store::OptimizationStore;
pub use types::{
    BenchmarkScore, DimensionType, Direction, ObjectiveSpec, OptimizationRun, RunStatus,
    SampleScore, SearchDimension, SearchSpace, TrialConfig, TrialFeedback, TrialResult,
};
