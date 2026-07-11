"""Prompt strings + tool specs for ToolOrchestraAgent (split from toolorchestra.py)."""

from __future__ import annotations

from typing import Any, Dict, List

ORCHESTRATOR_SYS = """\
You are a tool-orchestrating agent. You coordinate a pool of workers to answer the user's question. Each turn you MUST emit exactly one JSON object — no prose, no markdown fences — taking one of two forms:

  {"action": "call_worker", "worker_id": <int>, "input": "<question or instruction for that worker>"}

  {"action": "final_answer", "answer": "<final answer to the user, respecting the question's answer-format rules>"}

Strategy:

- Call cheap / specialized workers first (small local model for extraction or arithmetic on given data; web_search for unknowns; specialist LLMs for code/math).
- Call the frontier worker (Opus / GPT-5) sparingly, for hard reasoning or a final synthesis pass.
- Stop and emit `final_answer` as soon as the previous worker output is sufficient. Do NOT call a worker just to paraphrase.
- The user only sees the `answer` field of `final_answer`, so make sure it follows any answer-format rules in the question.
"""

FORCE_FINAL_PROMPT = (
    "Worker-call budget exhausted. Emit `final_answer` now using everything "
    "you've learned. Respect the question's answer-format rules."
)


# ============================================================================
# RL-mode constants (Orchestrator-8B, paper-faithful).
# ============================================================================
#
# Verbatim copies of the upstream system prompt / user-prompt template / tools
# from `external/ToolOrchestra/evaluation/eval_hle.py` + `tools.json`. Don't
# edit the description text — Orchestrator-8B was RL-trained against this
# exact wording and pricing/latency table.

RL_ORCHESTRATOR_SYS = "You are good at using tools."

RL_TOOLS_SPEC: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "enhance_reasoning",
            "description": "tool to enhance answer model reasoning. analyze the problem, write code, execute it and return intermidiate results that will help solve the problem",
            "parameters": {
                "properties": {
                    "model": {
                        "description": "The model used to reason. Choices: ['reasoner-1', 'reasoner-2', 'reasoner-3']. reasoner-1 demonstrates strong understanding and reasoning capabilities, which usually provides reliable insights. reasoner-2 can analyze some problems, but could hallucinate and make mistakes in difficult scenarios. reasoner-3 can reason over the context and reveal the logic. \nModel | price per million input tokens | price per million output tokens | average latency\nreasoner-1 | $1.25 | $10 | 31s\nreasoner-2 | $0.25 | $2 | 25s\nreasoner-3 | $0.8 | $0.8 | 9s",
                        "type": "string",
                    }
                },
                "required": ["model"],
                "title": "parameters",
                "type": "object",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "answer",
            "description": "give the final answer. Not allowed to call if documents is empty.",
            "parameters": {
                "properties": {
                    "model": {
                        "description": "The model used to answer. Choices: ['answer-1', 'answer-2', 'answer-3', 'answer-4', 'answer-math-1', 'answer-math-2']. answer-1 exhibits strong functional calling abilities and performs excellent in most domains (math, physics, social science, etc.). answer-2 presents reasonable solutions in some tasks, but could get stuck in complex reasoning and specific domain knowledge. answer-3 could solve easy to medium tasks, but is not capable of tackling tasks with strong expertise and long-horizon planning. answer-4 demonstrates basic capability: it can understand basic instructions, do simple steps, yet it sometimes misreads details, mixes concepts. answer-math-1 can solve moderate (middle school) math problem, though it becomes incapable in more difficult tasks. answer-math-2 can follow simple instructions and perform easy (primary-level) math problems, but struggle in more complex logic. The table below shows the pricing and latency of each model:\nModel | price per million input tokens | price per million output tokens | average latency\nanswer-1 | $1.25 | $10 | 96s\nanswer-2 | $0.25 | $2 | 27s\nanswer-3 | $0.9 | $0.9 | 15s\nanswer-4 | $0.8 | $0.8 | 11s\nanswer-math-1 | $0.9 | $0.9 | 13s\nanswer-math-2 | $$0.2 | $0.2 | 9s",
                        "type": "string",
                    }
                },
                "required": ["model"],
                "title": "parameters",
                "type": "object",
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search for missing information",
            "parameters": {
                "properties": {
                    "model": {
                        "description": "The model used to search for missing information. Choices: ['search-1', 'search-2', 'search-3']. search-1 usually identifies the missing information and can write concise queries for effective search. search-2 can reason over the context and write queries to find the missing content for answering questions. search-3 can also write queries to find information. The table below shows the pricing and latency:\nModel | price per million input tokens | price per million output tokens | average latency\nsearch-1 | $1.25 | $10 | 22s\nsearch-2 | $0.25 | $2 | 16s\nsearch-3 | $0.8 | $0.8 | 8s",
                        "type": "string",
                    }
                },
                "required": ["model"],
                "title": "parameters",
                "type": "object",
            },
        },
    },
]

# RL_ALL_TOOLS: argument-validation schema (mirrors eval_hle.py:104).
RL_ALL_TOOLS: Dict[str, Dict[str, List[str]]] = {
    "enhance_reasoning": {"model": ["reasoner-1", "reasoner-2", "reasoner-3"]},
    "answer": {
        "model": [
            "answer-1",
            "answer-2",
            "answer-3",
            "answer-4",
            "answer-math-1",
            "answer-math-2",
        ],
    },
    "search": {"model": ["search-1", "search-2", "search-3"]},
}
