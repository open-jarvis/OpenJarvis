//! Agent utilities — shared helper functions for all agent implementations.

use openjarvis_core::GenerateResult;
use regex::Regex;

/// Strip `<think>...</think>` tags from model output.
pub fn strip_think_tags(text: &str) -> String {
    let re = Regex::new(r"(?s)<think>.*?</think>").unwrap();
    re.replace_all(text, "").trim().to_string()
}

/// Check if generation was cut off and needs continuation.
pub fn check_continuation(result: &GenerateResult) -> bool {
    result.finish_reason == "length"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strip_think_tags() {
        let input = "Hello <think>internal reasoning</think> world";
        assert_eq!(strip_think_tags(input), "Hello  world");
    }

    #[test]
    fn test_strip_think_tags_multiline() {
        let input = "<think>\nstep 1\nstep 2\n</think>\nAnswer: 42";
        assert_eq!(strip_think_tags(input), "Answer: 42");
    }
}
