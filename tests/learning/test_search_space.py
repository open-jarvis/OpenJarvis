"""Tests for openjarvis.optimize.search_space module."""

from __future__ import annotations

from openjarvis.optimize.search_space import (
    DEFAULT_SEARCH_SPACE,
    build_search_space,
)
from openjarvis.optimize.types import SearchSpace

# ---------------------------------------------------------------------------
# build_search_space
# ---------------------------------------------------------------------------


class TestBuildSearchSpace:
    """Tests for the build_search_space() factory function."""

    def test_basic_build(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "agent.type",
                        "type": "categorical",
                        "values": [
                            "orchestrator",
                            "native_react",
                        ],
                        "description": "Agent architecture",
                    },
                ],
                "fixed": {
                    "engine": "ollama",
                    "model": "qwen3:8b",
                },
                "constraints": {
                    "rules": [
                        "SimpleAgent should only have max_turns = 1",
                    ],
                },
            },
        }
        space = build_search_space(config)
        assert isinstance(space, SearchSpace)
        assert len(space.dimensions) == 1
        dim = space.dimensions[0]
        assert dim.name == "agent.type"
        assert dim.dim_type == "categorical"
        assert dim.values == ["orchestrator", "native_react"]
        assert dim.description == "Agent architecture"
        assert dim.primitive == "agent"

    def test_fixed_params_preserved(self) -> None:
        config = {
            "optimize": {
                "search": [],
                "fixed": {
                    "engine": "ollama",
                    "model": "qwen3:8b",
                },
            },
        }
        space = build_search_space(config)
        assert space.fixed == {
            "engine": "ollama",
            "model": "qwen3:8b",
        }

    def test_constraints_parsed(self) -> None:
        config = {
            "optimize": {
                "search": [],
                "constraints": {
                    "rules": [
                        "max_turns must be >= 1",
                        "temperature should be <= 1.0",
                    ],
                },
            },
        }
        space = build_search_space(config)
        assert len(space.constraints) == 2
        assert "max_turns must be >= 1" in space.constraints
        assert "temperature should be <= 1.0" in space.constraints

    def test_continuous_dimension_build(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "intelligence.temperature",
                        "type": "continuous",
                        "low": 0.0,
                        "high": 1.0,
                        "description": "Generation temperature",
                    },
                ],
            },
        }
        space = build_search_space(config)
        dim = space.dimensions[0]
        assert dim.dim_type == "continuous"
        assert dim.low == 0.0
        assert dim.high == 1.0
        assert dim.primitive == "intelligence"

    def test_integer_dimension_build(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "agent.max_turns",
                        "type": "integer",
                        "low": 1,
                        "high": 30,
                    },
                ],
            },
        }
        space = build_search_space(config)
        dim = space.dimensions[0]
        assert dim.dim_type == "integer"
        assert dim.low == 1
        assert dim.high == 30

    def test_subset_dimension_build(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "tools.tool_set",
                        "type": "subset",
                        "values": [
                            "calculator",
                            "think",
                            "web_search",
                        ],
                    },
                ],
            },
        }
        space = build_search_space(config)
        dim = space.dimensions[0]
        assert dim.dim_type == "subset"
        assert dim.values == [
            "calculator",
            "think",
            "web_search",
        ]
        assert dim.primitive == "tools"

    def test_text_dimension_build(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "intelligence.system_prompt",
                        "type": "text",
                        "description": "System prompt",
                    },
                ],
            },
        }
        space = build_search_space(config)
        dim = space.dimensions[0]
        assert dim.dim_type == "text"
        assert dim.values == []
        assert dim.primitive == "intelligence"

    def test_multiple_dimensions(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "agent.type",
                        "type": "categorical",
                        "values": ["simple"],
                    },
                    {
                        "name": "intelligence.temperature",
                        "type": "continuous",
                        "low": 0.0,
                        "high": 1.0,
                    },
                    {
                        "name": "tools.tool_set",
                        "type": "subset",
                        "values": ["calculator"],
                    },
                ],
            },
        }
        space = build_search_space(config)
        assert len(space.dimensions) == 3

    def test_empty_config(self) -> None:
        space = build_search_space({})
        assert space.dimensions == []
        assert space.fixed == {}
        assert space.constraints == []

    def test_empty_optimize_section(self) -> None:
        space = build_search_space({"optimize": {}})
        assert space.dimensions == []
        assert space.fixed == {}
        assert space.constraints == []

    def test_primitive_inferred_from_name(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "learning.routing_policy",
                        "type": "categorical",
                        "values": ["grpo"],
                    },
                    {
                        "name": "engine.backend",
                        "type": "categorical",
                        "values": ["ollama"],
                    },
                ],
            },
        }
        space = build_search_space(config)
        assert space.dimensions[0].primitive == "learning"
        assert space.dimensions[1].primitive == "engine"

    def test_no_dot_in_name_gives_empty_primitive(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "standalone",
                        "type": "categorical",
                        "values": ["a"],
                    },
                ],
            },
        }
        space = build_search_space(config)
        assert space.dimensions[0].primitive == ""

    def test_missing_description_defaults_empty(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "agent.type",
                        "type": "categorical",
                        "values": ["simple"],
                    },
                ],
            },
        }
        space = build_search_space(config)
        assert space.dimensions[0].description == ""

    def test_missing_values_defaults_empty_list(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "agent.type",
                        "type": "categorical",
                    },
                ],
            },
        }
        space = build_search_space(config)
        assert space.dimensions[0].values == []

    def test_missing_constraints_section(self) -> None:
        config = {
            "optimize": {
                "search": [
                    {
                        "name": "a.b",
                        "type": "categorical",
                        "values": ["x"],
                    },
                ],
                "fixed": {"k": "v"},
            },
        }
        space = build_search_space(config)
        assert space.constraints == []


