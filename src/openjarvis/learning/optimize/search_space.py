"""Search space builder and default search space for configuration optimization."""

from __future__ import annotations

from typing import Any, Dict, List

from openjarvis.learning.optimize.types import SearchDimension, SearchSpace


def build_search_space(config: Dict[str, Any]) -> SearchSpace:
    """Build a SearchSpace from a TOML-style config dict.

    Expected format::

        {
            "optimize": {
                "search": [
                    {
                        "name": "agent.type",
                        "type": "categorical",
                        "values": ["orchestrator", "native_react"],
                        "description": "Agent architecture",
                    },
                    {
                        "name": "intelligence.temperature",
                        "type": "continuous",
                        "low": 0.0,
                        "high": 1.0,
                        "description": "Generation temperature",
                    },
                ],
                "fixed": {"engine": "ollama", "model": "qwen3:8b"},
                "constraints": {
                    "rules": ["SimpleAgent should only have max_turns = 1"],
                },
            }
        }
    """
    opt = config.get("optimize", {})
    search_entries: List[Dict[str, Any]] = opt.get("search", [])
    fixed: Dict[str, Any] = dict(opt.get("fixed", {}))
    constraints_sec = opt.get("constraints", {})
    constraints: List[str] = list(constraints_sec.get("rules", []))

    dimensions: List[SearchDimension] = []
    for entry in search_entries:
        # Infer primitive from the first segment of the dotted name
        name = entry.get("name", "")
        primitive = name.split(".")[0] if "." in name else ""

        dimensions.append(
            SearchDimension(
                name=name,
                dim_type=entry.get("type", "categorical"),
                values=list(entry.get("values", [])),
                low=entry.get("low"),
                high=entry.get("high"),
                description=entry.get("description", ""),
                primitive=primitive,
            )
        )

    return SearchSpace(
        dimensions=dimensions,
        fixed=fixed,
        constraints=constraints,
    )


# ---------------------------------------------------------------------------
# Default search space covering all 5 primitives
# ---------------------------------------------------------------------------

DEFAULT_SEARCH_SPACE = SearchSpace(
    dimensions=[
        # Intelligence primitive
        SearchDimension(
            name="intelligence.model",
            dim_type="categorical",
            values=[
                "qwen3:8b",
                "qwen3:4b",
                "qwen3:1.7b",
                "llama3.1:8b",
                "llama3.1:70b",
                "gemma2:9b",
                "mistral:7b",
                "deepseek-r1:8b",
            ],
            description="The LLM model to use for generation",
            primitive="intelligence",
        ),
        SearchDimension(
            name="intelligence.temperature",
            dim_type="continuous",
            low=0.0,
            high=1.0,
            description="Generation temperature (0 = deterministic, 1 = creative)",
            primitive="intelligence",
        ),
        SearchDimension(
            name="intelligence.max_tokens",
            dim_type="integer",
            low=256,
            high=8192,
            description="Maximum tokens to generate per response",
            primitive="intelligence",
        ),
        SearchDimension(
            name="intelligence.top_p",
            dim_type="continuous",
            low=0.0,
            high=1.0,
            description="Nucleus sampling probability threshold",
            primitive="intelligence",
        ),
        SearchDimension(
            name="intelligence.system_prompt",
            dim_type="text",
            description="System prompt to guide model behavior",
            primitive="intelligence",
        ),
        # Engine primitive
        SearchDimension(
            name="engine.backend",
            dim_type="categorical",
            values=[
                "ollama",
                "vllm",
                "sglang",
                "llamacpp",
                "mlx",
                "lmstudio",
                "exo",
                "nexa",
                "uzu",
                "apple_fm",
            ],
            description="Inference engine backend",
            primitive="engine",
        ),
        # Agent primitive
        SearchDimension(
            name="agent.type",
            dim_type="categorical",
            values=["simple", "orchestrator", "native_react", "native_openhands"],
            description="Agent architecture to use",
            primitive="agent",
        ),
        SearchDimension(
            name="agent.max_turns",
            dim_type="integer",
            low=1,
            high=30,
            description="Maximum number of agent reasoning turns",
            primitive="agent",
        ),
        # Tools primitive
        SearchDimension(
            name="tools.tool_set",
            dim_type="subset",
            values=[
                "calculator",
                "think",
                "file_read",
                "file_write",
                "web_search",
                "code_interpreter",
                "llm",
                "shell_exec",
                "apply_patch",
                "http_request",
                "database_query",
            ],
            description="Set of tools available to the agent",
            primitive="tools",
        ),
        # Learning primitive
        SearchDimension(
            name="learning.routing_policy",
            dim_type="categorical",
            values=["heuristic", "grpo", "bandit", "learned"],
            description="Router policy for model/agent selection",
            primitive="learning",
        ),
    ],
    fixed={},
    constraints=[
        "SimpleAgent (agent.type='simple') should only have max_turns = 1",
        "agent.max_turns must be >= 1",
        "intelligence.temperature and intelligence.top_p "
        "should not both be at extreme values",
    ],
)


__all__ = [
    "build_search_space",
    "DEFAULT_SEARCH_SPACE",
]
