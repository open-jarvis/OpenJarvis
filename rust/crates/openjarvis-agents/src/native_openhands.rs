//! NativeOpenHandsAgent -- CodeAct-style agent that uses code actions.
//!
//! Generates and dispatches code (Python blocks) and tool calls to accomplish
//! tasks.  Mirrors the Python ``NativeOpenHandsAgent`` which supports both
//! ``Action: / Action Input:`` structured tool calls and fenced
//! ````python`` code blocks executed via the ``code_interpreter`` tool.

use crate::loop_guard::LoopGuard;
use crate::traits::OjAgent;
use crate::utils::strip_think_tags;
use openjarvis_core::{AgentContext, AgentResult, OpenJarvisError, ToolResult};
use openjarvis_tools::executor::ToolExecutor;
use regex::Regex;
use rig::agent::AgentBuilder;
use rig::completion::message::Message as RigMessage;
use rig::completion::request::{Chat, CompletionModel};
use std::collections::HashMap;
use std::sync::Arc;

// ---------------------------------------------------------------------------
// System prompt
// ---------------------------------------------------------------------------

const OPENHANDS_SYSTEM_PROMPT: &str = "\
You are an AI assistant with access to tools. \
You MUST use tools when they would help answer the user's question.

## How to use tools

To call a tool, write on its own lines:

Action: <tool_name>
Action Input: <json_arguments>

You will receive the result, then continue your response.

## Available tools

{tool_list}

## Important rules

- When the user asks you to look up, search, fetch, or summarize a URL or \
topic, you MUST use web_search. Do NOT say you cannot browse the web.
- When the user provides a URL, pass the FULL URL (including https://) as the \
query to web_search. Do NOT rewrite URLs into search keywords.
- When the user asks a math question, use calculator.
- When the user asks to read a file, use file_read.
- You CAN write Python code in ```python blocks and it will be executed. Use \
this for computation, data processing, or when no specific tool fits.
- If no tool or code is needed, respond directly with your answer.
- Do NOT include <think> tags or internal reasoning in your response. Respond \
directly.";

// ---------------------------------------------------------------------------
// Agent implementation
// ---------------------------------------------------------------------------

/// Native CodeAct agent -- generates and executes code actions (shell commands,
/// file edits) and structured tool calls to accomplish tasks.
///
/// Supports two action formats:
/// 1. `Action: tool_name` / `Action Input: {json}` -- dispatched to the
///    `ToolExecutor`.
/// 2. Fenced ````python` code blocks -- dispatched to the `code_interpreter`
///    tool.
pub struct NativeOpenHandsAgent<M: CompletionModel> {
    agent: rig::agent::Agent<M>,
    executor: Arc<ToolExecutor>,
    max_turns: usize,
}

impl<M: CompletionModel> NativeOpenHandsAgent<M> {
    pub fn new(
        model: M,
        executor: Arc<ToolExecutor>,
        max_turns: usize,
        temperature: f64,
    ) -> Self {
        let tool_list = executor.list_tools().join(", ");
        let system_prompt = OPENHANDS_SYSTEM_PROMPT.replace("{tool_list}", &tool_list);

        let agent = AgentBuilder::new(model)
            .preamble(&system_prompt)
            .temperature(temperature)
            .build();

        Self {
            agent,
            executor,
            max_turns,
        }
    }

    /// Parse `Action:` and `Action Input:` lines from model output.
    fn parse_action(text: &str) -> Option<(String, String)> {
        let action_re = Regex::new(r"(?mi)^Action:\s*(.+)$").unwrap();
        let input_re = Regex::new(r"(?mi)^Action Input:\s*(.+?)(?:\n\n|\z)").unwrap();

        let action = action_re
            .captures(text)?
            .get(1)?
            .as_str()
            .trim()
            .to_string();
        let input = input_re
            .captures(text)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().trim().to_string())
            .unwrap_or_else(|| "{}".to_string());

        Some((action, input))
    }

    /// Extract Python code from fenced ````python` blocks.
    fn extract_code(text: &str) -> Option<String> {
        let re = Regex::new(r"(?s)```python\n(.*?)```").unwrap();
        re.captures(text)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().trim().to_string())
    }

    /// Remove raw tool-call artifacts from final output text.
    fn strip_tool_call_text(text: &str) -> String {
        // Remove Action: ... Action Input: ... blocks
        let action_re =
            Regex::new(r"(?si)Action:\s*.+?(?:Action Input:\s*.+?)?(?:\n\n|\z)").unwrap();
        let cleaned = action_re.replace_all(text, "");
        // Remove <tool_call>...</tool_name> XML blocks
        let xml_re = Regex::new(r"(?s)<tool_call>.*?</\w+>").unwrap();
        let cleaned = xml_re.replace_all(&cleaned, "");
        cleaned.trim().to_string()
    }

    /// Truncate observation text if it exceeds 4000 characters.
    fn truncate_observation(content: &str, limit: usize) -> String {
        if content.len() > limit {
            let mut truncated = content[..limit].to_string();
            truncated.push_str("\n\n[Output truncated]");
            truncated
        } else {
            content.to_string()
        }
    }
}

