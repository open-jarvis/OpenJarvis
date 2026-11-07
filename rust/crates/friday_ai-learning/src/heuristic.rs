//! HeuristicRouter — rule-based model selection.

use crate::traits::RouterPolicy;
use friday_ai_core::RoutingContext;

pub struct HeuristicRouter {
    default_model: String,
    code_model: Option<String>,
    math_model: Option<String>,
    fast_model: Option<String>,
}

impl HeuristicRouter {
    pub fn new(
        default_model: String,
        code_model: Option<String>,
        math_model: Option<String>,
        fast_model: Option<String>,
    ) -> Self {
        Self {
            default_model,
            code_model,
            math_model,
            fast_model,
        }
    }
}

impl RouterPolicy for HeuristicRouter {
    fn select_model(&self, context: &RoutingContext) -> String {
        if context.has_code {
            if let Some(ref model) = self.code_model {
                return model.clone();
            }
        }
        if context.has_math {
            if let Some(ref model) = self.math_model {
                return model.clone();
            }
        }
        if context.urgency > 0.8 {
            if let Some(ref model) = self.fast_model {
                return model.clone();
            }
        }
        if context.query_length < 20 {
            if let Some(ref model) = self.fast_model {
                return model.clone();
            }
        }
        self.default_model.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_heuristic_code() {
        let router = HeuristicRouter::new(
            "default".into(),
            Some("code_model".into()),
            None,
            None,
        );
        let ctx = RoutingContext {
            has_code: true,
            ..Default::default()
        };
        assert_eq!(router.select_model(&ctx), "code_model");
    }

    #[test]
    fn test_heuristic_default() {
        let router = HeuristicRouter::new("qwen3:8b".into(), None, None, None);
        let ctx = RoutingContext::default();
        assert_eq!(router.select_model(&ctx), "qwen3:8b");
    }
}
