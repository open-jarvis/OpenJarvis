"""AgentExecutor — runs a single agent tick."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from openjarvis.agents.errors import (
    AgentTickError,
    EscalateError,
    FatalError,
    classify_error,
    retry_delay,
)
from openjarvis.core.events import EventBus, EventType

if TYPE_CHECKING:
    from openjarvis.agents.manager import AgentManager

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class AgentExecutor:
    """Executes a single tick for a managed agent.

    Constructor receives a JarvisSystem reference for access to engine,
    tools, config, memory backends, and all other primitives.
    """

    def __init__(
        self,
        manager: AgentManager,
        event_bus: EventBus,
        system: Any = None,
    ) -> None:
        self._system = system
        self._manager = manager
        self._bus = event_bus

    def set_system(self, system: Any) -> None:
        """Deferred system injection — called after JarvisSystem is constructed."""
        self._system = system

    def execute_tick(self, agent_id: str) -> None:
        """Run one tick for the given agent.

        1. Acquire concurrency guard (start_tick)
        2. Invoke agent with retry logic
        3. Update stats
        4. Release guard (end_tick)
        """
        try:
            self._manager.start_tick(agent_id)
        except ValueError:
            logger.warning("Agent %s already running, skipping tick", agent_id)
            return

        agent = self._manager.get_agent(agent_id)
        if agent is None:
            logger.error("Agent %s not found", agent_id)
            return

        self._bus.publish(EventType.AGENT_TICK_START, {
            "agent_id": agent_id,
            "agent_name": agent["name"],
        })

        tick_start = time.time()
        result = None
        error_info = None

        try:
            result = self._run_with_retries(agent)
        except AgentTickError as e:
            error_info = e
        finally:
            tick_duration = time.time() - tick_start
            self._finalize_tick(agent_id, result, error_info, tick_duration)

    def _run_with_retries(self, agent: dict) -> str:
        """Invoke the agent, retrying on RetryableError up to _MAX_RETRIES."""
        last_error: AgentTickError | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                return self._invoke_agent(agent)
            except AgentTickError as e:
                if not e.retryable or attempt == _MAX_RETRIES - 1:
                    raise
                last_error = e
                delay = retry_delay(attempt)
                logger.info(
                    "Agent %s tick retry %d/%d in %ds: %s",
                    agent["id"], attempt + 1, _MAX_RETRIES, delay, e,
                )
                time.sleep(delay)
            except Exception as e:
                classified = classify_error(e)
                if not classified.retryable or attempt == _MAX_RETRIES - 1:
                    raise classified from e
                delay = retry_delay(attempt)
                logger.info(
                    "Agent %s tick retry %d/%d in %ds: %s",
                    agent["id"], attempt + 1, _MAX_RETRIES, delay, e,
                )
                time.sleep(delay)

        # Should not reach here, but just in case
        raise last_error or FatalError("max retries exhausted")

    def _invoke_agent(self, agent: dict) -> str:
        """Invoke the actual agent run. Tests mock this method."""
        from openjarvis.agents import AgentRegistry

        agent_type = agent.get("agent_type", "monitor_operative")
        agent_cls = AgentRegistry.get(agent_type)
        if agent_cls is None:
            raise FatalError(f"Unknown agent type: {agent_type}")

        config = agent.get("config", {})

        # Resolve engine + model from JarvisSystem
        engine = self._system.engine if self._system else None
        if engine is None:
            raise FatalError("No engine available in JarvisSystem")
        model = config.get("model") or (
            self._system.model
            if self._system else ""
        )
        if not model:
            raise FatalError("No model configured for agent")

        # Construct agent instance (BaseAgent requires engine, model as positional args)
        agent_instance = agent_cls(
            engine,
            model,
            system_prompt=config.get("system_prompt"),
            tools=[],
        )

        # Build input from summary_memory + pending messages
        context = agent.get("summary_memory", "") or "Continue your assigned task."
        pending = self._manager.get_pending_messages(agent["id"])
        if pending:
            user_msgs = "\n".join(f"User: {m['content']}" for m in pending)
            context = f"{context}\n\nNew instructions:\n{user_msgs}"
            for m in pending:
                self._manager.mark_message_delivered(m["id"])

        # AgentResult has a .content attribute (str)
        result = agent_instance.run(context)
        return result.content

    def _finalize_tick(
        self,
        agent_id: str,
        result: str | None,
        error: AgentTickError | None,
        duration: float,
    ) -> None:
        """Update agent state after tick completion or failure."""
        if error is None:
            # Success
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, total_runs_increment=1)
            if result:
                self._manager.update_summary_memory(
                    agent_id, result[:2000],
                )
                self._manager.store_agent_response(agent_id, result[:2000])
            self._bus.publish(EventType.AGENT_TICK_END, {
                "agent_id": agent_id,
                "duration": duration,
                "status": "ok",
            })
        elif isinstance(error, EscalateError):
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, status="needs_attention")
            self._bus.publish(EventType.AGENT_TICK_ERROR, {
                "agent_id": agent_id,
                "error": str(error),
                "error_type": "escalate",
                "duration": duration,
            })
        else:
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, status="error")
            self._bus.publish(EventType.AGENT_TICK_ERROR, {
                "agent_id": agent_id,
                "error": str(error),
                "error_type": (
                    "fatal" if isinstance(error, FatalError) else "retryable_exhausted"
                ),
                "duration": duration,
            })
