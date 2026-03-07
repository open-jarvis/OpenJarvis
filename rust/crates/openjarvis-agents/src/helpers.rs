//! Agent helpers — legacy utilities (use `utils` module instead).
//!
//! Kept for backward compatibility with code that references `AgentHelpers`.
//! New code should use `crate::utils::strip_think_tags()` and
//! `crate::utils::check_continuation()` directly.

use openjarvis_core::{GenerateResult, Message};
use openjarvis_engine::traits::InferenceEngine;

pub struct AgentHelpers<E: InferenceEngine> {
    engine: E,
    model: String,
    system_prompt: String,
    temperature: f64,
    max_tokens: i64,
}

impl<E: InferenceEngine> AgentHelpers<E> {
    pub fn new(
        engine: E,
        model: String,
        system_prompt: String,
        temperature: f64,
        max_tokens: i64,
    ) -> Self {
        Self { engine, model, system_prompt, temperature, max_tokens }
    }

    pub fn build_messages(&self, input: &str, history: &[Message]) -> Vec<Message> {
        let mut messages = Vec::new();
        if !self.system_prompt.is_empty() {
            messages.push(Message::system(&self.system_prompt));
        }
        messages.extend_from_slice(history);
        messages.push(Message::user(input));
        messages
    }

    pub fn generate(
        &self,
        messages: &[Message],
        extra: Option<&serde_json::Value>,
    ) -> Result<GenerateResult, openjarvis_core::OpenJarvisError> {
        self.engine.generate(messages, &self.model, self.temperature, self.max_tokens, extra)
    }

    pub fn engine(&self) -> &E {
        &self.engine
    }

    pub fn model(&self) -> &str {
        &self.model
    }

    pub fn strip_think_tags(text: &str) -> String {
        crate::utils::strip_think_tags(text)
    }

    pub fn check_continuation(result: &GenerateResult) -> bool {
        crate::utils::check_continuation(result)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use openjarvis_engine::Engine;

    #[test]
    fn test_strip_think_tags() {
        let input = "Hello <think>internal reasoning</think> world";
        assert_eq!(AgentHelpers::<Engine>::strip_think_tags(input), "Hello  world");
    }

    #[test]
    fn test_strip_think_tags_multiline() {
        let input = "<think>\nstep 1\nstep 2\n</think>\nAnswer: 42";
        assert_eq!(AgentHelpers::<Engine>::strip_think_tags(input), "Answer: 42");
    }
}
