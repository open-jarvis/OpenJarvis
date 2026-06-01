//! Calculator tool — evaluate mathematical expressions.

use crate::traits::BaseTool;
use openjarvis_core::{OpenJarvisError, ToolResult, ToolSpec};
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;

static SPEC: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
    name: "calculator".into(),
    description: "Evaluate a mathematical expression".into(),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression to evaluate"
            }
        },
        "required": ["expression"]
    }),
    category: "math".into(),
    cost_estimate: 0.0,
    latency_estimate: 0.0,
    requires_confirmation: false,
    timeout_seconds: 5.0,
    required_capabilities: vec![],
    metadata: HashMap::new(),
});

pub struct CalculatorTool;

impl BaseTool for CalculatorTool {
    fn tool_id(&self) -> &str {
        "calculator"
    }

    fn spec(&self) -> &ToolSpec {
        &SPEC
    }

    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let expression = params["expression"]
            .as_str()
            .unwrap_or("");

        match meval::eval_str(expression) {
            Ok(result) => Ok(ToolResult::success("calculator", result.to_string())),
            Err(e) => Ok(ToolResult::failure(
                "calculator",
                format!("Error evaluating '{expression}': {e}"),
            )),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_calculator_basic() {
        let tool = CalculatorTool;
        let result = tool
            .execute(&serde_json::json!({"expression": "2 + 2"}))
            .unwrap();
        assert!(result.success);
        assert_eq!(result.content, "4");
    }

    #[test]
    fn test_calculator_complex() {
        let tool = CalculatorTool;
        let result = tool
            .execute(&serde_json::json!({"expression": "sin(3.14159/2)"}))
            .unwrap();
        assert!(result.success);
        let val: f64 = result.content.parse().unwrap();
        assert!((val - 1.0).abs() < 0.01);
    }

    #[test]
    fn test_calculator_error() {
        let tool = CalculatorTool;
        let result = tool
            .execute(&serde_json::json!({"expression": "invalid"}))
            .unwrap();
        assert!(!result.success);
    }
}
