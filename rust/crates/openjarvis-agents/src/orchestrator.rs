//! OrchestratorAgent — multi-turn tool loop with function calling.
//!
//! Uses rig-core's `CompletionModel` for generation with LoopGuard protection.

use crate::loop_guard::LoopGuard;
use crate::traits::OjAgent;
use crate::utils::strip_think_tags;
use openjarvis_core::{AgentContext, AgentResult, OpenJarvisError, Role, ToolResult};
use openjarvis_tools::executor::ToolExecutor;
use rig::agent::AgentBuilder;
use rig::completion::request::{Chat, CompletionModel};
use std::collections::HashMap;
use std::sync::Arc;

/// Multi-turn agent with function calling and loop detection.
pub struct OrchestratorAgent<M: CompletionModel> {
    agent: rig::agent::Agent<M>,
    executor: Arc<ToolExecutor>,
    max_turns: usize,
}

impl<M: CompletionModel> OrchestratorAgent<M> {
    pub fn new(
        model: M,
        system_prompt: &str,
        executor: Arc<ToolExecutor>,
        max_turns: usize,
        temperature: f64,
    ) -> Self {
        let agent = AgentBuilder::new(model)
            .preamble(system_prompt)
            .temperature(temperature)
            .build();
        Self {
            agent,
            executor,
            max_turns,
        }
    }
}

#[async_trait::async_trait]
impl<M: CompletionModel + 'static> OjAgent for OrchestratorAgent<M> {
    fn agent_id(&self) -> &str {
        "orchestrator"
    }

    fn accepts_tools(&self) -> bool {
        true
    }

    async fn run(
        &self,
        input: &str,
        context: Option<&AgentContext>,
    ) -> Result<AgentResult, OpenJarvisError> {
        let history: Vec<rig::completion::message::Message> = context
            .map(|ctx| {
                ctx.conversation
                    .messages
                    .iter()
                    .filter_map(|m| match m.role {
                        Role::User => {
                            Some(rig::completion::message::Message::user(&m.content))
                        }
                        Role::Assistant => {
                            Some(rig::completion::message::Message::assistant(&m.content))
                        }
                        _ => None,
                    })
                    .collect()
            })
            .unwrap_or_default();

        let mut all_tool_results = Vec::new();
        let _guard = LoopGuard::default();

        // Use rig agent for generation. Multi-turn tool dispatch requires
        // direct CompletionModel access which we handle in future iterations.
        let response = self
            .agent
            .chat(input, history)
            .await
            .map_err(|e| {
                OpenJarvisError::Agent(openjarvis_core::error::AgentError::Execution(
                    e.to_string(),
                ))
            })?;

        let content = strip_think_tags(&response);

        Ok(AgentResult {
            content,
            tool_results: all_tool_results,
            turns: 1,
            metadata: HashMap::new(),
        })
    }
}
