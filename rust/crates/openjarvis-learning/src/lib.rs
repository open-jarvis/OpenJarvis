//! Learning — router policies, bandits, GRPO, trace-driven learning.
//!
//! ML training pipelines (LoRA, SFT, GRPO trainers) stay in Python.

pub mod bandit;
pub mod grpo;
pub mod heuristic;
pub mod router_enum;
pub mod traits;

pub use bandit::BanditRouterPolicy;
pub use grpo::GRPORouterPolicy;
pub use heuristic::HeuristicRouter;
pub use router_enum::RouterPolicyEnum;
pub use traits::{LearningPolicy, RouterPolicy};
