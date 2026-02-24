"""Composition layer -- config-driven construction of a fully wired JarvisSystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.events import EventBus, get_event_bus
from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine
from openjarvis.tools._stubs import BaseTool, ToolExecutor


@dataclass
class JarvisSystem:
    """Fully wired system -- the single source of truth for pillar composition."""

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

    def ask(
        self,
        query: str,
        *,
        context: bool = True,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        agent: Optional[str] = None,
        tools: Optional[List[str]] = None,
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
                    query, messages, self.memory_backend, config=ctx_cfg,
                )
            except Exception:
                pass

        # Agent mode
        use_agent = agent or self.agent_name
        if use_agent and use_agent != "none":
            return self._run_agent(
                query, messages, use_agent, tools, temperature, max_tokens,
            )

        # Direct engine mode
        result = self.engine.generate(
            messages, model=self.model,
            temperature=temperature, max_tokens=max_tokens,
        )
        return {
            "content": result.get("content", ""),
            "usage": result.get("usage", {}),
            "model": self.model,
            "engine": self.engine_key,
        }

    def _run_agent(
        self, query, messages, agent_name, tool_names, temperature, max_tokens,
    ) -> Dict[str, Any]:
        """Run through an agent."""
        from openjarvis.agents._stubs import AgentContext
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

        try:
            ag = agent_cls(self.engine, self.model, **agent_kwargs)
        except TypeError:
            try:
                ag = agent_cls(self.engine, self.model)
            except TypeError:
                ag = agent_cls()

        # Run
        result = ag.run(query, context=ctx)
        return {
            "content": result.content,
            "usage": getattr(result, "usage", {}),
            "tool_results": [
                {
                    "tool_name": tr.tool_name,
                    "content": tr.content,
                    "success": tr.success,
                }
                for tr in getattr(result, "tool_results", [])
            ],
            "turns": getattr(result, "turns", 1),
            "model": self.model,
            "engine": self.engine_key,
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
            except Exception:
                pass
        return tools

    def close(self) -> None:
        """Release resources."""
        if self.telemetry_store and hasattr(self.telemetry_store, "close"):
            self.telemetry_store.close()
        if self.trace_store and hasattr(self.trace_store, "close"):
            self.trace_store.close()


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

        # Wrap with InstrumentedEngine if telemetry enabled
        telemetry_enabled = (
            self._telemetry if self._telemetry is not None
            else config.telemetry.enabled
        )
        if telemetry_enabled:
            from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
            engine = InstrumentedEngine(engine, bus)

        # Apply security guardrails to engine
        engine = self._apply_security(config, engine, bus)

        # Set up telemetry
        telemetry_store = None
        telemetry_enabled = (
            self._telemetry if self._telemetry is not None else config.telemetry.enabled
        )
        if telemetry_enabled:
            telemetry_store = self._setup_telemetry(config, bus)

        # Resolve memory backend
        memory_backend = self._resolve_memory(config)

        # Resolve channel backend
        channel_backend = self._resolve_channel(config, bus)

        # Resolve tools
        tool_list = self._resolve_tools(
            config, engine, model, memory_backend, channel_backend,
        )

        # Build tool executor
        tool_executor = ToolExecutor(tool_list, bus) if tool_list else None

        # Resolve agent name
        agent_name = self._agent_name or config.agent.default_agent

        return JarvisSystem(
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
        )

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
        except Exception:
            pass

        return config.intelligence.fallback_model or ""

    def _apply_security(self, config, engine, bus):
        """Wrap engine with security guardrails if enabled."""
        if config.security.enabled:
            try:
                from openjarvis.security.guardrails import GuardrailsEngine
                from openjarvis.security.scanner import PIIScanner, SecretScanner
                from openjarvis.security.types import RedactionMode

                scanners = []
                if config.security.secret_scanner:
                    scanners.append(SecretScanner())
                if config.security.pii_scanner:
                    scanners.append(PIIScanner())

                if scanners:
                    mode_map = {
                        "warn": RedactionMode.WARN,
                        "redact": RedactionMode.REDACT,
                        "block": RedactionMode.BLOCK,
                    }
                    mode = mode_map.get(config.security.mode, RedactionMode.WARN)
                    engine = GuardrailsEngine(
                        engine, scanners, mode=mode, bus=bus,
                        scan_input=config.security.scan_input,
                        scan_output=config.security.scan_output,
                    )
            except Exception:
                pass
        return engine

    def _setup_telemetry(self, config, bus):
        """Set up telemetry store."""
        try:
            from openjarvis.telemetry.store import TelemetryStore

            store = TelemetryStore(db_path=config.telemetry.db_path)
            store.subscribe_to_bus(bus)
            return store
        except Exception:
            return None

    def _resolve_memory(self, config):
        """Resolve memory backend."""
        try:
            import openjarvis.memory  # noqa: F401 -- trigger registration
            from openjarvis.core.registry import MemoryRegistry

            key = config.memory.default_backend
            if MemoryRegistry.contains(key):
                return MemoryRegistry.create(key, db_path=config.memory.db_path)
        except Exception:
            pass
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

            return ChannelRegistry.create(key, **kwargs)
        except Exception:
            return None

    def _resolve_tools(self, config, engine, model, memory_backend,
                       channel_backend=None):
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
                                    t for t in external_tools
                                    if t.spec.name in tool_names
                                ]
                            tools.extend(external_tools)
                        except Exception:
                            pass
            except (json.JSONDecodeError, TypeError):
                pass

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

    @staticmethod
    def _discover_external_mcp(server_cfg) -> List[BaseTool]:
        """Discover tools from an external MCP server configuration."""
        import json

        from openjarvis.mcp.client import MCPClient
        from openjarvis.mcp.transport import StdioTransport
        from openjarvis.tools.mcp_adapter import MCPToolProvider

        cfg = json.loads(server_cfg) if isinstance(server_cfg, str) else server_cfg
        command = cfg.get("command", "")
        args = cfg.get("args", [])
        if not command:
            return []
        transport = StdioTransport(command=command, args=args)
        client = MCPClient(transport)
        provider = MCPToolProvider(client)
        return provider.discover()


__all__ = ["JarvisSystem", "SystemBuilder"]
