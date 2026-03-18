"""AgentExecutor — runs a single agent tick."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from openjarvis.agents._stubs import AgentResult
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
        trace_store: Any = None,
    ) -> None:
        self._system = system
        self._manager = manager
        self._bus = event_bus
        self._trace_store = trace_store

    def set_system(self, system: Any) -> None:
        """Deferred system injection — called after JarvisSystem is constructed."""
        self._system = system

    def run_ephemeral(
        self,
        agent_type: str,
        system_prompt: str,
        input_text: str,
        tools: list[str] | None = None,
    ) -> Any:
        """Run a one-shot agent turn with no lifecycle tracking."""
        from openjarvis.core.registry import AgentRegistry

        agent_cls = AgentRegistry.get(agent_type)
        agent = agent_cls(
            engine=getattr(self._manager, '_engine', None),
            system_prompt=system_prompt,
            bus=self._bus,
        )
        return agent.run(input_text)

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

        # Activity tracking: subscribe to tool/inference events
        def _on_activity(event: Any) -> None:
            if event.data.get("agent") == agent_id:
                self._manager.update_agent(agent_id, last_activity_at=time.time())

        self._bus.subscribe(EventType.TOOL_CALL_START, _on_activity)
        self._bus.subscribe(EventType.INFERENCE_START, _on_activity)

        # Trace recording: collect tool call steps
        trace_steps: list[dict[str, Any]] = []

        def _on_tool_start(event: Any) -> None:
            if event.data.get("agent") == agent_id:
                trace_steps.append({
                    "type": "tool_call",
                    "input": {
                        "tool": event.data.get("tool"),
                        "args": event.data.get("args"),
                    },
                    "start_time": event.timestamp,
                })

        def _on_tool_end(event: Any) -> None:
            if event.data.get("agent") == agent_id and trace_steps:
                for step in reversed(trace_steps):
                    if step["type"] == "tool_call" and "output" not in step:
                        step["output"] = {
                            "result": str(event.data.get("result", ""))[:4096],
                        }
                        step["duration"] = event.data.get("duration", 0)
                        break

        if self._trace_store:
            self._bus.subscribe(EventType.TOOL_CALL_START, _on_tool_start)
            self._bus.subscribe(EventType.TOOL_CALL_END, _on_tool_end)

        tick_start = time.time()
        result = None
        error_info = None

        try:
            result = self._run_with_retries(agent)
        except AgentTickError as e:
            error_info = e
        finally:
            self._bus.unsubscribe(EventType.TOOL_CALL_START, _on_activity)
            self._bus.unsubscribe(EventType.INFERENCE_START, _on_activity)

            if self._trace_store:
                self._bus.unsubscribe(EventType.TOOL_CALL_START, _on_tool_start)
                self._bus.unsubscribe(EventType.TOOL_CALL_END, _on_tool_end)

            tick_duration = time.time() - tick_start
            self._finalize_tick(agent_id, result, error_info, tick_duration)

            if self._trace_store:
                self._save_trace(
                    agent_id, agent, result, error_info,
                    tick_start, tick_duration, trace_steps,
                )

    def _run_with_retries(self, agent: dict) -> AgentResult:
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

    def _invoke_agent(self, agent: dict) -> AgentResult:
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

        # Optionally override model via router policy
        router_policy_key = config.get("router_policy")
        if router_policy_key and self._system:
            try:
                from openjarvis.core.registry import RouterPolicyRegistry
                from openjarvis.learning.routing.types import (
                    build_routing_context,
                )

                policy = RouterPolicyRegistry.create(
                    router_policy_key,
                    available_models=[model],
                )
                instruction = config.get("instruction", "")
                ctx = build_routing_context(instruction)
                selected = policy.select_model(ctx)
                if selected:
                    model = selected
            except Exception:
                pass  # Fall back to configured model

        # Construct agent instance (BaseAgent requires engine, model as positional args)
        agent_instance = agent_cls(
            engine,
            model,
            system_prompt=config.get("system_prompt"),
            tools=[],
        )

        # Build input from instruction + summary_memory + pending messages
        instruction = config.get("instruction", "")
        memory = agent.get("summary_memory", "")
        if instruction:
            input_text = f"Standing instruction: {instruction}"
            if memory:
                input_text += f"\n\nPrevious context: {memory}"
        else:
            input_text = memory or "Continue your assigned task."
        pending = self._manager.get_pending_messages(agent["id"])
        if pending:
            user_msgs = "\n".join(f"User: {m['content']}" for m in pending)
            input_text = f"{input_text}\n\nNew instructions:\n{user_msgs}"
            for m in pending:
                self._manager.mark_message_delivered(m["id"])

        # Build AgentContext with memory results from FTS5 backend
        from openjarvis.agents._stubs import AgentContext

        agent_ctx = AgentContext()
        memory_results = []

        if (
            self._system
            and getattr(self._system, "memory_backend", None)
            and getattr(self._system, "config", None)
            and self._system.config.agent.context_from_memory
        ):
            try:
                from openjarvis.tools.storage.context import (
                    ContextConfig,
                    format_context,
                )

                sys_cfg = self._system.config
                ctx_cfg = ContextConfig(
                    top_k=sys_cfg.memory.context_top_k,
                    min_score=sys_cfg.memory.context_min_score,
                    max_context_tokens=sys_cfg.memory.context_max_tokens,
                )
                # Use pending user messages as query, fall back to instruction
                query = ""
                if pending:
                    query = " ".join(m["content"] for m in pending)
                elif instruction:
                    query = instruction

                if query:
                    results = self._system.memory_backend.retrieve(
                        query, top_k=ctx_cfg.top_k,
                    )
                    memory_results = [
                        r for r in results if r.score >= ctx_cfg.min_score
                    ]
                    if memory_results:
                        # Prepend retrieved context to input for agents
                        # that don't inspect AgentContext.memory_results
                        retrieved = format_context(memory_results)
                        input_text = (
                            f"Retrieved context from knowledge base:\n"
                            f"{retrieved}\n\n{input_text}"
                        )
            except Exception:
                pass  # Don't break agent tick if memory retrieval fails

        agent_ctx.memory_results = memory_results
        return agent_instance.run(input_text, context=agent_ctx)

    def _build_error_detail(self, error: AgentTickError) -> dict[str, Any]:
        """Build structured error detail for trace metadata."""
        import traceback

        from openjarvis.agents.errors import (
            EscalateError,
            FatalError,
            suggest_action,
        )

        if isinstance(error, EscalateError):
            error_type = "escalate"
        elif isinstance(error, FatalError):
            error_type = "fatal"
        else:
            error_type = "retryable"

        return {
            "error_type": error_type,
            "error_message": str(error)[:2000],
            "suggested_action": suggest_action(error),
            "stack_trace_summary": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)[-3:]
            )[:1000] if error.__traceback__ else "",
        }

    def _finalize_tick(
        self,
        agent_id: str,
        result: AgentResult | None,
        error: AgentTickError | None,
        duration: float,
    ) -> None:
        """Update agent state after tick completion or failure."""
        if error is None:
            # Success
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, total_runs_increment=1)

            # Accumulate budget metrics from AgentResult metadata
            if result:
                tokens = result.metadata.get("tokens_used", 0)
                cost = result.metadata.get("cost", 0.0)
                budget_kwargs: dict[str, Any] = {"stall_retries": 0}
                if tokens > 0:
                    budget_kwargs["total_tokens_increment"] = tokens
                if cost > 0:
                    budget_kwargs["total_cost_increment"] = cost
                self._manager.update_agent(agent_id, **budget_kwargs)

                self._manager.update_summary_memory(
                    agent_id, result.content[:2000],
                )
                self._manager.store_agent_response(agent_id, result.content[:2000])

            # Budget enforcement (post-tick check)
            agent_data = self._manager.get_agent(agent_id)
            if agent_data:
                config = agent_data.get("config", {})
                max_cost = config.get("max_cost", 0)
                max_tokens = config.get("max_tokens", 0)
                exceeded = False
                if max_cost > 0 and agent_data["total_cost"] > max_cost:
                    exceeded = True
                if max_tokens > 0 and agent_data["total_tokens"] > max_tokens:
                    exceeded = True
                if exceeded:
                    self._manager.update_agent(agent_id, status="budget_exceeded")
                    self._bus.publish(EventType.AGENT_BUDGET_EXCEEDED, {
                        "agent_id": agent_id,
                        "total_cost": agent_data["total_cost"],
                        "total_tokens": agent_data["total_tokens"],
                        "max_cost": max_cost,
                        "max_tokens": max_tokens,
                    })
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
            # Write error detail to summary_memory so frontend can display it
            error_msg = str(error)[:2000]
            self._manager.update_summary_memory(agent_id, f"ERROR: {error_msg}")
            self._bus.publish(EventType.AGENT_TICK_ERROR, {
                "agent_id": agent_id,
                "error": str(error),
                "error_type": (
                    "fatal" if isinstance(error, FatalError) else "retryable_exhausted"
                ),
                "duration": duration,
            })

    def _save_trace(
        self,
        agent_id: str,
        agent: dict,
        result: AgentResult | None,
        error: AgentTickError | None,
        tick_start: float,
        tick_duration: float,
        trace_steps: list[dict[str, Any]],
    ) -> None:
        """Persist an execution trace to the trace store."""
        from openjarvis.core.types import StepType, Trace, TraceStep

        steps = []
        for s in trace_steps:
            steps.append(TraceStep(
                step_type=(
                    StepType.TOOL_CALL
                    if s["type"] == "tool_call"
                    else StepType.GENERATE
                ),
                input=s.get("input", {}),
                output=s.get("output", {}),
                duration_seconds=s.get("duration", 0),
                timestamp=s.get("start_time", tick_start),
            ))

        metadata: dict[str, Any] = {}
        if error is not None:
            metadata["error_detail"] = self._build_error_detail(error)

        outcome = "success" if error is None else "error"
        trace = Trace(
            agent=agent_id,
            query=agent.get("summary_memory", "")[:200],
            result=result.content[:200] if result else "",
            model=agent.get("config", {}).get("model", ""),
            outcome=outcome,
            steps=steps,
            started_at=tick_start,
            ended_at=tick_start + tick_duration,
            total_latency_seconds=tick_duration,
            metadata=metadata,
        )
        try:
            self._trace_store.save(trace)
        except Exception:
            logger.warning(
                "Failed to save trace for agent %s", agent_id, exc_info=True,
            )
