//! RouterPolicyEnum — static dispatch over router policy implementations.

use crate::bandit::BanditRouterPolicy;
use crate::grpo::GRPORouterPolicy;
use crate::heuristic::HeuristicRouter;
use crate::traits::RouterPolicy;
use openjarvis_core::RoutingContext;

/// Closed enum of all supported router policies.
pub enum RouterPolicyEnum {
    Heuristic(HeuristicRouter),
    Bandit(BanditRouterPolicy),
    Grpo(GRPORouterPolicy),
}

impl RouterPolicy for RouterPolicyEnum {
    fn select_model(&self, context: &RoutingContext) -> String {
        match self {
            RouterPolicyEnum::Heuristic(r) => r.select_model(context),
            RouterPolicyEnum::Bandit(r) => r.select_model(context),
            RouterPolicyEnum::Grpo(r) => r.select_model(context),
        }
    }
}

impl RouterPolicyEnum {
    /// Convenience: identify the policy variant key.
    pub fn variant_key(&self) -> &str {
        match self {
            RouterPolicyEnum::Heuristic(_) => "heuristic",
            RouterPolicyEnum::Bandit(_) => "bandit",
            RouterPolicyEnum::Grpo(_) => "grpo",
        }
    }
}
