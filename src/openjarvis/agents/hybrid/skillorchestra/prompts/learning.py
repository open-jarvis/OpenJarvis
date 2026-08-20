"""
LLM prompt templates for Skill Handbook learning.

All prompts used during the learning pipeline:
- Skill discovery from trajectory contrast
- Skill identification for a query
- Mode-level insight distillation
- Profile summarization (strengths/weaknesses)
- Skill split/merge analysis
- Failure-driven refinement
"""

# ---------------------------------------------------------------------------
# Phase 1a: Skill Discovery - Model Routing
# ---------------------------------------------------------------------------

SKILL_DISCOVERY_PROMPT = """You are a skill taxonomist analyzing QA problems and model performance data to discover what skills are needed for effective model routing.

## Task
Analyze the sample problems below along with per-model success/failure data. Your goal: Propose a HIERARCHICAL skill taxonomy with:
1. HIGH-LEVEL CATEGORIES (3-6): Broad skill areas that differentiate problems
2. FINE-GRAINED SKILLS (2-4 per category): Specific capabilities within each category

## Requirements
- Skills should capture what makes problems DIFFERENT from each other
- Skills should explain what makes MODELS perform DIFFERENTLY on those problems
- Skills should be SPECIFIC and MEASURABLE (not vague like "intelligence" or "reasoning")
- Include INDICATORS (keywords/patterns that suggest a skill is needed)
- Include EXAMPLES from the sample problems
- Skill IDs should follow the pattern: category_name.specific_skill_name

## Sample Problems with Model Performance
{sample_problems}

## Contrastive Evidence (where models disagree)
{contrastive_evidence}

## Existing Skills (avoid duplicates)
{existing_skills}

## Output Format
Return a JSON object with:
{{
  "categories": [
    {{
      "name": "category_name",
      "description": "What this category covers",
      "skills": [
        {{
          "skill_id": "category_name.skill_name",
          "name": "Human-readable Skill Name",
          "description": "What this specific skill involves and why models differ on it",
          "indicators": ["keyword1", "pattern2", "phrase3"],
          "examples": ["Example query requiring this skill"],
          "mode": "answer"
        }}
      ]
    }}
  ]
}}

Aim for a taxonomy that covers the FULL DIVERSITY of the sample problems, not just one narrow topic. If problems span temporal facts, entity lookups, numeric data, relational facts, etc., the taxonomy should reflect all of those."""


# ---------------------------------------------------------------------------
# Phase 1a: Skill Discovery - Agent Orchestration
# ---------------------------------------------------------------------------

AGENT_ORCHESTRATION_DISCOVERY_PROMPT = """You are a skill taxonomist analyzing QA problems to discover the underlying skills required to solve them.

## Stage Information
We have 3 stages in our pipeline:
- **search**: Web search to retrieve factual information (tool: search)
- **code**: Code generation and execution for calculations (tool: enhance_reasoning)
- **answer**: Generate final answer from context (tool: answer)

## Sample Problems
{sample_problems}

## Task
Analyze these problems and DISCOVER what skills are needed.
Propose a HIERARCHICAL skill taxonomy with:
1. HIGH-LEVEL CATEGORIES (3-5): Broad skill areas that differentiate problems
2. FINE-GRAINED SKILLS (2-4 per category): Specific capabilities within each category

## Requirements
- Skills should capture what makes problems DIFFERENT and what makes MODELS perform differently
- Skills should be SPECIFIC and MEASURABLE (not vague like "intelligence")
- Include INDICATORS (keywords/patterns that suggest a skill is needed)
- Use hierarchical IDs: stage.category.specific_skill

## Output Format (JSON)
```json
{{
  "categories": [
    {{
      "stage": "search|code|answer",
      "name": "category_name",
      "description": "What this category covers",
      "skills": [
        {{
          "id": "stage.category.skill_name",
          "name": "Human Readable Name",
          "description": "What this specific skill involves",
          "indicators": ["keyword1", "pattern2", "phrase3"],
          "examples": ["Example query requiring this skill"]
        }}
      ]
    }}
  ]
}}
```

Respond with JSON only."""


# ---------------------------------------------------------------------------
# Phase 1b: Skill Identification (which skills are active for a query)
# ---------------------------------------------------------------------------

