"""Episode dataclasses for orchestrator training.

Adapted from IPW's ``episode_builder.py``. These types represent the core
data structures for orchestrator RL/SFT training: actions, observations,
episode steps, and complete episodes with aggregate metrics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Answer grading utilities
# ---------------------------------------------------------------------------


def normalize_number(s: str) -> Optional[float]:
    """Try to parse a string as a number.

    Returns None if not a valid number.
    """
    s = s.strip().lower()
    s = re.sub(r"[,\s]", "", s)  # Remove commas and spaces
    s = re.sub(r"\.0+$", "", s)  # Remove trailing .0

    try:
        return float(s)
    except ValueError:
        return None


def extract_answer(text: str) -> str:
    """Extract the core answer from a potentially verbose response.

    Handles patterns like:
    - "The answer is 4"
    - "Result: 4.0"
    - "4" (unchanged)
    - "Therefore, the answer is approximately 4"
    """
    text = text.strip()

    patterns = [
        r"(?:the\s+)?answer\s+is[:\s]+(.+?)(?:\.|$)",
        r"result[:\s]+(.+?)(?:\.|$)",
        r"=\s*(.+?)(?:\.|$)",
        r"therefore[,\s]+(?:the\s+)?(?:answer\s+is\s+)?(.+?)(?:\.|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return text


def grade_answer(predicted: str, expected: str, tolerance: float = 1e-6) -> bool:
    """Grade an answer against expected, with smart matching.

    Handles:
    - Exact string match (case-insensitive)
    - Numeric comparison with tolerance
    - Answer extraction from verbose responses

    Args:
        predicted: The model's answer.
        expected: Ground truth answer.
        tolerance: Tolerance for numeric comparisons.

    Returns:
        True if answer is correct.
    """
    predicted = predicted.strip()
    expected = expected.strip()

    # Exact match (case-insensitive)
    if predicted.lower() == expected.lower():
        return True

    # Try extracting core answer
    pred_extracted = extract_answer(predicted)
    exp_extracted = extract_answer(expected)

    if pred_extracted.lower() == exp_extracted.lower():
        return True

    # Try numeric comparison
    pred_num = normalize_number(pred_extracted)
    exp_num = normalize_number(exp_extracted)

    if pred_num is not None and exp_num is not None:
        if exp_num == 0:
            return abs(pred_num) < tolerance
        return abs(pred_num - exp_num) / abs(exp_num) < tolerance

    return False


# ---------------------------------------------------------------------------
# Core dataclasses
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorAction:
    """Orchestrator action: thought + tool selection + tool input."""

    thought: str
    """Reasoning about what to do next."""

    tool_name: str
    """Selected tool name (e.g., 'calculator', 'think')."""

    tool_input: str
    """Input/prompt to send to the tool."""

    is_final_answer: bool = False
    """Whether this action provides the final answer."""


@dataclass
class OrchestratorObservation:
    """Result from executing an action, with flat telemetry fields."""

    content: str
    """Tool response content."""

    latency_seconds: float = 0.0
    """Latency in seconds."""

    cost_usd: float = 0.0
    """Cost in USD."""

    energy_joules: float = 0.0
    """Energy consumed in joules."""

    power_watts: float = 0.0
    """Power usage in watts."""

    tokens: int = 0
    """Tokens consumed."""


@dataclass
class EpisodeStep:
    """Single step in an episode."""

    turn: int
    """Step number (0-indexed)."""

    action: OrchestratorAction
    """Action taken."""

    observation: OrchestratorObservation
    """Result of action."""


@dataclass
class Episode:
    """Complete RL episode with aggregate metrics."""

    task_id: str
    """Unique task identifier."""

    initial_prompt: str
    """Initial question/task."""

    steps: List[EpisodeStep] = field(default_factory=list)
    """Sequence of (action, observation) pairs."""

    final_answer: str = ""
    """Final answer produced by orchestrator."""

    ground_truth: str = ""
    """Ground truth answer."""

    correct: bool = False
    """Whether final answer matches ground truth."""

    # Aggregate metrics
    total_energy_joules: float = 0.0
    total_cost_usd: float = 0.0
    total_latency_seconds: float = 0.0
    total_tokens: int = 0
    max_power_watts: float = 0.0

    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_step(
        self, action: OrchestratorAction, observation: OrchestratorObservation
    ) -> None:
        """Add a step to the episode and update aggregate metrics."""
        step = EpisodeStep(
            turn=len(self.steps),
            action=action,
            observation=observation,
        )
        self.steps.append(step)

        self.total_energy_joules += observation.energy_joules
        self.total_latency_seconds += observation.latency_seconds
        self.total_cost_usd += observation.cost_usd
        self.total_tokens += observation.tokens
        self.max_power_watts = max(self.max_power_watts, observation.power_watts)

        if action.is_final_answer:
            self.final_answer = observation.content

    def num_turns(self) -> int:
        """Return number of turns in episode."""
        return len(self.steps)

    def compute_ipj(self) -> float:
        """Compute Intelligence Per Joule (IPJ).

        Returns:
            IPJ score (higher is better).  0.0 if energy is zero or
            the answer is incorrect.
        """
        if self.total_energy_joules <= 0:
            return 0.0
        accuracy_score = 1.0 if self.correct else 0.0
        return accuracy_score / self.total_energy_joules

    def to_dict(self) -> Dict[str, Any]:
        """Convert episode to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "initial_prompt": self.initial_prompt,
            "steps": [
                {
                    "turn": step.turn,
                    "thought": step.action.thought,
                    "tool": step.action.tool_name,
                    "tool_input": step.action.tool_input,
                    "observation": step.observation.content[:200],
                    "energy_joules": step.observation.energy_joules,
                    "latency_seconds": step.observation.latency_seconds,
                    "cost_usd": step.observation.cost_usd,
                }
                for step in self.steps
            ],
            "final_answer": self.final_answer,
            "ground_truth": self.ground_truth,
            "correct": self.correct,
            "total_energy_joules": self.total_energy_joules,
            "total_latency_seconds": self.total_latency_seconds,
            "total_cost_usd": self.total_cost_usd,
            "total_tokens": self.total_tokens,
            "num_turns": self.num_turns(),
            "ipj": self.compute_ipj(),
        }


