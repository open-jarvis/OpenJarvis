"""TauBench task environment — native OpenJarvis agent in tau2 simulation.

Plugs OpenJarvis's inference engine into tau2-bench's orchestrator as a
``HalfDuplexAgent``, so the multi-turn conversation loop, user simulator,
domain tools, database, and evaluation all come from tau2-bench while the
agent's LLM calls go through OpenJarvis.
"""

from __future__ import annotations

import json
import logging
from types import TracebackType
from typing import Any, Optional, Type

from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message conversion helpers
# ---------------------------------------------------------------------------


def _tau2_to_oj_messages(
    tau2_messages: list,
) -> list:
    """Convert tau2 Message objects to OpenJarvis Message objects."""
    from openjarvis.core.types import Message, Role
    from openjarvis.core.types import ToolCall as OJToolCall

    oj_msgs: list = []
    for m in tau2_messages:
        role_str = getattr(m, "role", "user")
        if role_str == "system":
            oj_msgs.append(Message(role=Role.SYSTEM, content=m.content or ""))
        elif role_str == "user":
            oj_msgs.append(Message(role=Role.USER, content=m.content or ""))
        elif role_str == "assistant":
            tc_list = getattr(m, "tool_calls", None)
            if tc_list:
                oj_tool_calls = [
                    OJToolCall(
                        id=tc.id,
                        name=tc.name,
                        arguments=(
                            json.dumps(tc.arguments)
                            if isinstance(tc.arguments, dict)
                            else str(tc.arguments)
                        ),
                    )
                    for tc in tc_list
                ]
                oj_msgs.append(
                    Message(
                        role=Role.ASSISTANT,
                        content=m.content or "",
                        tool_calls=oj_tool_calls,
                    )
                )
            else:
                oj_msgs.append(Message(role=Role.ASSISTANT, content=m.content or ""))
        elif role_str == "tool":
            # tau2 ToolMessage uses 'id', not 'tool_call_id'
            raw_id = getattr(m, "id", "") or getattr(m, "tool_call_id", "") or ""
            import re as _re

            clean_id = _re.sub(r"[^a-zA-Z0-9_-]", "_", raw_id)
            oj_msgs.append(
                Message(
                    role=Role.TOOL,
                    content=m.content or "",
                    tool_call_id=clean_id,
                    name=getattr(m, "name", ""),
                )
            )
    return oj_msgs


def _oj_result_to_tau2_msg(result: dict):
    """Convert OpenJarvis engine.generate() result to a tau2 AssistantMessage."""
    from tau2.data_model.message import AssistantMessage, ToolCall

    raw_tool_calls = result.get("tool_calls", [])
    tool_calls = None
    if raw_tool_calls:
        tool_calls = [
            ToolCall(
                id=tc.get("id", ""),
                name=tc.get("name", ""),
                arguments=(
                    json.loads(tc["arguments"])
                    if isinstance(tc.get("arguments"), str)
                    else tc.get("arguments", {})
                ),
                requestor="assistant",
            )
            for tc in raw_tool_calls
        ]

    return AssistantMessage(
        role="assistant",
        content=result.get("content") or None,
        tool_calls=tool_calls,
        cost=result.get("cost_usd", 0.0),
    )


# ---------------------------------------------------------------------------
# Jarvis-powered tau2 agent
# ---------------------------------------------------------------------------


class JarvisHalfDuplexAgent:
    """A tau2 HalfDuplexAgent backed by OpenJarvis's inference engine.

    Replaces tau2's built-in LLMAgent while keeping the same interface
    so the Orchestrator, UserSimulator, and evaluation work unchanged.
    """

    STOP = "###STOP###"

    def __init__(
        self,
        tools: list,
        domain_policy: str,
        engine: Any,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self.tools = tools
        self.domain_policy = domain_policy
        self._engine = engine
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    @property
    def system_prompt(self) -> str:
        from tau2.agent.llm_agent import AGENT_INSTRUCTION, SYSTEM_PROMPT

        return SYSTEM_PROMPT.format(
            domain_policy=self.domain_policy,
            agent_instruction=AGENT_INSTRUCTION,
        )

    def get_init_state(self, message_history=None):
        from tau2.agent.llm_agent import LLMAgentState
        from tau2.data_model.message import SystemMessage

        return LLMAgentState(
            system_messages=[
                SystemMessage(role="system", content=self.system_prompt),
            ],
            messages=list(message_history) if message_history else [],
        )

    def generate_next_message(self, message, state):
        from tau2.data_model.message import MultiToolMessage

        # Add incoming message to conversation state
        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
        elif message is not None:
            state.messages.append(message)

        # Convert to OpenJarvis format
        oj_messages = _tau2_to_oj_messages(
            state.system_messages + state.messages,
        )

        # Build OpenAI tool schemas from tau2 tools
        openai_tools = [t.openai_schema for t in self.tools]

        # Call OpenJarvis engine
        gen_kwargs: dict = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "tools": openai_tools,
            "tool_choice": "auto",
        }
        # Disable thinking mode for local models (Qwen3.5 etc.)
        # to avoid <think> tags interfering with tool call parsing
        if "qwen" in self._model.lower():
            gen_kwargs["chat_template_kwargs"] = {
                "enable_thinking": False,
            }
        result = self._engine.generate(oj_messages, **gen_kwargs)

        # Convert result to tau2 AssistantMessage
        assistant_msg = _oj_result_to_tau2_msg(result)
        state.messages.append(assistant_msg)
        return assistant_msg, state

    @classmethod
    def is_stop(cls, message) -> bool:
        if hasattr(message, "is_tool_call") and message.is_tool_call():
            return False
        content = getattr(message, "content", "") or ""
        return cls.STOP in content

    def set_seed(self, seed: int) -> None:
        pass

    def stop(self, *args, **kwargs) -> None:
        """Cleanup hook called by orchestrator."""
        pass