SKILL_IDENTIFICATION_PROMPT = """You are an expert at identifying which skills from a catalog are required to handle a given query.

## Query
{query}

## Ground Truth
{ground_truth}

## Operational Mode
{mode}

## Model Results (all models' outputs and whether they succeeded)
Use this contrastive evidence: where models differ in success/failure, the outputs reveal what skills matter for this query.

{model_results}

## Available Skills for this Mode
{mode_skills}

## Output Format
Return a JSON object:
{{
  "active_skills": [
    {{
      "skill_id": "the skill id",
      "weight": 0.0 to 1.0,
      "reasoning": "brief explanation"
    }}
  ]
}}

Weights should sum to approximately 1.0. Only include skills that are genuinely relevant to this specific query and mode. Use the model outputs to infer which skills differentiate successful vs failed attempts."""


# ---------------------------------------------------------------------------
# Phase 1b: Mode-level Insight Distillation
# ---------------------------------------------------------------------------

MODE_INSIGHT_PROMPT = """You are an expert at analyzing execution patterns to derive reusable routing insights.

## Task
Analyze the execution patterns below and derive mode-level routing insights. These insights should help an orchestrator decide WHEN to use each mode and HOW to transition between modes.

## Execution Patterns
{execution_patterns}

## Modes
{modes}

## Output Format
Return a JSON object:
{{
  "insights": [
    {{
      "mode": "search|code|answer",
      "content": "The routing insight as a clear, actionable rule",
      "insight_type": "transition|usage|constraint",
      "confidence": 0.0 to 1.0
    }}
  ]
}}

Focus on patterns that generalize across queries, not query-specific observations. Examples:
- "If multiple arithmetic operations are needed, switch to code mode instead of search"
- "Prefer search-3 for multi-hop queries requiring entity tracking"
- "Switch to answer mode once all required facts have been gathered"
"""


# ---------------------------------------------------------------------------
# Phase 1b: Agent Profile Summarization
# ---------------------------------------------------------------------------

PROFILE_SUMMARY_PROMPT = """You are an expert at summarizing agent capabilities from performance data.

## Agent
{agent_id} (model: {model_name}, mode: {mode})

## Performance Data
{performance_data}

## Output Format
Return a JSON object:
{{
  "strengths": ["strength1", "strength2"],
  "weaknesses": ["weakness1", "weakness2"],
  "routing_signals": ["when to use this agent", "when to avoid"]
}}

Be specific and evidence-based. Reference skill categories where applicable."""


# ---------------------------------------------------------------------------
# Phase 2: Skill Split Analysis
# ---------------------------------------------------------------------------

SKILL_SPLIT_PROMPT = """You are an expert at analyzing whether a skill should be split into finer-grained sub-skills.

## Skill Under Review
ID: {skill_id}
Name: {skill_name}
Description: {skill_description}
Mode: {mode}

## Evidence for Splitting
The agents have highly VARIABLE performance on this skill, suggesting it may conflate distinct capabilities:

{performance_evidence}

## Sample Queries Where Agents Disagree
{sample_queries}

## Output Format
Return a JSON object:
{{
  "should_split": true/false,
  "rationale": "explanation",
  "proposed_splits": [
    {{
      "skill_id": "mode.category.new_name",
      "name": "New Skill Name",
      "description": "What this sub-skill captures",
      "indicators": ["indicator1", "indicator2"],
      "distinguishing_feature": "What separates this from sibling skills"
    }}
  ]
}}

Only recommend splitting if there is clear evidence that the skill conflates genuinely different capabilities. The splits should be actionable for routing decisions."""


# ---------------------------------------------------------------------------
# Phase 2: Skill Merge Analysis
# ---------------------------------------------------------------------------

SKILL_MERGE_PROMPT = """You are an expert at analyzing whether two skills should be merged.

## Skills Under Review

### Skill 1
ID: {skill_1_id}
Name: {skill_1_name}
Description: {skill_1_description}

### Skill 2
ID: {skill_2_id}
Name: {skill_2_name}
Description: {skill_2_description}

## Evidence for Merging
All agents have statistically INDISTINGUISHABLE performance between these two skills, suggesting they are redundant for routing purposes:

{performance_evidence}

## Output Format
Return a JSON object:
{{
  "should_merge": true/false,
  "rationale": "Why merge or not",
  "merged_skill": {{
    "skill_id": "mode.category.merged_name",
    "name": "Merged Skill Name",
    "description": "Combined description",
    "indicators": ["combined indicators"]
  }},
  "alternative_explanation": "If not merging, explain why they should remain separate"
}}

Only recommend merging if the skills truly capture the same capability from a routing perspective, even if they differ semantically."""


# ---------------------------------------------------------------------------
# Phase 2: Agent Orchestration Split/Merge
# ---------------------------------------------------------------------------

