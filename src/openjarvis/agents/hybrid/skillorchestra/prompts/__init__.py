"""Prompt templates for SkillOrchestra.

Centralized prompts for:
- eval_orchestrator: FRAMES orchestrator (search/code/answer)
- learning: handbook discovery, refinement, profiler
- model_routing: QA benchmarks (skill-based and baseline routing)
"""

from .eval_orchestrator import (
    SKILL_ANALYSIS_ORCHESTRATOR_PROMPT,
    SKILL_ORCHESTRATOR_PROMPT,
    build_skill_orchestrator_prompt,
    format_baseline_tool_info,
)
from .learning import (
    AGENT_ORCHESTRATION_DISCOVERY_PROMPT,
    AGENT_ORCHESTRATION_MERGE_PROMPT,
    AGENT_ORCHESTRATION_SPLIT_PROMPT,
    FAILURE_DRIVEN_REFINEMENT_PROMPT,
    MODE_INSIGHT_PROMPT,
    PROFILE_SUMMARY_PROMPT,
    SKILL_DISCOVERY_PROMPT,
    SKILL_IDENTIFICATION_PROMPT,
    SKILL_MERGE_PROMPT,
    SKILL_SPLIT_PROMPT,
)
from .model_routing import BASELINE_PROMPT, SKILL_ANALYSIS_PROMPT

__all__ = [
    # Eval orchestrator
    "build_skill_orchestrator_prompt",
    "format_baseline_tool_info",
    "SKILL_ORCHESTRATOR_PROMPT",
    "SKILL_ANALYSIS_ORCHESTRATOR_PROMPT",
    # Learning
    "SKILL_DISCOVERY_PROMPT",
    "AGENT_ORCHESTRATION_DISCOVERY_PROMPT",
    "SKILL_IDENTIFICATION_PROMPT",
    "MODE_INSIGHT_PROMPT",
    "PROFILE_SUMMARY_PROMPT",
    "SKILL_SPLIT_PROMPT",
    "SKILL_MERGE_PROMPT",
    "AGENT_ORCHESTRATION_SPLIT_PROMPT",
    "AGENT_ORCHESTRATION_MERGE_PROMPT",
    "FAILURE_DRIVEN_REFINEMENT_PROMPT",
    # Model routing
    "SKILL_ANALYSIS_PROMPT",
    "BASELINE_PROMPT",
]
