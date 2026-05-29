"""
Eval orchestrator prompts for skill-based agent orchestration.
"""

from typing import Any, Optional

# =============================================================================
# Baseline Tool Info
# =============================================================================


def format_baseline_tool_info() -> str:
    """Format baseline tool information for the orchestrator prompt."""
    return """- Tool: search, Models: search-1 ($10/M output), search-2 ($2/M output), search-3 ($0.8/M output)
Description: Search for missing information
- Tool: code|enhance_reasoning, Models: reasoner-1 ($10/M output), reasoner-2 ($2/M output), reasoner-3 ($0.8/M output)
Description: Write and execute Python code to solve the problem
- Tool: answer, Models: answer-1 ($10/M output), answer-2 ($2/M output), answer-3 ($0.9/M output), answer-4 ($0.8/M output), answer-math-1 ($0.9/M output), answer-math-2 ($0.2/M output)
Description: Extract the final answer if you think you have enough information to answer the problem"""


# =============================================================================
# Skill-Enhanced Orchestrator Prompt (router_decides strategy)
# =============================================================================

SKILL_ORCHESTRATOR_PROMPT = """You are a skill-based orchestrator for multi-step question answering. Choose the best tool and model for each step.

## Available Tools and Models (Baseline)

{baseline_tool_info}

## Learned Skill Definitions

### Search Skills
{search_skills}

### Code|Enhance Reasoning Skills
{reasoning_skills}

### Answer Skills
{answer_skills}

## Model Performance (learned from validation)

### Search Models
{search_model_performance}

### Code|Enhance Reasoning Models
{reasoning_model_performance}

### Answer Models
{answer_model_performance}

## Your Task
1. Analyze the problem and current context
2. Identify which skills are needed for the next step
3. Choose the appropriate tool (search/enhance_reasoning/answer)
4. Select the best model for that tool based on skill match and cost

Consider cost-efficiency: if multiple models can handle it, prefer cheaper ones.

You must first reason inside <think>...</think> about:
- What information is missing or what computation is needed
- Which skills from the catalog are required
- Which model is best suited based on performance data

**IMPORTANT**: When calling a tool, you MUST specify the model parameter using the model alias (e.g., "answer-1", "search-1", "reasoner-1"). Use the exact model names from the Available Models section above.

Problem: {problem}

{context_str}

Choose an appropriate tool."""


# =============================================================================
# Skill Analysis Prompt (for weighted_avg, analyze_model_decide strategies)
# =============================================================================

SKILL_ANALYSIS_ORCHESTRATOR_PROMPT = """You are a skill-based orchestrator for multi-step question answering. You select the best tool (search|code|answer) and model by analyzing required skills.

## Problem to Solve
{problem}

## Current Context
{context_str}

---

## Quick Reference: What You Need to Do

**CRITICAL REQUIREMENT**: Before making ANY tool call, you MUST:
1. Inside <think>...</think>, analyze required skills and output in <skill_analysis> tags
2. Then choose the appropriate tool with the selected model based on the skill analysis.

**The context above may be long - scroll back to see the problem and context, then follow the instructions below.**

---

## Available Tools and Models (Baseline)

{baseline_tool_info}

## Learned Skill Definitions

### Search Skills
{search_skills}

### Reasoning Skills
{reasoning_skills}

### Answer Skills
{answer_skills}
Use general performance of answer models to select the best model for the answer stage if you think you have enough information to answer the problem.

## Model Performance (learned from validation)

### Search Models
{search_model_performance}

### Reasoning Models
{reasoning_model_performance}

### Answer Models
{answer_model_performance}
---

## Detailed Instructions

**STEP 1 - REQUIRED**: Based on the Problem and Context shown at the top, think about what should be the next stage (search|code|answer).
Search stage is to find missing information that you think is needed to answer the problem.
Code stage is to write and execute Python code to solve the problem.
Answer stage is to synthesize all gathered information into a final answer.

**STEP 2 - REQUIRED FORMAT**:
After deciding the next stage, analyze the skills needed for the next stage and provide the detailed skill analysis needed for the next stage.
Reason inside <think>...</think> about why these skills are needed and their relative importance. We will use this skill analysis to select the best model for the next stage.
Then output your analysis in the following format inside <skill_analysis> tags:
<skill_analysis>
{{ "required_skills": [ {{"skill_id": "skill.id", "percentage": 50}}, {{"skill_id": "skill.id", "percentage": 30}}, ... ], "reasoning": "Brief explanation of why these skills are needed" }}
</skill_analysis>

**STEP 3**: Choose the appropriate tool with the selected model based on the skill analysis.

---

## Final Reminders

**CRITICAL**: The <skill_analysis> block is MANDATORY and must appear BEFORE your tool call. Without it, the routing system cannot function properly.

**IMPORTANT**: When calling a tool, you MUST specify the model parameter using the model alias (e.g., "answer-1", "search-1", "reasoner-1"). Use the exact model names from the Available Models section above.

Now, based on the Problem and Context shown at the top, analyze what should be the next stage (search|code|answer), provide the detailed skill analysis needed for the next stage in the <skill_analysis> tags and then choose an appropriate tool.
"""