# ---------------------------------------------------------------------------
# DEFAULT_SEARCH_SPACE
# ---------------------------------------------------------------------------


_DIMS = DEFAULT_SEARCH_SPACE.dimensions


def _find_dim(name: str):
    """Helper to find a dimension by name."""
    return next(d for d in _DIMS if d.name == name)


class TestDefaultSearchSpace:
    """Tests for the DEFAULT_SEARCH_SPACE module-level constant."""

    def test_is_search_space(self) -> None:
        assert isinstance(DEFAULT_SEARCH_SPACE, SearchSpace)

    def test_has_all_five_primitives(self) -> None:
        primitives = {dim.primitive for dim in _DIMS}
        assert "intelligence" in primitives
        assert "engine" in primitives
        assert "agent" in primitives
        assert "tools" in primitives
        assert "learning" in primitives

    def test_intelligence_dimensions(self) -> None:
        intel_dims = [d for d in _DIMS if d.primitive == "intelligence"]
        intel_names = {d.name for d in intel_dims}
        assert "intelligence.model" in intel_names
        assert "intelligence.temperature" in intel_names
        assert "intelligence.max_tokens" in intel_names
        assert "intelligence.top_p" in intel_names
        assert "intelligence.system_prompt" in intel_names

    def test_intelligence_model_is_categorical(self) -> None:
        dim = _find_dim("intelligence.model")
        assert dim.dim_type == "categorical"
        assert len(dim.values) > 0

    def test_intelligence_temperature_range(self) -> None:
        dim = _find_dim("intelligence.temperature")
        assert dim.dim_type == "continuous"
        assert dim.low == 0.0
        assert dim.high == 1.0

    def test_intelligence_max_tokens_range(self) -> None:
        dim = _find_dim("intelligence.max_tokens")
        assert dim.dim_type == "integer"
        assert dim.low == 256
        assert dim.high == 8192

    def test_intelligence_system_prompt_is_text(self) -> None:
        dim = _find_dim("intelligence.system_prompt")
        assert dim.dim_type == "text"

    def test_engine_backend_options(self) -> None:
        dim = _find_dim("engine.backend")
        assert dim.dim_type == "categorical"
        expected = {
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
        }
        assert set(dim.values) == expected

    def test_agent_type_options(self) -> None:
        dim = _find_dim("agent.type")
        assert dim.dim_type == "categorical"
        expected = {
            "simple",
            "orchestrator",
            "native_react",
            "native_openhands",
        }
        assert set(dim.values) == expected

    def test_agent_max_turns_range(self) -> None:
        dim = _find_dim("agent.max_turns")
        assert dim.dim_type == "integer"
        assert dim.low == 1
        assert dim.high == 30

    def test_tools_tool_set_is_subset(self) -> None:
        dim = _find_dim("tools.tool_set")
        assert dim.dim_type == "subset"
        assert "calculator" in dim.values
        assert "think" in dim.values

    def test_learning_routing_policy(self) -> None:
        dim = _find_dim("learning.routing_policy")
        assert dim.dim_type == "categorical"
        expected = {"heuristic", "grpo", "bandit", "learned"}
        assert set(dim.values) == expected

    def test_has_constraints(self) -> None:
        assert len(DEFAULT_SEARCH_SPACE.constraints) > 0

    def test_all_dimensions_have_descriptions(self) -> None:
        for dim in _DIMS:
            assert dim.description != "", f"Dimension {dim.name} has no description"

    def test_all_dimensions_have_primitives(self) -> None:
        for dim in _DIMS:
            assert dim.primitive != "", f"Dimension {dim.name} has no primitive"


# ---------------------------------------------------------------------------
# to_prompt_description rendering
# ---------------------------------------------------------------------------


class TestToPromptDescription:
    """Tests for SearchSpace.to_prompt_description()."""

    def test_default_space_renders(self) -> None:
        desc = DEFAULT_SEARCH_SPACE.to_prompt_description()
        assert isinstance(desc, str)
        assert len(desc) > 100

    def test_all_dimensions_appear_in_description(self) -> None:
        desc = DEFAULT_SEARCH_SPACE.to_prompt_description()
        for dim in _DIMS:
            assert dim.name in desc, f"Dimension {dim.name} not in description"

    def test_all_primitive_headers_in_description(self) -> None:
        desc = DEFAULT_SEARCH_SPACE.to_prompt_description()
        for primitive in (
            "Intelligence",
            "Engine",
            "Agent",
            "Tools",
            "Learning",
        ):
            assert f"## {primitive}" in desc, (
                f"Primitive header {primitive} not in description"
            )

    def test_constraints_in_description(self) -> None:
        desc = DEFAULT_SEARCH_SPACE.to_prompt_description()
        assert "## Constraints" in desc
        for constraint in DEFAULT_SEARCH_SPACE.constraints:
            assert constraint in desc

    def test_empty_space_renders(self) -> None:
        space = SearchSpace()
        desc = space.to_prompt_description()
        assert "# Search Space" in desc
        assert "## Fixed Parameters" not in desc
        assert "## Constraints" not in desc