#[async_trait::async_trait]
impl<M: CompletionModel + 'static> OjAgent for NativeOpenHandsAgent<M> {
    fn agent_id(&self) -> &str {
        "native_openhands"
    }

    fn accepts_tools(&self) -> bool {
        true
    }

    async fn run(
        &self,
        input: &str,
        context: Option<&AgentContext>,
    ) -> Result<AgentResult, OpenJarvisError> {
        let mut history: Vec<RigMessage> = context
            .map(|ctx| {
                ctx.conversation
                    .messages
                    .iter()
                    .filter_map(|m| match m.role {
                        openjarvis_core::Role::User => {
                            Some(RigMessage::user(&m.content))
                        }
                        openjarvis_core::Role::Assistant => {
                            Some(RigMessage::assistant(&m.content))
                        }
                        _ => None,
                    })
                    .collect()
            })
            .unwrap_or_default();

        let mut all_tool_results: Vec<ToolResult> = Vec::new();
        let mut guard = LoopGuard::default();
        let mut current_input = input.to_string();

        for turn in 1..=self.max_turns {
            let response = self
                .agent
                .chat(&current_input, history.clone())
                .await
                .map_err(|e| {
                    OpenJarvisError::Agent(openjarvis_core::error::AgentError::Execution(
                        e.to_string(),
                    ))
                })?;

            let text = strip_think_tags(&response);

            // 1. Try to extract a Python code block -> execute via code_interpreter
            if let Some(code) = Self::extract_code(&text) {
                let tool_name = "code_interpreter";
                let args = serde_json::json!({"code": code});
                let args_str = args.to_string();

                if let Some(loop_msg) = guard.check(tool_name, &args_str) {
                    return Ok(AgentResult {
                        content: format!("Agent stopped: {loop_msg}"),
                        tool_results: all_tool_results,
                        turns: turn,
                        metadata: HashMap::new(),
                    });
                }

                let tool_result = match self.executor.execute(
                    tool_name,
                    &args,
                    Some("native_openhands"),
                    None,
                ) {
                    Ok(r) => r,
                    Err(e) => ToolResult::failure(tool_name, e.to_string()),
                };

                let obs = Self::truncate_observation(&tool_result.content, 4000);
                history.push(RigMessage::assistant(&text));
                current_input = format!("Output:\n{obs}");

                all_tool_results.push(tool_result);
                continue;
            }

            // 2. Try to extract a structured tool call (Action: / Action Input:)
            if let Some((action, action_input)) = Self::parse_action(&text) {
                if let Some(loop_msg) = guard.check(&action, &action_input) {
                    return Ok(AgentResult {
                        content: format!("Agent stopped: {loop_msg}"),
                        tool_results: all_tool_results,
                        turns: turn,
                        metadata: HashMap::new(),
                    });
                }

                let params: serde_json::Value =
                    serde_json::from_str(&action_input).unwrap_or(serde_json::json!({}));

                let tool_result = match self.executor.execute(
                    &action,
                    &params,
                    Some("native_openhands"),
                    None,
                ) {
                    Ok(r) => r,
                    Err(e) => ToolResult::failure(&action, e.to_string()),
                };

                let obs = Self::truncate_observation(&tool_result.content, 4000);
                history.push(RigMessage::assistant(&text));
                current_input = format!("Result: {obs}");

                all_tool_results.push(tool_result);
                continue;
            }

            // 3. No code or tool call -- this is the final answer
            let cleaned = Self::strip_tool_call_text(&text);
            return Ok(AgentResult {
                content: cleaned,
                tool_results: all_tool_results,
                turns: turn,
                metadata: HashMap::new(),
            });
        }

        // Max turns exceeded
        Ok(AgentResult {
            content: format!("Reached maximum turns ({})", self.max_turns),
            tool_results: all_tool_results,
            turns: self.max_turns,
            metadata: HashMap::new(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use openjarvis_engine::rig_adapter::RigModelAdapter;
    type OpenHandsAgent = NativeOpenHandsAgent<RigModelAdapter<openjarvis_engine::Engine>>;

    #[test]
    fn test_parse_action() {
        let text = "I need to search.\nAction: web_search\nAction Input: {\"query\": \"rust lang\"}";
        let (action, input) = OpenHandsAgent::parse_action(text).unwrap();
        assert_eq!(action, "web_search");
        assert!(input.contains("rust lang"));
    }

    #[test]
    fn test_parse_action_missing_input() {
        let text = "Action: calculator\n\nSome other text";
        let (action, input) = OpenHandsAgent::parse_action(text).unwrap();
        assert_eq!(action, "calculator");
        assert_eq!(input, "{}");
    }

    #[test]
    fn test_extract_code() {
        let text = "Let me compute that:\n```python\nprint(2 + 2)\n```\nDone.";
        let code = OpenHandsAgent::extract_code(text).unwrap();
        assert_eq!(code, "print(2 + 2)");
    }

    #[test]
    fn test_extract_code_none() {
        let text = "No code here, just text.";
        assert!(OpenHandsAgent::extract_code(text).is_none());
    }

    #[test]
    fn test_strip_tool_call_text() {
        let text = "Here is the answer.\nAction: calc\nAction Input: {\"x\": 1}\n\nFinal part.";
        let cleaned = OpenHandsAgent::strip_tool_call_text(text);
        assert!(!cleaned.contains("Action:"));
        assert!(cleaned.contains("Final part"));
    }

    #[test]
    fn test_truncate_observation() {
        let short = "hello";
        assert_eq!(
            OpenHandsAgent::truncate_observation(short, 100),
            "hello"
        );

        let long = "x".repeat(5000);
        let truncated = OpenHandsAgent::truncate_observation(&long, 100);
        assert!(truncated.len() < 200);
        assert!(truncated.contains("[Output truncated]"));
    }
}
