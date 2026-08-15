from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from openjarvis.agents._stubs import (
    _RUN_PERSISTENCE,
    _RUN_WORKER_LEASE,
    AgentContext,
    AgentPersistenceStaging,
    AgentResult,
    AgentRunCompleted,
    AgentStreamEvent,
    AgentWorkerLease,
    BaseAgent,
)
from openjarvis.tools.mcp_adapter import MCPToolAdapter


@dataclass(frozen=True, slots=True)
class AgentCapabilitySnapshot:
    agent_id: str
    model: str
    tool_names: tuple[str, ...]
    mcp_tool_names: tuple[str, ...]
    data_source_configuration: "DataSourceConfigurationSnapshot"
    persistent_identity: str | None
    capability_policy: Any = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class DataSourceConfigurationSnapshot:
    enabled: bool
    backend_id: str
    top_k: int
    min_score: float
    max_context_tokens: int


@dataclass(frozen=True, slots=True)
class AgentExecutionBinding:
    _runtime: "NativeAgentRuntime" = field(repr=False, compare=False)
    snapshot: AgentCapabilitySnapshot

    @property
    def model(self) -> str:
        return self.snapshot.model

    async def run_stream(
        self,
        input: str,
        context: AgentContext,
        *,
        persistence_key: str | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        async for event in self._runtime._run_stream(
            self, input, context, persistence_key=persistence_key
        ):
            yield event

    async def run(
        self,
        input: str,
        context: AgentContext,
        *,
        persistence_key: str | None = None,
    ) -> AgentResult:
        completed: AgentResult | None = None
        async for event in self.run_stream(
            input, context, persistence_key=persistence_key
        ):
            if isinstance(event, AgentRunCompleted):
                completed = event.result
        if completed is None:
            raise RuntimeError("agent_stream_incomplete")
        return completed

    async def commit_persistence(self, persistence_key: str) -> None:
        """Make the answer-derived writes of a staged turn durable."""
        await self._runtime._settle_persistence(persistence_key, commit=True)

    async def discard_persistence(self, persistence_key: str) -> None:
        """Drop the answer-derived writes of a turn the caller never accepted."""
        await self._runtime._settle_persistence(persistence_key, commit=False)


class NativeAgentRuntime:
    def __init__(
        self,
        agent: BaseAgent,
        *,
        data_source_configuration: DataSourceConfigurationSnapshot | None = None,
    ) -> None:
        self._agent = agent
        self._lock = asyncio.Lock()
        self._staged_persistence: dict[str, AgentPersistenceStaging] = {}
        self._data_source_configuration = data_source_configuration or (
            DataSourceConfigurationSnapshot(False, "", 0, 0.0, 0)
        )

    @property
    def agent(self) -> BaseAgent:
        return self._agent

    def bind(self, *, model: str) -> AgentExecutionBinding:
        if not model.strip():
            raise ValueError("agent_model_required")
        tools = tuple(getattr(self._agent, "_tools", ()))
        executor = getattr(self._agent, "_executor", None)
        snapshot = AgentCapabilitySnapshot(
            agent_id=getattr(self._agent, "agent_id", type(self._agent).__name__),
            model=model,
            tool_names=tuple(tool.spec.name for tool in tools),
            mcp_tool_names=tuple(
                tool.spec.name for tool in tools if isinstance(tool, MCPToolAdapter)
            ),
            data_source_configuration=self._data_source_configuration,
            persistent_identity=getattr(self._agent, "_operator_id", None),
            capability_policy=getattr(executor, "_capability_policy", None),
        )
        return AgentExecutionBinding(self, snapshot)

    async def _settle_persistence(self, persistence_key: str, *, commit: bool) -> None:
        staging = self._staged_persistence.pop(persistence_key, None)
        if staging is None:
            return
        if commit:
            await asyncio.to_thread(staging.commit)
        else:
            staging.discard()

    async def _run_stream(
        self,
        binding: AgentExecutionBinding,
        input: str,
        context: AgentContext,
        *,
        persistence_key: str | None = None,
    ) -> AsyncIterator[AgentStreamEvent]:
        await self._lock.acquire()
        worker_lease = AgentWorkerLease()
        staging = AgentPersistenceStaging()
        worker_token = _RUN_WORKER_LEASE.set(worker_lease)
        staging_token = _RUN_PERSISTENCE.set(staging)
        drained = False
        try:
            async for event in self._agent.run_stream(
                input,
                context,
                model=binding.model,
            ):
                yield event
            drained = True
        finally:
            # Arrange the release before anything that can raise: an abandoned
            # stream is finalized by asyncio in its own Task, where resetting a
            # token raises, and a lost release strands the lock forever. Waiters
            # only wake once this handler yields, so the rest still runs first.
            worker_lease.when_settled(self._lock.release)
            if not drained:
                # The caller never saw the answer through, so nothing derived
                # from it may reach a durable store.
                staging.discard()
            elif persistence_key is None:
                staging.commit()
            else:
                # Held until the caller confirms the turn actually landed —
                # for Voice, when the browser reports the text as played.
                self._staged_persistence[persistence_key] = staging
            for context_token, context_var in (
                (staging_token, _RUN_PERSISTENCE),
                (worker_token, _RUN_WORKER_LEASE),
            ):
                try:
                    context_var.reset(context_token)
                except ValueError:
                    # That foreign Context never saw the set(), and the Context
                    # that did dies with the task that abandoned this stream.
                    pass