# =============================================================================
# Prompt Builder
# =============================================================================


def build_skill_orchestrator_prompt(
    problem: str,
    context_str: str,
    strategy: str = "router_decides",
    handbook: Any = None,
    search_skills: Optional[str] = None,
    reasoning_skills: Optional[str] = None,
    answer_skills: Optional[str] = None,
    search_model_performance: Optional[str] = None,
    reasoning_model_performance: Optional[str] = None,
    answer_model_performance: Optional[str] = None,
    baseline_tool_info: Optional[str] = None,
) -> str:
    """
    Build enhanced orchestrator prompt with skill catalog and model performance.

    Args:
        problem: The question/problem to solve
        context_str: Current context (documents, code results, etc.)
        strategy: Routing strategy - "router_decides" or "analyze_model_decide" etc.
        handbook: SkillHandbook object with format_skills(stage/mode) and format_model_performance(stage/mode)
        search_skills: Override - skill definitions for search stage
        reasoning_skills: Override - skill definitions for reasoning stage
        answer_skills: Override - skill definitions for answer stage
        search_model_performance: Override - model performance for search
        reasoning_model_performance: Override - model performance for reasoning
        answer_model_performance: Override - model performance for answer
        baseline_tool_info: Override - baseline tool descriptions

    Returns:
        Formatted prompt string
    """
    if baseline_tool_info is None:
        baseline_tool_info = format_baseline_tool_info()

    if handbook:
        if search_skills is None:
            search_skills = handbook.format_skills("search")
        if reasoning_skills is None:
            reasoning_skills = handbook.format_skills("code")
        if answer_skills is None:
            answer_skills = handbook.format_skills("answer")
        if search_model_performance is None:
            search_model_performance = handbook.format_model_performance("search")
        if reasoning_model_performance is None:
            reasoning_model_performance = handbook.format_model_performance("code")
        if answer_model_performance is None:
            answer_model_performance = handbook.format_model_performance("answer")

    search_skills = search_skills or "No skills defined"
    reasoning_skills = reasoning_skills or "No skills defined"
    answer_skills = answer_skills or "No skills defined"
    search_model_performance = search_model_performance or "No performance data"
    reasoning_model_performance = reasoning_model_performance or "No performance data"
    answer_model_performance = answer_model_performance or "No performance data"

    if strategy == "router_decides":
        template = SKILL_ORCHESTRATOR_PROMPT
    else:
        template = SKILL_ANALYSIS_ORCHESTRATOR_PROMPT

    return template.format(
        baseline_tool_info=baseline_tool_info,
        search_skills=search_skills,
        reasoning_skills=reasoning_skills,
        answer_skills=answer_skills,
        search_model_performance=search_model_performance,
        reasoning_model_performance=reasoning_model_performance,
        answer_model_performance=answer_model_performance,
        problem=problem,
        context_str=context_str if context_str else "(No context yet)",
    )
