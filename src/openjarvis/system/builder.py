"""Config-driven fluent builder that wires up a JarvisSystem."""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.events import EventBus, get_event_bus
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.system.core import JarvisSystem
from openjarvis.tools._stubs import BaseTool, ToolExecutor

logger = logging.getLogger(__name__)


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

        engine, engine_key = self._resolve_engine(config)
        model = self._resolve_model(config, engine)

        telemetry_enabled = (
            self._telemetry if self._telemetry is not None else config.telemetry.enabled
        )
        traces_enabled = (
            self._traces if self._traces is not None else config.traces.enabled
        )
        config.traces.enabled = traces_enabled
        gpu_monitor = None
        energy_monitor = None
        if telemetry_enabled and config.telemetry.gpu_metrics:
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

            if energy_monitor is None:
                try:
                    from openjarvis.telemetry.gpu_monitor import GpuMonitor

                    if GpuMonitor.available():
                        gpu_monitor = GpuMonitor(
                            poll_interval_ms=config.telemetry.gpu_poll_interval_ms,
                        )
                except ImportError:
                    pass

        from openjarvis.security import setup_security

        sec = setup_security(config, engine, bus)
        engine = sec.engine

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

        telemetry_store = None
        if telemetry_enabled:
            telemetry_store = self._setup_telemetry(config, bus)

        memory_backend = self._resolve_memory(config)
        channel_backend = self._resolve_channel(config, bus)
        tool_list = self._resolve_tools(
            config,
            engine,
            model,
            memory_backend,
            channel_backend,
        )
        tool_executor = ToolExecutor(tool_list, bus) if tool_list else None

        skill_manager = None
        skill_few_shot_examples: List[str] = []
        if config.skills.enabled:
            try:
                from pathlib import Path

                from openjarvis.skills.manager import SkillManager

                skill_manager = SkillManager(
                    bus, capability_policy=sec.capability_policy
                )
                skill_paths = [Path(config.skills.skills_dir).expanduser()]
                workspace_skills = Path("./skills")
                if workspace_skills.exists():
                    skill_paths.insert(0, workspace_skills)
                skill_manager.discover(paths=skill_paths)
                if tool_executor:
                    skill_manager.set_tool_executor(tool_executor)
                skill_tools = skill_manager.get_skill_tools(
                    tool_executor=tool_executor,
                )
                tool_list.extend(skill_tools)
                if tool_list:
                    tool_executor = ToolExecutor(tool_list, bus)
                skill_few_shot_examples = skill_manager.get_few_shot_examples()
            except Exception as exc:
                logger.warning("Failed to initialize skills: %s", exc)

        agent_name = self._agent_name or config.agent.default_agent
        container_runner = self._setup_sandbox(config)
        scheduler_store, task_scheduler = self._setup_scheduler(config, bus)
        workflow_engine = self._setup_workflow(config, bus)
        session_store = self._setup_sessions(config)

        trace_store = None
        if traces_enabled:
            try:
                from openjarvis.traces.store import TraceStore

                trace_store = TraceStore(config.traces.db_path)
            except Exception:
                logger.warning("Failed to initialize TraceStore", exc_info=True)

        capability_policy = sec.capability_policy
        learning_orchestrator = self._setup_learning_orchestrator(config)

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

        agent_executor = None
        agent_scheduler = None
        if agent_manager is not None:
            try:
                from openjarvis.agents.executor import AgentExecutor
                from openjarvis.agents.scheduler import AgentScheduler

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
            skill_manager=skill_manager,
        )
        system._learning_orchestrator = learning_orchestrator
        system._skill_few_shot_examples = skill_few_shot_examples
        system._mcp_clients = list(getattr(self, "_mcp_clients", []))
        if system.agent_executor is not None:
            system.agent_executor.set_system(system)
        return system

    def _resolve_engine(self, config: JarvisConfig):
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
        if self._model:
            return self._model
        if config.intelligence.default_model:
            return config.intelligence.default_model
        try:
            models = engine.list_models()
            if models:
                return models[0]
        except Exception as exc:
            logger.warning("Failed to list models from engine: %s", exc)
        return config.intelligence.fallback_model or ""

    def _setup_telemetry(self, config, bus):
        try:
            from openjarvis.telemetry.store import TelemetryStore

            store = TelemetryStore(db_path=config.telemetry.db_path)
            store.subscribe_to_bus(bus)
            return store
        except Exception as exc:
            logger.warning("Failed to set up telemetry store: %s", exc)
            return None

    def _resolve_memory(self, config):
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
        if not config.channel.enabled:
            return None
        key = config.channel.default_channel
        try:
            import openjarvis.channels  # noqa: F401 -- trigger registration
            from openjarvis.core.registry import ChannelRegistry
            from openjarvis.system._channel_kwargs import build_channel_kwargs

            if not key or not ChannelRegistry.contains(key):
                return None
            kwargs = {"bus": bus, **build_channel_kwargs(config.channel, key)}
            return ChannelRegistry.create(key, **kwargs)
        except Exception as exc:
            logger.warning("Failed to resolve channel backend %r: %s", key, exc)
            return None

    def _resolve_tools(
        self, config, engine, model, memory_backend, channel_backend=None
    ):
        """Resolve tool instances via MCPServer (primary) + external MCP servers."""
        from openjarvis.mcp.server import MCPServer

        internal_server = MCPServer()
        for tool in internal_server.get_tools():
            self._inject_tool_deps(tool, engine, model, memory_backend, channel_backend)

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

        if tool_names:
            all_tools = {t.spec.name: t for t in internal_server.get_tools()}
            tools = [all_tools[n] for n in tool_names if n in all_tools]
        else:
            tools = []

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

        self._mcp_clients.append(client)

        provider = MCPToolProvider(client)
        discovered = provider.discover()

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
