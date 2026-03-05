//! NativeReActAgent — Thought-Action-Observation loop with regex parsing.
//!
//! Keeps custom ReAct loop (rig-core has no built-in ReAct).
//! Uses rig-core's `CompletionModel` via `Agent.chat()` for generation.

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

/// ReAct agent with Thought-Action-Observation loop.
pub struct NativeReActAgent<M: CompletionModel> {
    agent: rig::agent::Agent<M>,
    executor: Arc<ToolExecutor>,
    max_turns: usize,
}

impl<M: CompletionModel> NativeReActAgent<M> {
    pub fn new(
        model: M,
        executor: Arc<ToolExecutor>,
        max_turns: usize,
        temperature: f64,
    ) -> Self {
        let system_prompt = format!(
            "You are a helpful assistant that uses the ReAct framework.\n\
             Available tools: {}\n\n\
             For each step, output:\n\
             Thought: <your reasoning>\n\
             Action: <tool_name>\n\
             Action Input: <JSON arguments>\n\n\
             After receiving an observation, continue reasoning.\n\
             When you have the final answer, output:\n\
             Thought: I now know the answer.\n\
             Final Answer: <your answer>",
            executor.list_tools().join(", ")
        );

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

    fn parse_action(text: &str) -> Option<(String, String)> {
        let action_re = Regex::new(r"(?m)^Action:\s*(.+)$").unwrap();
        let input_re = Regex::new(r"(?m)^Action Input:\s*(.+)$").unwrap();

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

    fn parse_final_answer(text: &str) -> Option<String> {
        let re = Regex::new(r"(?m)^Final Answer:\s*(.+)").unwrap();
        re.captures(text)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().trim().to_string())
    }
}

#[async_trait::async_trait]
impl<M: CompletionModel + 'static> OjAgent for NativeReActAgent<M> {
    fn agent_id(&self) -> &str {
        "native_react"
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

        let mut all_tool_results = Vec::new();
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

            if let Some(answer) = Self::parse_final_answer(&text) {
                return Ok(AgentResult {
                    content: answer,
                    tool_results: all_tool_results,
                    turns: turn,
                    metadata: HashMap::new(),
                });
            }

            if let Some((action, action_input)) = Self::parse_action(&text) {
                if let Some(loop_msg) = guard.check(&action, &action_input) {
                    return Ok(AgentResult {
                        content: format!("Agent stopped: {}", loop_msg),
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
                    Some("native_react"),
                    None,
                ) {
                    Ok(r) => r,
                    Err(e) => ToolResult::failure(&action, e.to_string()),
                };

                history.push(RigMessage::assistant(&text));
                current_input = format!("Observation: {}", tool_result.content);

                all_tool_results.push(tool_result);
            } else {
                return Ok(AgentResult {
                    content: text,
                    tool_results: all_tool_results,
                    turns: turn,
                    metadata: HashMap::new(),
                });
            }
        }

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

    // Use RigModelAdapter<Engine> as a concrete CompletionModel type for parse tests
    use openjarvis_engine::rig_adapter::RigModelAdapter;
    type ReactAgent = NativeReActAgent<RigModelAdapter<openjarvis_engine::Engine>>;

    #[test]
    fn test_parse_action() {
        let text = "Thought: I need to calculate\nAction: calculator\nAction Input: {\"expression\": \"2+2\"}";
        let (action, input) = ReactAgent::parse_action(text).unwrap();
        assert_eq!(action, "calculator");
        assert!(input.contains("2+2"));
    }

    #[test]
    fn test_parse_final_answer() {
        let text = "Thought: I know the answer\nFinal Answer: 42";
        let answer = ReactAgent::parse_final_answer(text).unwrap();
        assert_eq!(answer, "42");
    }
}
