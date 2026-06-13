"""Tests for openjarvis.routing.a2a_chain.A2AChain."""

from __future__ import annotations

import pytest

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.registry import AgentRegistry
from openjarvis.routing.a2a_chain import A2AChain, ChainStep


class _AgentAlpha(BaseAgent):
    agent_id = "alpha"

    def run(self, input: str, context: AgentContext | None = None, **kwargs) -> AgentResult:
        return AgentResult(content=f"Alpha processed: {input}", turns=1)


class _AgentBeta(BaseAgent):
    agent_id = "beta"

    def run(self, input: str, context: AgentContext | None = None, **kwargs) -> AgentResult:
        return AgentResult(content=f"Beta processed: {input}", turns=1)


@pytest.fixture
def chain_setup(mock_engine, event_bus):
    AgentRegistry.register_value("alpha", _AgentAlpha)
    AgentRegistry.register_value("beta", _AgentBeta)
    engine = mock_engine()
    return engine, event_bus


class TestA2AChain:
    def test_single_step(self, chain_setup):
        engine, bus = chain_setup
        chain = A2AChain(
            steps=[ChainStep(agent_id="alpha")],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        assert result.content == "Alpha processed: Hello"
        assert result.turns == 1
        assert result.metadata["chain_steps"] == 1

    def test_two_step_pipeline(self, chain_setup):
        engine, bus = chain_setup
        chain = A2AChain(
            steps=[
                ChainStep(agent_id="alpha"),
                ChainStep(agent_id="beta"),
            ],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        # Beta receives Alpha's output as input via {previous} if template used,
        # but default template is {input}, so Beta gets original "Hello"
        assert "Beta processed:" in result.content
        assert result.metadata["chain_steps"] == 2

    def test_template_with_previous(self, chain_setup):
        engine, bus = chain_setup
        chain = A2AChain(
            steps=[
                ChainStep(agent_id="alpha"),
                ChainStep(
                    agent_id="beta",
                    input_template="Follow-up: {previous}",
                ),
            ],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        # AgentDelegateTool prepends context as [Context]...[Task]
        assert "Beta processed:" in result.content
        assert "Follow-up: Alpha processed: Hello" in result.content
        assert result.metadata["chain_steps"] == 2

    def test_from_string_simple(self, chain_setup):
        engine, bus = chain_setup
        chain = A2AChain.from_string(
            "alpha,beta",
            engine,
            "test-model",
            bus=bus,
        )
        assert len(chain._steps) == 2
        assert chain._steps[0].agent_id == "alpha"
        assert chain._steps[1].agent_id == "beta"

    def test_from_string_with_template(self, chain_setup):
        engine, bus = chain_setup
        chain = A2AChain.from_string(
            "alpha,beta>Review: {previous}",
            engine,
            "test-model",
            bus=bus,
        )
        assert chain._steps[1].input_template == "Review: {previous}"

    def test_empty_steps_raises(self, chain_setup):
        engine, bus = chain_setup
        with pytest.raises(ValueError, match="at least one step"):
            A2AChain([], engine, "test-model", bus=bus)

    def test_unregistered_agent_raises(self, chain_setup):
        engine, bus = chain_setup
        with pytest.raises(ValueError, match="not registered"):
            A2AChain(
                [ChainStep(agent_id="ghost")],
                engine,
                "test-model",
                bus=bus,
            )

    def test_failure_mid_chain(self, chain_setup):
        """If a step fails, the chain stops and reports the failing step."""
        engine, bus = chain_setup

        class _FailingAgent(BaseAgent):
            agent_id = "failing"

            def run(self, input, context=None, **kwargs):
                raise RuntimeError("boom")

        AgentRegistry.register_value("failing", _FailingAgent)

        chain = A2AChain(
            steps=[
                ChainStep(agent_id="alpha"),
                ChainStep(agent_id="failing"),
            ],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        assert result.metadata.get("chain_failed_at_step") == 2
        assert "boom" in result.content

    def test_input_template_variable(self, chain_setup):
        """{input} should be replaced with the original query."""
        engine, bus = chain_setup
        chain = A2AChain(
            steps=[
                ChainStep(
                    agent_id="alpha",
                    input_template="Task: {input}",
                ),
            ],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        assert "Task: Hello" in result.content

    def test_three_step_pipeline(self, chain_setup):
        """Chain with three steps should execute all and pass context."""
        engine, bus = chain_setup

        class _AgentGamma(BaseAgent):
            agent_id = "gamma"

            def run(self, input: str, context=None, **kwargs) -> AgentResult:
                return AgentResult(content=f"Gamma processed: {input}", turns=1)

        AgentRegistry.register_value("gamma", _AgentGamma)

        chain = A2AChain(
            steps=[
                ChainStep(agent_id="alpha"),
                ChainStep(agent_id="beta"),
                ChainStep(
                    agent_id="gamma",
                    input_template="Final review of: {previous}",
                ),
            ],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        assert "Gamma processed:" in result.content
        assert "Final review of: Beta processed:" in result.content
        assert result.metadata["chain_steps"] == 3
        assert len(result.metadata["step_results"]) == 3

    def test_combined_input_and_previous(self, chain_setup):
        """Template using both {input} and {previous} simultaneously."""
        engine, bus = chain_setup
        chain = A2AChain(
            steps=[
                ChainStep(agent_id="alpha"),
                ChainStep(
                    agent_id="beta",
                    input_template="Original: {input} | Previous: {previous}",
                ),
            ],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        assert "Original: Hello" in result.content
        assert "Previous: Alpha processed: Hello" in result.content

    def test_step_results_metadata(self, chain_setup):
        """Each step result should be recorded in metadata."""
        engine, bus = chain_setup
        chain = A2AChain(
            steps=[
                ChainStep(agent_id="alpha"),
                ChainStep(agent_id="beta"),
            ],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        step_results = result.metadata.get("step_results", [])
        assert len(step_results) == 2
        assert step_results[0]["step"] == 1
        assert step_results[0]["agent"] == "alpha"
        assert "Alpha processed: Hello" in step_results[0]["output"]
        assert step_results[1]["step"] == 2
        assert step_results[1]["agent"] == "beta"

    def test_sub_turns_aggregation(self, chain_setup):
        """Total turns should sum sub_turns from each step."""
        engine, bus = chain_setup

        class _MultiTurnAgent(BaseAgent):
            agent_id = "multiturn"

            def run(self, input: str, context=None, **kwargs) -> AgentResult:
                # Simulate an agent that uses 3 internal turns
                return AgentResult(
                    content=f"Multi: {input}",
                    turns=3,
                    metadata={"sub_turns": 3},
                )

        AgentRegistry.register_value("multiturn", _MultiTurnAgent)

        chain = A2AChain(
            steps=[
                ChainStep(agent_id="alpha"),   # 1 turn (default)
                ChainStep(agent_id="multiturn"), # 3 turns
            ],
            engine=engine,
            model="test-model",
            bus=bus,
        )
        result = chain.run("Hello")
        # Alpha has no sub_turns metadata, defaults to 1
        # multiturn has sub_turns=3
        assert result.turns == 4

    def test_from_string_single_step(self, chain_setup):
        """from_string with a single agent ID."""
        engine, bus = chain_setup
        chain = A2AChain.from_string(
            "alpha",
            engine,
            "test-model",
            bus=bus,
        )
        assert len(chain._steps) == 1
        assert chain._steps[0].agent_id == "alpha"
        assert chain._steps[0].input_template == "{input}"

    def test_from_string_empty_parts(self, chain_setup):
        """from_string should ignore empty/whitespace parts."""
        engine, bus = chain_setup
        chain = A2AChain.from_string(
            "alpha, , beta",
            engine,
            "test-model",
            bus=bus,
        )
        assert len(chain._steps) == 2
        assert chain._steps[0].agent_id == "alpha"
        assert chain._steps[1].agent_id == "beta"

    def test_chain_step_default_template(self):
        """ChainStep default input_template should be {input}."""
        step = ChainStep(agent_id="alpha")
        assert step.input_template == "{input}"
