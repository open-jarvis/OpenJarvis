"""Regression tests for the shared agent-construction seam.

``QueryOrchestrator._run_agent`` used to build the agent as::

    try:
        ag = agent_cls(engine, model, **agent_kwargs)
    except TypeError:
        ag = agent_cls(engine, model)      # no tools, no bus, no max_turns

``OrchestratorAgent.__init__`` declares neither ``capability_policy`` nor
``skill_few_shot_examples`` and takes no ``**kwargs``, so passing either one
raised ``TypeError`` and the fallback silently rebuilt the agent with an empty
tool list -- in exactly the two configurations you would want most: a
capability policy turned on, or a Skill contributing few-shot examples.

``AgentExecutor._invoke_agent_impl`` already filters by signature for the same
reason (see its comment). This seam is that fix, shared.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from openjarvis.agents._stubs import BaseAgent
from openjarvis.agents.orchestrator import OrchestratorAgent
from openjarvis.agents.simple import SimpleAgent
from openjarvis.core.config import AgentConfig
from openjarvis.core.registry import AgentRegistry
from openjarvis.system.agent_construction import (
    construct_registered_agent,
    resolve_agent_system_prompt,
)


class _KwargsAgentNoTools(BaseAgent):
    """Fixture mirroring e.g. LocalCloudAgent: accepts_tools=False but its
    ``__init__`` declares ``**kwargs``, so the signature check alone would
    let ``tools`` through -- the ``accepts_tools`` gate must catch it."""

    agent_id = "kwargs_no_tools"
    accepts_tools = False

    def __init__(self, engine, model, **kwargs):
        super().__init__(engine, model)
        self.received_kwargs = kwargs

    def run(self, input, context=None, **kwargs):
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _registered_agents():
    """conftest clears every registry per test, and the module-level
    ``@AgentRegistry.register`` decorators only ran on first import."""
    AgentRegistry.register_value("orchestrator", OrchestratorAgent)
    AgentRegistry.register_value("simple", SimpleAgent)
    AgentRegistry.register_value("kwargs_no_tools", _KwargsAgentNoTools)


class _FakeEngine:
    def generate(self, *args, **kwargs):
        raise NotImplementedError


class _FakeTool:
    class spec:
        name = "browser_click"
        description = "test tool"
        parameters: dict = {}
        required_capabilities: tuple = ()

    def execute(self, **params):
        raise NotImplementedError


def _build(**extra):
    kwargs = {"bus": None, "tools": [_FakeTool()], "max_turns": 5}
    kwargs.update(extra)
    return construct_registered_agent(
        agent_name="orchestrator",
        engine=_FakeEngine(),
        model="test-model",
        extra_kwargs=kwargs,
    )


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param({}, id="plain"),
        pytest.param({"capability_policy": object()}, id="with-policy"),
        pytest.param({"skill_few_shot_examples": ["example"]}, id="with-skills"),
        pytest.param(
            {
                "capability_policy": object(),
                "skill_few_shot_examples": ["example"],
                "operator_id": "op-1",
            },
            id="all-three",
        ),
    ],
)
def test_agent_keeps_its_tools(extra):
    """A keyword the agent does not declare must not cost it its tools."""
    agent = _build(**extra)
    assert len(agent._tools) == 1


def test_unsupported_keyword_is_dropped_not_raised():
    agent = _build(definitely_not_a_real_parameter=object())
    assert len(agent._tools) == 1


def test_tools_withheld_from_agents_that_reject_them():
    """``tools`` is gated on ``accepts_tools``, unlike the other keywords."""
    assert getattr(OrchestratorAgent, "accepts_tools", False) is True
    agent = construct_registered_agent(
        agent_name="simple",
        engine=_FakeEngine(),
        model="test-model",
        tools=[_FakeTool()],
    )
    assert not getattr(agent, "_tools", [])


def test_tools_via_extra_kwargs_dropped_for_kwargs_target_that_rejects_tools():
    """The ``accepts_tools`` gate must hold for the ``extra_kwargs`` path too,
    not just the named ``tools=`` argument -- otherwise a target with
    ``**kwargs`` and ``accepts_tools=False`` bypasses the signature check and
    either crashes on an unexpected keyword or (worse) silently gets tools it
    declared it does not accept."""
    agent = construct_registered_agent(
        agent_name="kwargs_no_tools",
        engine=_FakeEngine(),
        model="test-model",
        extra_kwargs={"tools": [_FakeTool()]},
    )
    assert "tools" not in agent.received_kwargs


def test_tools_still_delivered_to_accepting_agents_via_both_paths():
    """Unchanged behaviour: an ``accepts_tools=True`` agent still gets its
    tools whether they arrive via the named ``tools=`` kwarg or via
    ``extra_kwargs``."""
    via_named = construct_registered_agent(
        agent_name="orchestrator",
        engine=_FakeEngine(),
        model="test-model",
        tools=[_FakeTool()],
    )
    assert len(via_named._tools) == 1

    via_extra = construct_registered_agent(
        agent_name="orchestrator",
        engine=_FakeEngine(),
        model="test-model",
        extra_kwargs={"tools": [_FakeTool()]},
    )
    assert len(via_extra._tools) == 1


def test_inline_system_prompt_wins_over_path(tmp_path):
    path = tmp_path / "prompt.md"
    path.write_text("from file", encoding="utf-8")

    config = AgentConfig(system_prompt="inline", system_prompt_path=str(path))
    assert resolve_agent_system_prompt(config) == "inline"

    config = AgentConfig(system_prompt="", system_prompt_path=str(path))
    assert resolve_agent_system_prompt(config) == "from file"

    assert resolve_agent_system_prompt(AgentConfig()) is None


def test_unreadable_prompt_path_is_a_startup_error():
    """Falling back to generic behavior would silently drop the instructions."""
    config = AgentConfig(system_prompt_path="/nonexistent/prompt.md")
    with pytest.raises(RuntimeError, match="not readable"):
        resolve_agent_system_prompt(config)


def test_run_agent_has_no_tool_swallowing_fallback():
    import openjarvis.system.orchestrator as orchestrator_module

    tree = ast.parse(inspect.getsource(orchestrator_module))
    swallowers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and getattr(node.type, "id", None) == "TypeError"
    ]
    assert not swallowers


def test_run_agent_uses_the_shared_seam():
    import openjarvis.system.orchestrator as orchestrator_module

    assert "construct_registered_agent(" in inspect.getsource(orchestrator_module)