# ---------------------------------------------------------------------------
# Task environment
# ---------------------------------------------------------------------------


class TauBenchTaskEnv:
    """Per-task environment for TauBench evaluation.

    Creates an OpenJarvis-powered agent, plugs it into tau2's orchestrator,
    runs the simulation, and stores results in record.metadata for the scorer.
    """

    # Thread-safety marker for the eval runner. tau2 simulations are pure
    # in-process (LLM calls + tau2 orchestrator state held inside this
    # instance) — no CWD changes, no shared mutable globals — so multiple
    # TauBenchTaskEnv instances can run in parallel threads safely.
    THREAD_SAFE = True

    def __init__(
        self,
        record: EvalRecord,
        engine_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        user_model: Optional[str] = None,
        num_trials: int = 1,
        telemetry: bool = False,
        gpu_metrics: bool = False,
    ) -> None:
        self._record = record
        self._num_trials = num_trials
        self._engine_key = engine_key
        self._model = model or "claude-opus-4-6"
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._user_model = user_model or "gpt-5-mini-2025-08-07"
        self._telemetry = telemetry
        self._gpu_metrics = gpu_metrics
        self._system = None

    def __enter__(self) -> TauBenchTaskEnv:
        # Build OpenJarvis system for engine access
        from openjarvis.system import SystemBuilder

        builder = SystemBuilder()
        if self._engine_key:
            builder.engine(self._engine_key)
        if self._gpu_metrics:
            builder._config.telemetry.gpu_metrics = True
        self._system = builder.telemetry(self._telemetry).build()

        # Run the simulation
        self._run_simulation()
        return self

    def _run_simulation(self) -> None:
        from tau2.evaluator.evaluator import EvaluationType
        from tau2.orchestrator.orchestrator import Orchestrator
        from tau2.runner.build import build_environment, build_user
        from tau2.runner.helpers import get_tasks
        from tau2.runner.simulation import run_simulation

        domain = self._record.metadata["domain"]
        task_id = self._record.metadata["task_id"]

        tasks = get_tasks(domain, task_ids=[task_id])
        if not tasks:
            LOGGER.error("Task %s not found in domain %s", task_id, domain)
            self._record.metadata["tau_reward"] = 0.0
            self._record.metadata["is_resolved"] = False
            return

        task = tasks[0]
        best_reward = 0.0
        best_info: dict = {}
        best_n_messages = 0

        # Run multiple trials, keep best result (pass^k)
        for trial in range(self._num_trials):
            try:
                environment = build_environment(domain)

                agent = JarvisHalfDuplexAgent(
                    tools=environment.get_tools(),
                    domain_policy=environment.get_policy(),
                    engine=self._system.engine,
                    model=self._model,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                )

                user = build_user(
                    "user_simulator",
                    environment,
                    task,
                    llm=self._user_model,
                )

                orchestrator = Orchestrator(
                    domain=domain,
                    agent=agent,
                    user=user,
                    environment=environment,
                    task=task,
                    max_steps=200,
                    seed=42 + trial,
                )

                simulation = run_simulation(
                    orchestrator,
                    evaluation_type=EvaluationType.ALL_WITH_NL_ASSERTIONS,
                )

                reward = (
                    simulation.reward_info.reward if simulation.reward_info else 0.0
                )
                info: dict = {}
                if simulation.reward_info:
                    info = simulation.reward_info.info or {}
                    if simulation.reward_info.reward_breakdown:
                        info["reward_breakdown"] = {
                            k.value if hasattr(k, "value") else str(k): v
                            for k, v in simulation.reward_info.reward_breakdown.items()
                        }
                n_messages = len(simulation.messages) if simulation.messages else 0

                trial_label = (
                    f" (trial {trial + 1}/{self._num_trials})"
                    if self._num_trials > 1
                    else ""
                )
                LOGGER.info(
                    "TauBench %s/%s: reward=%.2f messages=%d%s",
                    domain,
                    task_id,
                    reward,
                    n_messages,
                    trial_label,
                )

                if reward > best_reward:
                    best_reward = reward
                    best_info = info
                    best_n_messages = n_messages

                # Early exit if perfect score
                if reward >= 1.0:
                    break

            except Exception as exc:
                LOGGER.error(
                    "TauBench simulation failed for %s/%s: %s",
                    domain,
                    task_id,
                    exc,
                )

        self._record.metadata["tau_reward"] = best_reward
        self._record.metadata["tau_info"] = best_info
        self._record.metadata["tau_n_messages"] = best_n_messages
        self._record.metadata["tau_num_trials"] = self._num_trials
        self._record.metadata["is_resolved"] = best_reward >= 0.5

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._system:
            try:
                self._system.close()
            except Exception:
                pass
            self._system = None


__all__ = ["TauBenchTaskEnv"]
