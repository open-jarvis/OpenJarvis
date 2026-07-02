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

# Default model for monitor_operative / long-horizon agent ticks. qwen3:8b
# emits tool_calls but, when given the full MonitorOperative system prompt
# alongside a `think` no-op tool, reliably picks `think` instead of the real
# action tools — producing tickless prose from training-data memory.
# gemma4:31b follows the function-calling protocol with the same prompt and
# actually invokes web_search / memory_retrieve. Explicit ``config["model"]``
# on an agent still wins.
_AGENT_TICK_DEFAULT_MODEL = "gemma4:31b"


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

    def _set_activity(self, agent_id: str, activity: str) -> None:
        """Update the agent's current_activity for progress visibility."""
        try:
            self._manager.update_agent(agent_id, current_activity=activity)
        except Exception:
            pass  # Non-critical

    def _inject_tool_deps(self, tool: Any) -> None:
        """Inject runtime dependencies into a tool instance.

        Mirrors SystemBuilder._inject_tool_deps (system.py:920-945)
        but uses the lightweight system's references.
        """
        if self._system is None:
            return
        name = getattr(getattr(tool, "spec", None), "name", "")
        if name == "llm":
            if hasattr(tool, "_engine"):
                tool._engine = self._system.engine
            if hasattr(tool, "_model"):
                tool._model = self._system.model
        elif name == "retrieval" or name.startswith("memory_"):
            if hasattr(tool, "_backend"):
                tool._backend = getattr(self._system, "memory_backend", None)
        elif name.startswith("channel_"):
            if hasattr(tool, "_channel"):
                tool._channel = getattr(self._system, "channel_backend", None)

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
            engine=getattr(self._manager, "_engine", None),
            system_prompt=system_prompt,
            bus=self._bus,
        )
        return agent.run(input_text)

    def execute_tick(self, agent_id: str, *, lock_already_held: bool = False) -> None:
        """Run one tick for the given agent.

        1. Acquire concurrency guard (start_tick)
        2. Invoke agent with retry logic
        3. Update stats
        4. Release guard (end_tick)

        ``lock_already_held`` is set by callers that took the start_tick()
        lock themselves before spawning the worker (e.g. the HTTP /run route
        guards against concurrent POSTs by acquiring before threading).
        Without this flag, the executor would re-acquire and trip its own
        guard — bailing out with no end_tick(), leaving the agent stuck in
        ``status='running'`` forever.
        """
        if lock_already_held:
            self._set_activity(agent_id, "Preparing tick...")
        else:
            try:
                self._manager.start_tick(agent_id)
                self._set_activity(agent_id, "Preparing tick...")
            except ValueError:
                logger.warning("Agent %s already running, skipping tick", agent_id)
                return

        agent = self._manager.get_agent(agent_id)
        if agent is None:
            logger.error("Agent %s not found", agent_id)
            return

        self._bus.publish(
            EventType.AGENT_TICK_START,
            {
                "agent_id": agent_id,
                "agent_name": agent["name"],
            },
        )

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
                trace_steps.append(
                    {
                        "type": "tool_call",
                        "input": {
                            "tool": event.data.get("tool"),
                            "args": event.data.get("args"),
                        },
                        "start_time": event.timestamp,
                    }
                )

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
                    agent_id,
                    agent,
                    result,
                    error_info,
                    tick_start,
                    tick_duration,
                    trace_steps,
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
                    agent["id"],
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    e,
                )
                time.sleep(delay)
            except Exception as e:
                classified = classify_error(e)
                if not classified.retryable or attempt == _MAX_RETRIES - 1:
                    raise classified from e
                delay = retry_delay(attempt)
                logger.info(
                    "Agent %s tick retry %d/%d in %ds: %s",
                    agent["id"],
                    attempt + 1,
                    _MAX_RETRIES,
                    delay,
                    e,
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
        model = (
            config.get("model")
            or _AGENT_TICK_DEFAULT_MODEL
            or (self._system.model if self._system else "")
        )
        if not model:
            raise FatalError("No model configured for agent")

        logger.info(
            "Agent %s [%s]: using model=%s, engine=%s",
            agent["name"],
            agent["id"],
            model,
            type(engine).__name__,
        )
        self._set_activity(agent["id"], f"Loading model {model}...")

        # Optionally override model via router policy
        router_policy_key = config.get("router_policy")
        if router_policy_key and self._system:
            try:
                from openjarvis.core.registry import RouterPolicyRegistry
                from openjarvis.learning.routing.router import (
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

        # Resolve tools from config via ToolRegistry
        tool_names = config.get("tools", [])
        if isinstance(tool_names, str):
            tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]

        tool_instances: list[Any] = []
        if tool_names:
            try:
                from openjarvis.server.agent_manager_routes import (
                    _ensure_registries_populated,
                )

                _ensure_registries_populated()
            except ImportError:
                pass
            from openjarvis.core.registry import ToolRegistry

            for tname in tool_names:
                if ToolRegistry.contains(tname):
                    try:
                        tool_cls = ToolRegistry.get(tname)
                        tool = tool_cls()
                        self._inject_tool_deps(tool)
                        tool_instances.append(tool)
                    except Exception:
                        logger.warning("Failed to instantiate tool %s", tname)

            # Pull tools already discovered by SystemBuilder (e.g. external MCP
            # adapters) that aren't in the static ToolRegistry. Without this,
            # agents declaring MCP-discovered tools in their template would
            # silently fall back to natives only.
            if (
                self._system is not None
                and getattr(self._system, "tool_executor", None) is not None
            ):
                mcp_pool = getattr(self._system.tool_executor, "_tools", {}) or {}
                existing = {t.spec.name for t in tool_instances}
                for tname in tool_names:
                    if tname in existing:
                        continue
                    pooled = mcp_pool.get(tname)
                    if pooled is not None:
                        tool_instances.append(pooled)

            if tool_instances:
                logger.info(
                    "Agent %s: resolved %d/%d tools",
                    agent["name"],
                    len(tool_instances),
                    len(tool_names),
                )

        # Construct agent instance
        agent_kwargs: dict[str, Any] = {}
        sys_prompt = config.get("system_prompt")
        if sys_prompt is not None:
            agent_kwargs["system_prompt"] = sys_prompt
        if getattr(agent_cls, "accepts_tools", False) and tool_instances:
            agent_kwargs["tools"] = tool_instances
        # Hand the agent our EventBus so its ToolExecutor can publish
        # TOOL_CALL_START/END — without this, ToolExecutor's ``self._bus``
        # is None and every tool call executes silently, which is why
        # traces previously reported "0 steps" even when the model was
        # actively invoking web_search/memory_*/etc.
        if self._bus is not None:
            agent_kwargs["bus"] = self._bus
        # Propagate confirmation policy from the AgentExecutor down to the
        # agent's own ToolExecutor. Set by CLI paths like `jarvis agents ask`
        # so non-interactive runs can auto-approve tool execution.
        if getattr(self, "_confirm_callback", None) is not None:
            agent_kwargs["interactive"] = True
            agent_kwargs["confirm_callback"] = self._confirm_callback

        # Wire cross-tick state plumbing into agent classes that accept it.
        # Without this, MonitorOperative/Operative agents have no working
        # session_store or memory_backend and silently no-op their state
        # recall / persistence paths.
        import inspect

        init_sig = inspect.signature(agent_cls.__init__)
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in init_sig.parameters.values()
        )

        def _accepts(name: str) -> bool:
            return accepts_var_kw or name in init_sig.parameters

        state_kwargs: dict[str, Any] = {}
        if _accepts("operator_id"):
            state_kwargs["operator_id"] = agent["id"]
        if self._system is not None:
            if _accepts("session_store"):
                state_kwargs["session_store"] = getattr(
                    self._system, "session_store", None
                )
            if _accepts("memory_backend"):
                state_kwargs["memory_backend"] = getattr(
                    self._system, "memory_backend", None
                )
            # Wire SOUL.md / MEMORY.md / USER.md persona files into persistent
            # agents, mirroring the one-shot `jarvis ask` path so they no
            # longer apply to CLI calls only (#376).
            cfg = getattr(self._system, "config", None)
            if cfg is not None and _accepts("prompt_builder"):
                from openjarvis.prompt.builder import SystemPromptBuilder

                state_kwargs["prompt_builder"] = SystemPromptBuilder(
                    agent_template=getattr(cfg.agent, "default_system_prompt", "")
                    or "",
                    memory_files_config=cfg.memory_files,
                    system_prompt_config=cfg.system_prompt,
                )

        try:
            agent_instance = agent_cls(engine, model, **agent_kwargs, **state_kwargs)
        except TypeError:
            try:
                agent_instance = agent_cls(engine, model, **agent_kwargs)
            except TypeError:
                agent_instance = agent_cls(engine, model)

        # Inject the managed-agent UUID into the agent's ToolExecutor so
        # emitted TOOL_CALL_START/END events carry it; the trace subscriber
        # below filters by ``event.data["agent"] == agent_id`` and would
        # otherwise drop every tool call (the class-level agent_id like
        # "monitor_operative" doesn't match the runtime UUID).
        inner_executor = getattr(agent_instance, "_executor", None)
        if inner_executor is not None and hasattr(inner_executor, "_agent_id"):
            inner_executor._agent_id = agent["id"]

        logger.info(
            "Agent %s: tool wiring — %d tools resolved (%s), agent class %s",
            agent["name"],
            len(tool_instances),
            ", ".join(t.spec.name for t in tool_instances) or "none",
            agent_cls.__name__,
        )

        # Build input from instruction + summary_memory + pending messages.
        # NB: we deliberately do NOT inject the full previous response back
        # in as "Previous context" — that caused the model to parrot its
        # own prior output verbatim. Cross-tick continuity now lives in the
        # agent's session_store / memory_backend; here we only surface a
        # short tick-boundary marker so the model knows time has passed.
        import datetime
        import re

        today = datetime.date.today().strftime("%A, %B %d, %Y")
        instruction = config.get("instruction", "")
        memory = (agent.get("summary_memory") or "").strip()
        last_run_at = agent.get("last_run_at")

        tick_note = ""
        if memory:
            first_sentence = re.split(r"(?<=[.!?])\s+", memory, maxsplit=1)[0]
            first_sentence = first_sentence.strip()[:200]
            if last_run_at:
                ts = datetime.datetime.fromtimestamp(last_run_at).strftime(
                    "%Y-%m-%d %H:%M"
                )
                tick_note = f"Last tick at {ts}: {first_sentence}"
            else:
                tick_note = f"Previous tick: {first_sentence}"

        if instruction:
            input_text = f"Current date: {today}\n\nStanding instruction: {instruction}"
            if tick_note:
                input_text += f"\n\n{tick_note}"
        else:
            base = tick_note or "Continue your assigned task."
            input_text = f"Current date: {today}\n\n{base}"
        pending = self._manager.get_pending_messages(agent["id"])
        if pending:
            user_msgs = "\n".join(f"User: {m['content']}" for m in pending)
            input_text = f"{input_text}\n\nNew instructions:\n{user_msgs}"
            for m in pending:
                self._manager.mark_message_delivered(m["id"])
            logger.info(
                "Agent %s: delivering %d pending message(s)",
                agent["name"],
                len(pending),
            )
            self._set_activity(
                agent["id"],
                f"Delivering {len(pending)} message(s)...",
            )
        else:
            logger.info(
                "Agent %s: no pending messages, running with instruction only",
                agent["name"],
            )

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
                        query,
                        top_k=ctx_cfg.top_k,
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
        self._set_activity(agent["id"], "Generating response...")
        logger.info(
            "Agent %s: calling agent.run() with %d chars input",
            agent["name"],
            len(input_text),
        )
        _t0 = time.time()
        result = agent_instance.run(input_text, context=agent_ctx)

        # Retry once if the model returned empty content (common with
        # Qwen3.5 thinking mode consuming all tokens).
        if not (result.content or "").strip():
            self._set_activity(
                agent["id"],
                "Retrying (empty response)...",
            )
            logger.warning(
                "Agent %s: empty content, retrying once",
                agent["name"],
            )
            result = agent_instance.run(input_text, context=agent_ctx)

        _elapsed = time.time() - _t0
        logger.info(
            "Agent %s: agent.run() completed in %.1fs, "
            "content_len=%d, turns=%d, tokens=%s",
            agent["name"],
            _elapsed,
            len(result.content or ""),
            result.turns,
            result.metadata.get("total_tokens", "?"),
        )
        return result

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
            )[:1000]
            if error.__traceback__
            else "",
        }

    def _finalize_tick(
        self,
        agent_id: str,
        result: AgentResult | None,
        error: AgentTickError | None,
        duration: float,
    ) -> None:
        """Update agent state after tick completion or failure."""
        self._set_activity(agent_id, "Finalizing...")
        if error is None:
            # Success
            logger.info(
                "Tick succeeded for agent %s in %.1fs, response_len=%d",
                agent_id,
                duration,
                len(result.content or "") if result else 0,
            )
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, total_runs_increment=1)

            # Accumulate budget metrics from AgentResult metadata
            if result:
                tokens = (
                    result.metadata.get("total_tokens")
                    or result.metadata.get("tokens_used")
                    or 0
                )
                in_tokens = result.metadata.get("prompt_tokens", 0)
                out_tokens = result.metadata.get(
                    "completion_tokens",
                    0,
                )
                cost = result.metadata.get("cost", 0.0)
                budget_kwargs: dict[str, Any] = {"stall_retries": 0}
                if tokens > 0:
                    budget_kwargs["total_tokens_increment"] = tokens
                if in_tokens > 0:
                    budget_kwargs["input_tokens_increment"] = in_tokens
                if out_tokens > 0:
                    budget_kwargs["output_tokens_increment"] = out_tokens
                if cost > 0:
                    budget_kwargs["total_cost_increment"] = cost
                self._manager.update_agent(agent_id, **budget_kwargs)

                # Store the full response. update_summary_memory enforces the
                # rolling-summary cap (_SUMMARY_MAX) itself, and the chat
                # message keeps the complete report. The old [:2000] slices
                # double-truncated and cut findings off mid-sentence.
                self._manager.update_summary_memory(agent_id, result.content)
                self._manager.store_agent_response(agent_id, result.content)

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
                    self._bus.publish(
                        EventType.AGENT_BUDGET_EXCEEDED,
                        {
                            "agent_id": agent_id,
                            "total_cost": agent_data["total_cost"],
                            "total_tokens": agent_data["total_tokens"],
                            "max_cost": max_cost,
                            "max_tokens": max_tokens,
                        },
                    )
            self._bus.publish(
                EventType.AGENT_TICK_END,
                {
                    "agent_id": agent_id,
                    "duration": duration,
                    "status": "ok",
                },
            )
        elif isinstance(error, EscalateError):
            logger.warning(
                "Tick escalated for agent %s after %.1fs: %s",
                agent_id,
                duration,
                error,
            )
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, status="needs_attention")
            self._bus.publish(
                EventType.AGENT_TICK_ERROR,
                {
                    "agent_id": agent_id,
                    "error": str(error),
                    "error_type": "escalate",
                    "duration": duration,
                },
            )
        else:
            logger.error(
                "Tick failed for agent %s after %.1fs: %s",
                agent_id,
                duration,
                error,
                exc_info=error,
            )
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, status="error")
            # Write error detail to summary_memory so frontend can display it
            error_msg = str(error)[:2000]
            self._manager.update_summary_memory(agent_id, f"ERROR: {error_msg}")
            self._bus.publish(
                EventType.AGENT_TICK_ERROR,
                {
                    "agent_id": agent_id,
                    "error": str(error),
                    "error_type": (
                        "fatal"
                        if isinstance(error, FatalError)
                        else "retryable_exhausted"
                    ),
                    "duration": duration,
                },
            )

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
            steps.append(
                TraceStep(
                    step_type=(
                        StepType.TOOL_CALL
                        if s["type"] == "tool_call"
                        else StepType.GENERATE
                    ),
                    input=s.get("input", {}),
                    output=s.get("output", {}),
                    duration_seconds=s.get("duration", 0),
                    timestamp=s.get("start_time", tick_start),
                )
            )

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
                "Failed to save trace for agent %s",
                agent_id,
                exc_info=True,
            )
