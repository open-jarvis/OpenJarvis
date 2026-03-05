//! SimpleAgent — single-turn generation without tools.
//!
//! Wraps a rig-core `Agent<M>` for single-turn completion.

use crate::traits::OjAgent;
use crate::utils::strip_think_tags;
use openjarvis_core::{AgentContext, AgentResult, OpenJarvisError};
use rig::agent::AgentBuilder;
use rig::completion::request::{Chat, CompletionModel};
use std::collections::HashMap;

/// Single-turn agent that delegates to rig-core's agent builder.
pub struct SimpleAgent<M: CompletionModel> {
    agent: rig::agent::Agent<M>,
}

impl<M: CompletionModel> SimpleAgent<M> {
    pub fn new(model: M, system_prompt: &str, temperature: f64) -> Self {
        let agent = AgentBuilder::new(model)
            .preamble(system_prompt)
            .temperature(temperature)
            .build();
        Self { agent }
    }
}

#[async_trait::async_trait]
impl<M: CompletionModel + 'static> OjAgent for SimpleAgent<M> {
    fn agent_id(&self) -> &str {
        "simple"
    }

    fn accepts_tools(&self) -> bool {
        false
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
                        openjarvis_core::Role::User => {
                            Some(rig::completion::message::Message::user(&m.content))
                        }
                        openjarvis_core::Role::Assistant => {
                            Some(rig::completion::message::Message::assistant(&m.content))
                        }
                        _ => None,
                    })
                    .collect()
            })
            .unwrap_or_default();

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
            tool_results: vec![],
            turns: 1,
            metadata: HashMap::new(),
        })
    }
}