AGENT_ORCHESTRATION_SPLIT_PROMPT = """You are analyzing whether a skill should be split into more fine-grained skills.

## Skill to Analyze
{skill_definition}

## Performance Data
{performance_data}

## Sample Queries
### High Performance Queries (models succeeded)
{high_perf_queries}

### Low Performance Queries (models failed)
{low_perf_queries}

### Divergent Performance Queries (some models succeeded, others failed)
{divergent_queries}

## Sample Trajectories (if available)
### Successful Trajectories
{success_trajectories}

### Failed Trajectories
{failure_trajectories}

## Task
Analyze whether this skill should be split:
1. Does the skill have high variance across models? (suggests splitting)
2. Do different query types show different performance patterns? (suggests splitting)
3. Are there clear sub-skills that could be distinguished? (suggests splitting)

## Output Format (JSON)
```json
{{
  "should_split": true/false,
  "rationale": "Why split or not",
  "proposed_splits": [
    {{
      "skill_id": "stage.category.subskill1",
      "name": "Sub-skill Name",
      "description": "What this sub-skill covers",
      "indicators": ["indicator1", "indicator2"],
      "distinguishing_feature": "What distinguishes this from sibling skills"
    }}
  ]
}}
```

Respond with JSON only."""


AGENT_ORCHESTRATION_MERGE_PROMPT = """You are analyzing whether two skills should be merged.

## Skills to Analyze
{skills_definitions}

## Performance Correlation
{performance_correlation}

## Sample Queries
### Skill 1 Queries
{skill1_queries}

### Skill 2 Queries
{skill2_queries}

## Task
Analyze whether these skills should be merged:
1. Do they have nearly identical performance patterns across models? (suggests merge)
2. Are they conceptually similar or overlapping? (suggests merge)
3. Would merging simplify routing without losing important distinctions? (suggests merge)

## Output Format (JSON)
```json
{{
  "should_merge": true/false,
  "rationale": "Why merge or not",
  "merged_skill": {{
    "skill_id": "stage.category.merged_skill",
    "name": "Merged Skill Name",
    "description": "Combined description",
    "indicators": ["indicator1", "indicator2"]
  }},
  "alternative_explanation": "If not merging, explain why they should remain separate"
}}
```

Respond with JSON only."""


# ---------------------------------------------------------------------------
# Failure-driven refinement (when skill routing < oracle on training set)
# ---------------------------------------------------------------------------

FAILURE_DRIVEN_REFINEMENT_PROMPT = """You are an expert at analyzing why skill-based model routing fails and how to improve the skill taxonomy.

## Context
We have a skill-based routing system that selects which LLM to call based on identified skills. On the training set, we achieved:
- **Oracle accuracy**: {oracle_accuracy:.1%} (best possible — if we always picked the correct model per query)
- **Skill-based accuracy**: {skill_accuracy:.1%} (our current routing)

We failed to achieve oracle-level performance. This suggests either:
1. **Missing skills**: Queries require skills not in our catalog
2. **Skills too coarse**: Existing skills conflate distinct capabilities and lead to wrong model selection
3. **Skill identification gaps**: The router fails to identify the right skills for some query types

## Current Skill Catalog
{skill_catalog}

## Failed Queries (oracle would have been correct, but we routed wrong)
For each failed query we show: the question, what model(s) would have been correct (oracle), what model we routed to, and whether any model got it right.

{failed_queries}

## Task
Reflect on why the routing failed for these queries. Consider:
1. What skills are **missing** from the catalog that would have helped route correctly?
2. Which existing skills might need to be **split** into finer-grained sub-skills?
3. What **indicators** or patterns in the failed queries suggest new or refined skills?

## Output Format
Return a JSON object:
{{
  "rationale": "Your overall reflection on why routing failed and what the main gaps are",
  "proposed_new_skills": [
    {{
      "skill_id": "category.specific_skill_name",
      "name": "Human-readable name",
      "description": "What this skill captures and why it matters for routing",
      "indicators": ["keyword1", "pattern2", "phrase3"],
      "example_queries": ["Example from failed queries that would match this skill"]
    }}
  ],
  "proposed_splits": [
    {{
      "parent_skill_id": "existing.skill.id",
      "rationale": "Why this skill should be split",
      "proposed_sub_skills": [
        {{
          "skill_id": "existing.new_sub_name",
          "name": "Sub-skill name",
          "description": "What this sub-skill captures",
          "indicators": ["indicator1"],
          "distinguishing_feature": "What separates this from sibling sub-skills"
        }}
      ]
    }}
  ]
}}

- Only propose new skills or splits that are clearly supported by the failed queries
- Skill IDs should follow category.specific_name pattern
- Be specific: tie each proposal to concrete failed queries"""
