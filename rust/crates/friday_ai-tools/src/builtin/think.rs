//! Think tool — allows the agent to express reasoning steps.

use crate::traits::BaseTool;
use friday_ai_core::{FridayAIError, ToolResult, ToolSpec};
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;

static SPEC: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
    name: "think".into(),
    description: "Express a reasoning step without side effects".into(),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": "The reasoning or thinking step"
            }
        },
        "required": ["thought"]
    }),
    category: "reasoning".into(),
    cost_estimate: 0.0,
    latency_estimate: 0.0,
    requires_confirmation: false,
    timeout_seconds: 1.0,
    required_capabilities: vec![],
    metadata: HashMap::new(),
});

pub struct ThinkTool;

impl BaseTool for ThinkTool {
    fn tool_id(&self) -> &str {
        "think"
    }

    fn spec(&self) -> &ToolSpec {
        &SPEC
    }

    fn execute(&self, params: &Value) -> Result<ToolResult, FridayAIError> {
        let thought = params["thought"].as_str().unwrap_or("(empty thought)");
        Ok(ToolResult::success("think", thought))
    }
}
