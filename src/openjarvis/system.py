"""Composition layer -- config-driven construction of a fully wired JarvisSystem."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.events import EventBus, get_event_bus
from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, ToolExecutor

logger = logging.getLogger(__name__)


@dataclass
class JarvisSystem:
    """Fully wired system -- the single source of truth for primitive composition."""

    config: JarvisConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent: Optional[Any] = None  # BaseAgent
    agent_name: str = ""
    tools: List[BaseTool] = field(default_factory=list)
    tool_executor: Optional[ToolExecutor] = None
    memory_backend: Optional[Any] = None  # MemoryBackend
    channel_backend: Optional[Any] = None  # BaseChannel
    router: Optional[Any] = None  # RouterPolicy
    mcp_server: Optional[Any] = None  # MCPServer
    telemetry_store: Optional[Any] = None
    trace_store: Optional[Any] = None
    trace_collector: Optional[Any] = None
    gpu_monitor: Optional[Any] = None
    scheduler_store: Optional[Any] = None  # SchedulerStore
    scheduler: Optional[Any] = None  # TaskScheduler
    container_runner: Optional[Any] = None  # ContainerRunner
    workflow_engine: Optional[Any] = None  # WorkflowEngine
    session_store: Optional[Any] = None  # SessionStore
    capability_policy: Optional[Any] = None  # CapabilityPolicy
    audit_logger: Optional[Any] = None  # AuditLogger
    boundary_guard: Optional[Any] = None  # BoundaryGuard
    operator_manager: Optional[Any] = None  # OperatorManager
    agent_manager: Optional[Any] = None  # AgentManager
    agent_scheduler: Optional[Any] = None  # AgentScheduler
    agent_executor: Optional[Any] = None  # AgentExecutor
    speech_backend: Optional[Any] = None  # SpeechBackend
    _learning_orchestrator: Optional[Any] = None  # LearningOrchestrator
    _mcp_clients: List = field(default_factory=list)

    def ask(
        self,
        query: str,
        *,
        context: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        agent: Optional[str] = None,
        tools: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
        operator_id: Optional[str] = None,
        prior_messages: Optional[List[Message]] = None,
    ) -> Dict[str, Any]:
        """Execute a query through the system and return a result dict."""
        if temperature is None:
            temperature = self.config.intelligence.temperature
        if max_tokens is None:
            max_tokens = self.config.intelligence.max_tokens

        messages = [Message(role=Role.USER, content=query)]

        # Context injection from memory
        if context and self.memory_backend and self.config.agent.context_from_memory:
            try:
                from openjarvis.tools.storage.context import (
                    ContextConfig,
                    inject_context,
                )

                ctx_cfg = ContextConfig(
                    top_k=self.config.memory.context_top_k,
                    min_score=self.config.memory.context_min_score,
                    max_context_tokens=self.config.memory.context_max_tokens,
                )
                messages = inject_context(
                    query,
                    messages,
                    self.memory_backend,
                    config=ctx_cfg,
                )
            except Exception as exc:
                logger.warning("Failed to inject memory context: %s", exc)

        # Agent mode
        use_agent = agent or self.agent_name
        if use_agent and use_agent != "none":
            return self._run_agent(
                query,
                messages,
                use_agent,
                tools,
                temperature,
                max_tokens,
                system_prompt=system_prompt,
                operator_id=operator_id,
                prior_messages=prior_messages,
            )

        # Direct engine mode
        result = self.engine.generate(
            messages,
            model=self.model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return {
            "content": result.get("content", ""),
            "usage": result.get("usage", {}),
            "model": self.model,
            "engine": self.engine_key,
        }

    def _run_agent(
        self,
        query,
        messages,
        agent_name,
        tool_names,
        temperature,
        max_tokens,
        *,
        system_prompt=None,
        operator_id=None,
        prior_messages=None,
    ) -> Dict[str, Any]:
        """Run through an agent."""
        from openjarvis.agents._stubs import AgentContext
        from openjarvis.core.events import EventType
        from openjarvis.core.registry import AgentRegistry

        # Resolve agent
        try:
            agent_cls = AgentRegistry.get(agent_name)
        except KeyError:
            return {"content": f"Unknown agent: {agent_name}", "error": True}

        # Build tools for agent
        agent_tools = self.tools
        if tool_names:
            agent_tools = self._build_tools(tool_names)

        # Build context
        ctx = AgentContext()

        # Seed prior conversation turns (channel session history)
        if prior_messages:
            for msg in prior_messages:
                ctx.conversation.add(msg)

        # Inject memory context messages into the agent conversation
        if messages and len(messages) > 1:
            # Context messages were prepended by inject_context
            for msg in messages[:-1]:
                ctx.conversation.add(msg)

        # Instantiate agent with the same pattern as CLI
        agent_kwargs: Dict[str, Any] = {
            "bus": self.bus,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if getattr(agent_cls, "accepts_tools", False):
            agent_kwargs["tools"] = agent_tools
            agent_kwargs["max_turns"] = self.config.agent.max_turns
        if system_prompt is not None:
            agent_kwargs["system_prompt"] = system_prompt
        if self.capability_policy is not None:
            agent_kwargs["capability_policy"] = self.capability_policy
        if operator_id is not None:
            agent_kwargs["operator_id"] = operator_id
            agent_kwargs["session_store"] = self.session_store
            agent_kwargs["memory_backend"] = self.memory_backend

        try:
            ag = agent_cls(self.engine, self.model, **agent_kwargs)
        except TypeError:
            try:
                ag = agent_cls(self.engine, self.model)
            except TypeError:
                ag = agent_cls()

        # Collect telemetry from all engine calls during agent run
        telemetry_events: List[Dict[str, Any]] = []

        def _on_inference_end(event: Any) -> None:
            telemetry_events.append(event.data if hasattr(event, "data") else event)

        self.bus.subscribe(EventType.INFERENCE_END, _on_inference_end)

        # Run — wrap with TraceCollector when tracing is enabled.
        # Check trace_store (set at build time) instead of config.traces.enabled
        # because the shared config singleton can be mutated by other SystemBuilder
        # instances (e.g. the judge backend).
        try:
            if self.trace_store is not None:
                from openjarvis.traces.collector import TraceCollector

                collector = TraceCollector(
                    ag, store=self.trace_store, bus=self.bus,
                )
                result = collector.run(query, context=ctx)
                self.trace_collector = collector
            else:
                result = ag.run(query, context=ctx)
        finally:
            self.bus.unsubscribe(EventType.INFERENCE_END, _on_inference_end)

        # Aggregate telemetry across all engine calls
        _telemetry: Dict[str, Any] = {}
        if telemetry_events:
            total_energy = sum(e.get("energy_joules", 0.0) for e in telemetry_events)
            total_latency = sum(e.get("latency", 0.0) for e in telemetry_events)
            power_vals = [
                e.get("power_watts", 0.0)
                for e in telemetry_events
                if e.get("power_watts", 0.0) > 0
            ]
            util_vals = [
                e.get("gpu_utilization_pct", 0.0)
                for e in telemetry_events
                if e.get("gpu_utilization_pct", 0.0) > 0
            ]
            throughput_vals = [
                e.get("throughput_tok_per_sec", 0.0)
                for e in telemetry_events
                if e.get("throughput_tok_per_sec", 0.0) > 0
            ]
            _telemetry = {
                "ttft": telemetry_events[0].get("ttft", 0.0),
                "energy_joules": total_energy,
                "power_watts": (
                    sum(power_vals) / len(power_vals) if power_vals else 0.0
                ),
                "gpu_utilization_pct": (
                    sum(util_vals) / len(util_vals) if util_vals else 0.0
                ),
                "throughput_tok_per_sec": (
                    sum(throughput_vals) / len(throughput_vals)
                    if throughput_vals
                    else 0.0
                ),
                "gpu_memory_used_gb": max(
                    (e.get("gpu_memory_used_gb", 0.0) for e in telemetry_events),
                    default=0.0,
                ),
                "gpu_temperature_c": max(
                    (e.get("gpu_temperature_c", 0.0) for e in telemetry_events),
                    default=0.0,
                ),
                "inference_calls": len(telemetry_events),
                "total_inference_latency": total_latency,
            }

        return {
            "content": result.content,
            "usage": getattr(result, "usage", {}),
            "tool_results": [
                {
                    "tool_name": tr.tool_name,
                    "content": tr.content,
                    "success": tr.success,
                    "arguments": tr.metadata.get("arguments", {}),
                }
                for tr in getattr(result, "tool_results", [])
            ],
            "turns": getattr(result, "turns", 1),
            "model": self.model,
            "engine": self.engine_key,
            "_telemetry": _telemetry,
        }

    def _build_tools(self, tool_names: List[str]) -> List[BaseTool]:
        """Build tool instances from tool names."""
        from openjarvis.core.registry import ToolRegistry

        tools: List[BaseTool] = []
        for name in tool_names:
            try:
                if name == "retrieval" and self.memory_backend:
                    from openjarvis.tools.retrieval import RetrievalTool

                    tools.append(RetrievalTool(self.memory_backend))
                elif name == "llm":
                    from openjarvis.tools.llm_tool import LLMTool

                    tools.append(LLMTool(self.engine, model=self.model))
                elif ToolRegistry.contains(name):
                    tools.append(ToolRegistry.create(name))
            except Exception as exc:
                logger.warning("Failed to build tool %r: %s", name, exc)
        return tools

    def wire_channel(self, channel_bridge: Any) -> None:
        """Register a message handler on *channel_bridge* that routes every
        incoming message through this system (agent or engine) and replies.

        Sessions are isolated per ``"<channel>:<conversation_id>"`` key so
        each chat retains its own history.

        Parameters
        ----------
        channel_bridge:
            A connected :class:`~openjarvis.channels._stubs.BaseChannel`
            instance whose ``on_message`` method accepts a callable.
        """
        from openjarvis.core.types import Message, Role
        from openjarvis.sessions.session import SessionStore

        if self.session_store is None:
            from pathlib import Path

            self.session_store = SessionStore(
                db_path=Path(self.config.sessions.db_path).expanduser(),
                max_age_hours=self.config.sessions.max_age_hours,
                consolidation_threshold=self.config.sessions.consolidation_threshold,
            )

        _system = self  # capture for closure

        def _on_channel_message(cm) -> None:
            session_key = f"{cm.channel}:{cm.conversation_id}"
            session = _system.session_store.get_or_create(
                session_key,
                channel=cm.channel,
                channel_user_id=cm.sender,
            )

            prior_msgs: List[Message] = []
            for sm in session.messages:
                try:
                    role = Role(sm.role)
                except ValueError:
                    role = Role.USER
                prior_msgs.append(Message(role=role, content=sm.content))

            reply = ""
            try:
                if _system.agent_name and _system.agent_name != "none":
                    result = _system.ask(
                        cm.content,
                        context=False,
                        agent=_system.agent_name,
                        prior_messages=prior_msgs,
                    )
                    reply = result.get("content", "")
                else:
                    result = _system.ask(
                        cm.content,
                        context=False,
                        prior_messages=prior_msgs,
                    )
                    reply = result.get("content", "")
            except Exception:
                logger.exception("Channel message handler error")
                reply = "Sorry, I encountered an error processing your message."

            try:
                _system.session_store.save_message(
                    session.session_id,
                    "user",
                    cm.content,
                    channel=cm.channel,
                )
                _system.session_store.save_message(
                    session.session_id,
                    "assistant",
                    reply,
                    channel=cm.channel,
                )
            except Exception:
                logger.debug("Session save error", exc_info=True)

            if reply:
                try:
                    channel_bridge.send(
                        cm.channel,
                        reply,
                        conversation_id=cm.conversation_id,
                    )
                except Exception:
                    logger.exception("Channel send error")

        channel_bridge.on_message(_on_channel_message)

    def _close_mcp_clients(self) -> None:
        """Close all persistent MCP client connections."""
        for client in self._mcp_clients:
            try:
                client.close()
            except Exception:
                logger.debug("Error closing MCP client", exc_info=True)

    def close(self) -> None:
        """Release resources."""
        if self.scheduler and hasattr(self.scheduler, "stop"):
            self.scheduler.stop()
        for resource in (
            self.scheduler_store,
            self.engine,
            self.gpu_monitor,
            self.telemetry_store,
            self.trace_store,
            self.memory_backend,
            self.session_store,
            self.channel_backend,
            self.workflow_engine,
            self.container_runner,
        ):
            if resource and hasattr(resource, "close"):
                resource.close()
        if self.agent_manager is not None:
            self.agent_manager.close()
        if self.agent_scheduler is not None:
            self.agent_scheduler.stop()
        self._close_mcp_clients()

    def __enter__(self) -> JarvisSystem:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class SystemBuilder:
    """Config-driven fluent builder for JarvisSystem."""

    def __init__(
        self,
        config: Optional[JarvisConfig] = None,
        *,
        config_path: Optional[Any] = None,
    ) -> None:
        if config is not None:
            self._config = config
        elif config_path is not None:
            from pathlib import Path

            self._config = load_config(Path(config_path))
        else:
            self._config = load_config()

        self._engine_key: Optional[str] = None
        self._model: Optional[str] = None
        self._agent_name: Optional[str] = None
        self._tool_names: Optional[List[str]] = None
        self._telemetry: Optional[bool] = None
        self._traces: Optional[bool] = None
        self._bus: Optional[EventBus] = None
        self._sandbox: Optional[bool] = None
        self._scheduler: Optional[bool] = None
        self._workflow: Optional[bool] = None
        self._sessions: Optional[bool] = None
        self._speech: Optional[bool] = None
        self._mcp_clients: List = []

    def engine(self, key: str) -> SystemBuilder:
        self._engine_key = key
        return self

    def model(self, name: str) -> SystemBuilder:
        self._model = name
        return self

    def agent(self, name: str) -> SystemBuilder:
        self._agent_name = name
        return self

    def tools(self, names: List[str]) -> SystemBuilder:
        self._tool_names = names
        return self

    def telemetry(self, enabled: bool) -> SystemBuilder:
        self._telemetry = enabled
        return self

    def traces(self, enabled: bool) -> SystemBuilder:
        self._traces = enabled
        return self

    def sandbox(self, enabled: bool) -> SystemBuilder:
        self._sandbox = enabled
        return self

    def scheduler(self, enabled: bool) -> SystemBuilder:
        self._scheduler = enabled
        return self

    def workflow(self, enabled: bool) -> SystemBuilder:
        self._workflow = enabled
        return self

    def sessions(self, enabled: bool) -> SystemBuilder:
        self._sessions = enabled
        return self

    def speech(self, enabled: bool) -> SystemBuilder:
        self._speech = enabled
        return self

    def event_bus(self, bus: EventBus) -> SystemBuilder:
        self._bus = bus
        return self

    def build(self) -> JarvisSystem:
        """Construct a fully wired JarvisSystem."""
        config = self._config
        bus = self._bus or get_event_bus()

        # Resolve engine
        engine, engine_key = self._resolve_engine(config)

        # Resolve model
        model = self._resolve_model(config, engine)

        # Compute telemetry_enabled and traces_enabled once
        telemetry_enabled = (
            self._telemetry if self._telemetry is not None else config.telemetry.enabled
        )
        traces_enabled = (
            self._traces if self._traces is not None else config.traces.enabled
        )
        # Apply traces flag to config so downstream code respects it
        config.traces.enabled = traces_enabled
        gpu_monitor = None
        energy_monitor = None
        if telemetry_enabled and config.telemetry.gpu_metrics:
            # Try new multi-vendor EnergyMonitor first
            try:
                from openjarvis.telemetry.energy_monitor import (
                    create_energy_monitor,
                )

                energy_monitor = create_energy_monitor(
                    poll_interval_ms=config.telemetry.gpu_poll_interval_ms,
                    prefer_vendor=config.telemetry.energy_vendor or None,
                )
            except ImportError:
                pass

            # Fall back to legacy GpuMonitor
            if energy_monitor is None:
                try:
                    from openjarvis.telemetry.gpu_monitor import GpuMonitor

                    if GpuMonitor.available():
                        gpu_monitor = GpuMonitor(
                            poll_interval_ms=config.telemetry.gpu_poll_interval_ms,
                        )
                except ImportError:
                    pass

        # Apply security guardrails FIRST (innermost wrapper)
        from openjarvis.security import setup_security

        sec = setup_security(config, engine, bus)
        engine = sec.engine

        # Then wrap with InstrumentedEngine (outermost wrapper)
        if telemetry_enabled:
            from openjarvis.telemetry.instrumented_engine import (
                InstrumentedEngine,
            )

            engine = InstrumentedEngine(
                engine,
                bus,
                gpu_monitor=gpu_monitor,
                energy_monitor=energy_monitor,
            )

        # Set up telemetry store
        telemetry_store = None
        if telemetry_enabled:
            telemetry_store = self._setup_telemetry(config, bus)

        # Resolve memory backend
        memory_backend = self._resolve_memory(config)

        # Resolve channel backend
        channel_backend = self._resolve_channel(config, bus)

        # Resolve tools
        tool_list = self._resolve_tools(
            config,
            engine,
            model,
            memory_backend,
            channel_backend,
        )

        # Build tool executor
        tool_executor = ToolExecutor(tool_list, bus) if tool_list else None

        # Resolve agent name
        agent_name = self._agent_name or config.agent.default_agent

        # Set up container sandbox runner
        container_runner = self._setup_sandbox(config)

        # Set up scheduler
        scheduler_store, task_scheduler = self._setup_scheduler(config, bus)

        # Set up workflow engine
        workflow_engine = self._setup_workflow(config, bus)

        # Set up session store
        session_store = self._setup_sessions(config)

        # Set up trace store
        trace_store = None
        if traces_enabled:
            try:
                from openjarvis.traces.store import TraceStore

                trace_store = TraceStore(config.traces.db_path)
            except Exception:
                logger.warning("Failed to initialize TraceStore", exc_info=True)

        # Set up capability policy
        capability_policy = sec.capability_policy

        # Set up learning orchestrator (when training is enabled)
        learning_orchestrator = self._setup_learning_orchestrator(config)

        # Agent Manager
        agent_manager = None
        if config.agent_manager.enabled:
            try:
                from pathlib import Path

                from openjarvis.agents.manager import AgentManager

                am_db = config.agent_manager.db_path or str(
                    Path("~/.openjarvis/agents.db").expanduser()
                )
                agent_manager = AgentManager(db_path=am_db)
            except Exception as exc:
                logger.warning("Failed to initialize agent manager: %s", exc)

        # Executor + Scheduler (depend on agent_manager)
        agent_executor = None
        agent_scheduler = None
        if agent_manager is not None:
            try:
                from openjarvis.agents.executor import AgentExecutor
                from openjarvis.agents.scheduler import AgentScheduler

                # Wire TraceStore into executor when tracing is enabled
                _trace_store = None
                if config.traces.enabled:
                    try:
                        from openjarvis.traces.store import TraceStore

                        _trace_store = TraceStore(config.traces.db_path)
                    except Exception:
                        logger.warning(
                            "Failed to initialize TraceStore",
                            exc_info=True,
                        )

                agent_executor = AgentExecutor(
                    manager=agent_manager,
                    event_bus=bus,
                    trace_store=_trace_store,
                )
                agent_scheduler = AgentScheduler(
                    manager=agent_manager,
                    executor=agent_executor,
                )
            except Exception:
                logger.warning("Failed to initialize agent scheduler", exc_info=True)

        # Set up speech backend
        speech_backend = None
        speech_enabled = self._speech if self._speech is not None else True
        if speech_enabled:
            try:
                from openjarvis.speech._discovery import get_speech_backend

                speech_backend = get_speech_backend(config)
            except Exception as exc:
                logger.warning("Failed to initialize speech backend: %s", exc)

        system = JarvisSystem(
            config=config,
            bus=bus,
            engine=engine,
            engine_key=engine_key,
            model=model,
            agent_name=agent_name,
            tools=tool_list,
            tool_executor=tool_executor,
            memory_backend=memory_backend,
            channel_backend=channel_backend,
            telemetry_store=telemetry_store,
            trace_store=trace_store,
            gpu_monitor=gpu_monitor,
            scheduler_store=scheduler_store,
            scheduler=task_scheduler,
            container_runner=container_runner,
            workflow_engine=workflow_engine,
            session_store=session_store,
            capability_policy=capability_policy,
            audit_logger=sec.audit_logger,
            agent_manager=agent_manager,
            agent_scheduler=agent_scheduler,
            agent_executor=agent_executor,
            speech_backend=speech_backend,
        )
        system._learning_orchestrator = learning_orchestrator
        # Transfer MCP clients so JarvisSystem.close() can shut them down
        system._mcp_clients = list(getattr(self, "_mcp_clients", []))
        # Wire system reference — must happen before scheduler.start()
        if system.agent_executor is not None:
            system.agent_executor.set_system(system)
        return system

    def _resolve_engine(self, config: JarvisConfig):
        """Resolve the inference engine."""
        from openjarvis.engine._discovery import get_engine

        pref = config.intelligence.preferred_engine
        key = self._engine_key or pref or config.engine.default
        resolved = get_engine(config, key)
        if resolved is None:
            raise RuntimeError(
                "No inference engine available. "
                "Make sure an engine is running (e.g. ollama serve)."
            )
        return resolved[1], resolved[0]

    def _resolve_model(self, config: JarvisConfig, engine: InferenceEngine) -> str:
        """Resolve which model to use."""
        if self._model:
            return self._model
        if config.intelligence.default_model:
            return config.intelligence.default_model

        # Try to discover from engine
        try:
            models = engine.list_models()
            if models:
                return models[0]
        except Exception as exc:
            logger.warning("Failed to list models from engine: %s", exc)

        return config.intelligence.fallback_model or ""

    def _setup_telemetry(self, config, bus):
        """Set up telemetry store."""
        try:
            from openjarvis.telemetry.store import TelemetryStore

            store = TelemetryStore(db_path=config.telemetry.db_path)
            store.subscribe_to_bus(bus)
            return store
        except Exception as exc:
            logger.warning("Failed to set up telemetry store: %s", exc)
            return None

    def _resolve_memory(self, config):
        """Resolve memory backend."""
        try:
            import openjarvis.tools.storage  # noqa: F401 -- trigger registration
            from openjarvis.core.registry import MemoryRegistry

            key = config.memory.default_backend
            if MemoryRegistry.contains(key):
                return MemoryRegistry.create(key, db_path=config.memory.db_path)
        except Exception as exc:
            logger.warning("Failed to resolve memory backend: %s", exc)
        return None

    def _resolve_channel(self, config, bus):
        """Resolve channel backend from config."""
        if not config.channel.enabled:
            return None
        try:
            import openjarvis.channels  # noqa: F401 -- trigger registration
            from openjarvis.core.registry import ChannelRegistry

            key = config.channel.default_channel
            if not key:
                return None
            if not ChannelRegistry.contains(key):
                return None

            kwargs: Dict[str, Any] = {"bus": bus}
            if key == "telegram":
                tc = config.channel.telegram
                if tc.bot_token:
                    kwargs["bot_token"] = tc.bot_token
                if tc.parse_mode:
                    kwargs["parse_mode"] = tc.parse_mode
            elif key == "discord":
                dc = config.channel.discord
                if dc.bot_token:
                    kwargs["bot_token"] = dc.bot_token
            elif key == "slack":
                sc = config.channel.slack
                if sc.bot_token:
                    kwargs["bot_token"] = sc.bot_token
                if sc.app_token:
                    kwargs["app_token"] = sc.app_token
            elif key == "webhook":
                wc = config.channel.webhook
                if wc.url:
                    kwargs["url"] = wc.url
                if wc.secret:
                    kwargs["secret"] = wc.secret
                if wc.method:
                    kwargs["method"] = wc.method
            elif key == "email":
                ec = config.channel.email
                if ec.smtp_host:
                    kwargs["smtp_host"] = ec.smtp_host
                kwargs["smtp_port"] = ec.smtp_port
                if ec.imap_host:
                    kwargs["imap_host"] = ec.imap_host
                kwargs["imap_port"] = ec.imap_port
                if ec.username:
                    kwargs["username"] = ec.username
                if ec.password:
                    kwargs["password"] = ec.password
                kwargs["use_tls"] = ec.use_tls
            elif key == "whatsapp":
                wac = config.channel.whatsapp
                if wac.access_token:
                    kwargs["access_token"] = wac.access_token
                if wac.phone_number_id:
                    kwargs["phone_number_id"] = wac.phone_number_id
            elif key == "signal":
                sgc = config.channel.signal
                if sgc.api_url:
                    kwargs["api_url"] = sgc.api_url
                if sgc.phone_number:
                    kwargs["phone_number"] = sgc.phone_number
            elif key == "google_chat":
                gcc = config.channel.google_chat
                if gcc.webhook_url:
                    kwargs["webhook_url"] = gcc.webhook_url
            elif key == "irc":
                ic = config.channel.irc
                if ic.server:
                    kwargs["server"] = ic.server
                kwargs["port"] = ic.port
                if ic.nick:
                    kwargs["nick"] = ic.nick
                if ic.password:
                    kwargs["password"] = ic.password
                kwargs["use_tls"] = ic.use_tls
            elif key == "webchat":
                pass  # no config needed
            elif key == "teams":
                tmc = config.channel.teams
                if tmc.app_id:
                    kwargs["app_id"] = tmc.app_id
                if tmc.app_password:
                    kwargs["app_password"] = tmc.app_password
                if tmc.service_url:
                    kwargs["service_url"] = tmc.service_url
            elif key == "matrix":
                mc = config.channel.matrix
                if mc.homeserver:
                    kwargs["homeserver"] = mc.homeserver
                if mc.access_token:
                    kwargs["access_token"] = mc.access_token
            elif key == "mattermost":
                mmc = config.channel.mattermost
                if mmc.url:
                    kwargs["url"] = mmc.url
                if mmc.token:
                    kwargs["token"] = mmc.token
            elif key == "feishu":
                fc = config.channel.feishu
                if fc.app_id:
                    kwargs["app_id"] = fc.app_id
                if fc.app_secret:
                    kwargs["app_secret"] = fc.app_secret
            elif key == "bluebubbles":
                bbc = config.channel.bluebubbles
                if bbc.url:
                    kwargs["url"] = bbc.url
                if bbc.password:
                    kwargs["password"] = bbc.password
            elif key == "whatsapp_baileys":
                wbc = config.channel.whatsapp_baileys
                if wbc.auth_dir:
                    kwargs["auth_dir"] = wbc.auth_dir
                if wbc.assistant_name:
                    kwargs["assistant_name"] = wbc.assistant_name
                kwargs["assistant_has_own_number"] = wbc.assistant_has_own_number
            elif key == "sendblue":
                sbc = getattr(config.channel, "sendblue", None)
                if sbc:
                    if getattr(sbc, "api_key_id", ""):
                        kwargs["api_key_id"] = sbc.api_key_id
                    if getattr(sbc, "api_secret_key", ""):
                        kwargs["api_secret_key"] = sbc.api_secret_key
                    if getattr(sbc, "from_number", ""):
                        kwargs["from_number"] = sbc.from_number

            return ChannelRegistry.create(key, **kwargs)
        except Exception as exc:
            logger.warning("Failed to resolve channel backend %r: %s", key, exc)
            return None

    def _resolve_tools(
        self, config, engine, model, memory_backend, channel_backend=None
    ):
        """Resolve tool instances via MCPServer (primary) + external MCP servers."""
        from openjarvis.mcp.server import MCPServer

        # 1. Build internal MCPServer with all auto-discovered tools
        internal_server = MCPServer()

        # 2. Inject runtime dependencies into tools that need them
        for tool in internal_server.get_tools():
            self._inject_tool_deps(tool, engine, model, memory_backend, channel_backend)

        # 3. Determine which tool names to include
        tool_names = self._tool_names
        if tool_names is None:
            raw = config.tools.enabled or config.agent.tools
            if raw:
                if isinstance(raw, list):
                    tool_names = [
                        n.strip() for n in raw if isinstance(n, str) and n.strip()
                    ]
                else:
                    tool_names = [n.strip() for n in raw.split(",") if n.strip()]
            else:
                tool_names = []

        # 4. Filter to requested tool names (if specified)
        if tool_names:
            all_tools = {t.spec.name: t for t in internal_server.get_tools()}
            tools = [all_tools[n] for n in tool_names if n in all_tools]
        else:
            tools = []

        # 5. Discover external MCP server tools
        if config.tools.mcp.servers:
            try:
                import json

                server_list = json.loads(config.tools.mcp.servers)
                if isinstance(server_list, list):
                    for server_cfg in server_list:
                        try:
                            external_tools = self._discover_external_mcp(server_cfg)
                            if tool_names:
                                external_tools = [
                                    t
                                    for t in external_tools
                                    if t.spec.name in tool_names
                                ]
                            tools.extend(external_tools)
                        except Exception as exc:
                            logger.warning(
                                "Failed to discover external MCP tools: %s",
                                exc,
                            )
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Failed to parse MCP server config: %s", exc)

        return tools

    @staticmethod
    def _inject_tool_deps(tool, engine, model, memory_backend, channel_backend):
        """Inject runtime dependencies into tools that need them."""
        name = tool.spec.name
        if name == "llm":
            if hasattr(tool, "_engine"):
                tool._engine = engine
            if hasattr(tool, "_model"):
                tool._model = model
        elif name == "retrieval":
            if hasattr(tool, "_backend"):
                tool._backend = memory_backend
        elif name.startswith("memory_"):
            if hasattr(tool, "_backend"):
                tool._backend = memory_backend
        elif name.startswith("channel_"):
            if hasattr(tool, "_channel"):
                tool._channel = channel_backend
        elif name in (
            "schedule_task",
            "list_scheduled_tasks",
            "pause_scheduled_task",
            "resume_scheduled_task",
            "cancel_scheduled_task",
        ):
            pass  # scheduler injection handled post-build

    def _setup_sandbox(self, config):
        """Set up container sandbox runner if enabled."""
        sandbox_enabled = (
            self._sandbox if self._sandbox is not None else config.sandbox.enabled
        )
        if not sandbox_enabled:
            return None
        try:
            from openjarvis.sandbox.runner import ContainerRunner

            return ContainerRunner(
                image=config.sandbox.image,
                timeout=config.sandbox.timeout,
                mount_allowlist_path=config.sandbox.mount_allowlist_path,
                max_concurrent=config.sandbox.max_concurrent,
                runtime=config.sandbox.runtime,
            )
        except Exception as exc:
            logger.warning("Failed to set up container sandbox: %s", exc)
            return None

    def _setup_scheduler(self, config, bus):
        """Set up task scheduler if enabled."""
        scheduler_enabled = (
            self._scheduler if self._scheduler is not None else config.scheduler.enabled
        )
        if not scheduler_enabled:
            return None, None
        try:
            from openjarvis.scheduler.store import SchedulerStore

            db_path = config.scheduler.db_path or str(
                config.hardware.platform  # unused, just for fallback
            )
            if not config.scheduler.db_path:
                from openjarvis.core.config import DEFAULT_CONFIG_DIR

                db_path = str(DEFAULT_CONFIG_DIR / "scheduler.db")

            store = SchedulerStore(db_path=db_path)

            from openjarvis.scheduler.scheduler import TaskScheduler

            sched = TaskScheduler(
                store,
                poll_interval=config.scheduler.poll_interval,
                bus=bus,
            )
            return store, sched
        except Exception as exc:
            logger.warning("Failed to set up task scheduler: %s", exc)
            return None, None

    def _setup_workflow(self, config, bus):
        """Set up workflow engine if enabled."""
        workflow_enabled = (
            self._workflow if self._workflow is not None else config.workflow.enabled
        )
        if not workflow_enabled:
            return None
        try:
            from openjarvis.workflow.engine import WorkflowEngine

            return WorkflowEngine(
                bus=bus,
                max_parallel=config.workflow.max_parallel,
                default_node_timeout=config.workflow.default_node_timeout,
            )
        except Exception as exc:
            logger.warning("Failed to set up workflow engine: %s", exc)
            return None

    def _setup_sessions(self, config):
        """Set up session store if enabled."""
        sessions_enabled = (
            self._sessions if self._sessions is not None else config.sessions.enabled
        )
        if not sessions_enabled:
            return None
        try:
            from openjarvis.sessions.session import SessionStore

            return SessionStore(
                db_path=config.sessions.db_path,
                max_age_hours=config.sessions.max_age_hours,
                consolidation_threshold=config.sessions.consolidation_threshold,
            )
        except Exception as exc:
            logger.warning("Failed to set up session store: %s", exc)
            return None

    @staticmethod
    def _setup_learning_orchestrator(config: JarvisConfig):
        """Set up LearningOrchestrator when training is enabled."""
        if not config.learning.training_enabled:
            return None
        try:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR
            from openjarvis.learning.learning_orchestrator import (
                LearningOrchestrator,
            )
            from openjarvis.learning.training.lora import LoRATrainingConfig
            from openjarvis.traces.store import TraceStore

            trace_store = TraceStore(db_path=config.traces.db_path)
            config_dir = DEFAULT_CONFIG_DIR / "agent_configs"

            sft_cfg = config.learning.intelligence.sft
            lora_config = LoRATrainingConfig(
                lora_rank=sft_cfg.lora_rank,
                lora_alpha=sft_cfg.lora_alpha,
            )

            return LearningOrchestrator(
                trace_store=trace_store,
                config_dir=config_dir,
                min_improvement=config.learning.min_improvement,
                min_sft_pairs=sft_cfg.min_pairs,
                lora_config=lora_config,
            )
        except Exception as exc:
            logger.warning("Failed to set up learning orchestrator: %s", exc)
            return None

    def _discover_external_mcp(self, server_cfg) -> List[BaseTool]:
        """Discover tools from an external MCP server configuration.

        Supports both stdio (command + args) and Streamable HTTP (url)
        transports. Persists MCP clients on ``self._mcp_clients`` so
        that transports stay alive for runtime tool calls.
        """
        import json

        from openjarvis.mcp.client import MCPClient
        from openjarvis.mcp.transport import StdioTransport, StreamableHTTPTransport
        from openjarvis.tools.mcp_adapter import MCPToolProvider

        cfg = json.loads(server_cfg) if isinstance(server_cfg, str) else server_cfg
        name = cfg.get("name", "<unnamed>")
        url = cfg.get("url")
        command = cfg.get("command", "")
        args = cfg.get("args", [])

        # Build transport based on config keys
        if url:
            transport = StreamableHTTPTransport(url=url)
        elif command:
            transport = StdioTransport(command=[command] + args)
        else:
            logger.warning(
                "MCP server '%s' has neither 'url' nor 'command' — skipping",
                name,
            )
            return []

        client = MCPClient(transport)
        client.initialize()

        # Persist client so the transport stays alive for tool calls
        self._mcp_clients.append(client)

        provider = MCPToolProvider(client)
        discovered = provider.discover()

        # Per-server tool filtering
        include_tools = set(cfg.get("include_tools", []))
        exclude_tools = set(cfg.get("exclude_tools", []))
        if include_tools:
            discovered = [t for t in discovered if t.spec.name in include_tools]
        if exclude_tools:
            discovered = [t for t in discovered if t.spec.name not in exclude_tools]

        logger.info(
            "Discovered %d tools from MCP server '%s'",
            len(discovered),
            name,
        )
        return discovered


__all__ = ["JarvisSystem", "SystemBuilder"]
