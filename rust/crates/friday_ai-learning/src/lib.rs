//! Learning — router policies, bandits, GRPO, trace-driven learning.
//!
//! ML training pipelines (LoRA, SFT, GRPO trainers) stay in Python.

pub mod agent_advisor;
pub mod agent_evolver;
pub mod bandit;
pub mod grpo;
pub mod heuristic;
pub mod heuristic_reward;
pub mod icl_updater;
pub mod learning_orchestrator;
pub mod optimize;
pub mod orchestrator_types;
pub mod reward;
pub mod router_enum;
pub mod sft_policy;
pub mod skill_discovery;
pub mod trace_policy;
pub mod training_data;
pub mod traits;

pub use agent_advisor::{AgentAdvisorPolicy, Recommendation, TraceInfo};
pub use agent_evolver::{AgentConfigEvolver, AgentConfigRecommendation, EvolutionTraceData};
pub use bandit::BanditRouterPolicy;
pub use grpo::GRPORouterPolicy;
pub use heuristic::HeuristicRouter;
pub use heuristic_reward::HeuristicRewardFunction;
pub use icl_updater::{DiscoveredSequence, ICLExample, ICLUpdaterPolicy};
pub use learning_orchestrator::{LearningCycleResult, LearningOrchestrator};
pub use orchestrator_types::{
    Episode, EpisodeState, EpisodeStep, OrchestratorAction, OrchestratorObservation, PolicyOutput,
};
pub use reward::{AdaptiveRewardWeights, MultiObjectiveReward, Normalizers, RewardWeights};
pub use router_enum::RouterPolicyEnum;
pub use sft_policy::SFTRouterPolicy;
pub use skill_discovery::{DiscoveredSkill, SkillDiscovery};
pub use trace_policy::{classify_query, TraceDrivenPolicy};
pub use training_data::{AgentConfigPair, MinerTraceData, RoutingRecommendation, SFTPair, TrainingDataMiner};
pub use traits::{LearningPolicy, RouterPolicy};