@dataclass
class EpisodeState:
    """Mutable state during episode execution."""

    initial_prompt: str
    """Initial task/question."""

    history: List[Tuple[OrchestratorAction, OrchestratorObservation]] = field(
        default_factory=list
    )
    """History of (action, observation) pairs."""

    final_answer: Optional[str] = None
    """Final answer (set when is_final_answer action is taken)."""

    def add_turn(
        self,
        action: OrchestratorAction,
        observation: OrchestratorObservation,
    ) -> None:
        """Add a turn to the episode history."""
        self.history.append((action, observation))
        if action.is_final_answer:
            self.final_answer = observation.content

    def num_turns(self) -> int:
        """Return number of turns so far."""
        return len(self.history)

    def to_episode(self, task_id: str, ground_truth: str, correct: bool) -> Episode:
        """Convert state to Episode for reward computation."""
        episode = Episode(
            task_id=task_id,
            initial_prompt=self.initial_prompt,
            ground_truth=ground_truth,
            final_answer=self.final_answer or "",
            correct=correct,
        )
        for action, observation in self.history:
            episode.add_step(action, observation)
        return episode


@dataclass
class PolicyOutput:
    """Output from policy model prediction."""

    thought: str
    """Reasoning about what to do."""

    tool_name: str
    """Selected tool."""

    tool_input: str
    """Input for the tool."""

    is_final_answer: bool = False
    """Whether this provides the final answer."""

    raw_text: str = ""
    """Raw model output."""

    confidence: float = 1.0
    """Confidence score (if available)."""


__all__ = [
    "Episode",
    "EpisodeState",
    "EpisodeStep",
    "OrchestratorAction",
    "OrchestratorObservation",
    "PolicyOutput",
    "extract_answer",
    "grade_answer",
    "normalize_number",
]
