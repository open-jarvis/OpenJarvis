"""High-level Python SDK for OpenJarvis."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import openjarvis
from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.events import EventBus
from openjarvis.core.types import Message, Role
from openjarvis.engine._discovery import get_engine
from openjarvis.system import JarvisSystem, SystemBuilder
from openjarvis.telemetry.store import TelemetryStore
from openjarvis.telemetry.wrapper import instrumented_generate


class MemoryHandle:
    """Proxy for memory operations. Lazily initializes backend."""

    def __init__(self, config: JarvisConfig) -> None:
        self._config = config
        self._backend: Any = None

    def _get_backend(self) -> Any:
        if self._backend is not None:
            return self._backend

        import openjarvis.memory  # noqa: F401
        from openjarvis.core.registry import MemoryRegistry

        key = self._config.memory.default_backend
        if not MemoryRegistry.contains(key):
            # Register built-in backends
            try:
                from openjarvis.memory.sqlite import SqliteMemory  # noqa: F401
            except ImportError:
                pass

        if not MemoryRegistry.contains(key):
            raise RuntimeError(f"Memory backend '{key}' not available")

        if key == "sqlite":
            self._backend = MemoryRegistry.create(
                key, db_path=self._config.memory.db_path,
            )
        else:
            self._backend = MemoryRegistry.create(key)
        return self._backend

    def index(
        self,
        path: str,
        *,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ) -> Dict[str, Any]:
        """Index a file or directory into memory."""
        from openjarvis.memory.chunking import ChunkConfig
        from openjarvis.memory.ingest import ingest_path

        backend = self._get_backend()
        cfg = ChunkConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks = ingest_path(Path(path), config=cfg)

        doc_ids: List[str] = []
        for chunk in chunks:
            doc_id = backend.store(
                chunk.content, source=chunk.source,
                metadata={"index": chunk.index},
            )
            doc_ids.append(doc_id)

        return {
            "chunks": len(chunks),
            "doc_ids": doc_ids,
            "path": path,
        }

    def search(self, query: str, *, top_k: int = 5) -> List[Dict[str, Any]]:
        """Search memory for relevant chunks."""
        backend = self._get_backend()
        results = backend.retrieve(query, top_k=top_k)
        return [
            {
                "content": r.content,
                "score": r.score,
                "source": r.source,
                "metadata": r.metadata,
            }
            for r in results
        ]

    def stats(self) -> Dict[str, Any]:
        """Return memory backend statistics."""
        backend = self._get_backend()
        if hasattr(backend, "count"):
            return {
                "count": backend.count(),
                "backend": self._config.memory.default_backend,
            }
        return {"backend": self._config.memory.default_backend}

    def close(self) -> None:
        """Release the memory backend."""
        if self._backend is not None:
            if hasattr(self._backend, "close"):
                self._backend.close()
            self._backend = None


class Jarvis:
    """High-level OpenJarvis SDK.

    Usage::

        from openjarvis import Jarvis

        j = Jarvis()
        response = j.ask("Hello, what can you do?")
        print(response)
        j.close()
    """

    def __init__(
        self,
        *,
        config: Optional[JarvisConfig] = None,
        config_path: Optional[str] = None,
        engine_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        if config is not None:
            self._config = config
        elif config_path is not None:
            self._config = load_config(Path(config_path))
        else:
            self._config = load_config()

        self._engine_key = engine_key
        self._model_override = model
        self._engine: Any = None
        self._resolved_engine_key: Optional[str] = None
        self._bus = EventBus()
        self._telem_store: Optional[TelemetryStore] = None
        self._audit_logger: Any = None
        self.memory = MemoryHandle(self._config)

        # Set up telemetry
        if self._config.telemetry.enabled:
            try:
                self._telem_store = TelemetryStore(self._config.telemetry.db_path)
                self._telem_store.subscribe_to_bus(self._bus)
            except Exception:
                pass

        # Set up security audit logger
        if self._config.security.enabled:
            try:
                from openjarvis.security.audit import AuditLogger

                self._audit_logger = AuditLogger(
                    db_path=self._config.security.audit_log_path,
                    bus=self._bus,
                )
            except Exception:
                pass

    @property
    def config(self) -> JarvisConfig:
        """Return the active configuration."""
        return self._config

    @property
    def version(self) -> str:
        """Return the OpenJarvis version string."""
        return openjarvis.__version__

    def _ensure_engine(self) -> None:
        """Lazily initialize the inference engine."""
        if self._engine is not None:
            return

        # Import engines to trigger registration
        try:
            import openjarvis.engine  # noqa: F401
        except ImportError:
            pass

        pref = self._config.intelligence.preferred_engine
        engine_key = self._engine_key or pref or None
        resolved = get_engine(self._config, engine_key)
        if resolved is None:
            raise RuntimeError(
                "No inference engine available. "
                "Make sure an engine is running (e.g. ollama serve)."
            )
        self._resolved_engine_key, engine = resolved

        # Wrap engine with security guardrails if configured
        if self._config.security.enabled:
            try:
                from openjarvis.security.guardrails import GuardrailsEngine
                from openjarvis.security.scanner import PIIScanner, SecretScanner
                from openjarvis.security.types import RedactionMode

                scanners = []
                if self._config.security.secret_scanner:
                    scanners.append(SecretScanner())
                if self._config.security.pii_scanner:
                    scanners.append(PIIScanner())
                if scanners:
                    mode = RedactionMode(self._config.security.mode)
                    engine = GuardrailsEngine(
                        engine,
                        scanners=scanners,
                        mode=mode,
                        scan_input=self._config.security.scan_input,
                        scan_output=self._config.security.scan_output,
                        bus=self._bus,
                    )
            except Exception:
                pass  # security is best-effort

        self._engine = engine

    def ask(
        self,
        query: str,
        *,
        model: Optional[str] = None,
        agent: Optional[str] = None,
        tools: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        context: bool = True,
    ) -> str:
        """Send a query and return the response text."""
        result = self.ask_full(
            query,
            model=model,
            agent=agent,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            context=context,
        )
        return result["content"]

    def ask_full(
        self,
        query: str,
        *,
        model: Optional[str] = None,
        agent: Optional[str] = None,
        tools: Optional[List[str]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        context: bool = True,
    ) -> Dict[str, Any]:
        """Send a query and return the full result dict.

        Returns a dict with keys: content, usage, tool_results (if agent mode).
        """
        self._ensure_engine()
        if temperature is None:
            temperature = self._config.intelligence.temperature
        if max_tokens is None:
            max_tokens = self._config.intelligence.max_tokens

        model_name = model or self._model_override

        # Resolve model via router if not specified
        if model_name is None:
            model_name = self._resolve_model(query)

        if not model_name:
            models = self._engine.list_models()
            model_name = models[0] if models else "default"

        # Agent mode
        if agent is not None:
            return self._run_agent(
                agent, query, model_name,
                tools=tools or [],
                temperature=temperature,
                max_tokens=max_tokens,
                context=context,
            )

        # Direct engine mode
        messages = [Message(role=Role.USER, content=query)]

        # Memory context injection
        if context and self._config.agent.context_from_memory:
            messages = self._inject_context(query, messages)

        result = instrumented_generate(
            self._engine,
            messages,
            model=model_name,
            bus=self._bus,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return {
            "content": result.get("content", ""),
            "usage": result.get("usage", {}),
            "model": model_name,
            "engine": self._resolved_engine_key,
        }

    def _resolve_model(self, query: str) -> Optional[str]:
        """Resolve model using config fallback chain."""
        if self._config.intelligence.default_model:
            return self._config.intelligence.default_model
        # Try first available from engine
        try:
            models = self._engine.list_models()
            if models:
                return models[0]
        except Exception:
            pass
        return self._config.intelligence.fallback_model or None

    def _run_agent(
        self,
        agent_name: str,
        query: str,
        model_name: str,
        *,
        tools: List[str],
        temperature: float,
        max_tokens: int,
        context: bool,
    ) -> Dict[str, Any]:
        """Run an agent and return the result dict."""
        import openjarvis.agents  # noqa: F401
        from openjarvis.agents._stubs import AgentContext
        from openjarvis.core.registry import AgentRegistry

        if not AgentRegistry.contains(agent_name):
            raise ValueError(
                f"Unknown agent: {agent_name}. "
                f"Available: {', '.join(AgentRegistry.keys())}"
            )

        agent_cls = AgentRegistry.get(agent_name)

        # Build tools
        tool_objects: List[Any] = []
        if tools:
            import openjarvis.tools  # noqa: F401
            from openjarvis.cli.ask import _build_tools

            tool_objects = _build_tools(
                tools, self._config, self._engine, model_name,
            )

        agent_kwargs: Dict[str, Any] = {
            "bus": self._bus,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if getattr(agent_cls, "accepts_tools", False):
            agent_kwargs["tools"] = tool_objects
            agent_kwargs["max_turns"] = self._config.agent.max_turns

        agent_obj = agent_cls(self._engine, model_name, **agent_kwargs)
        ctx = AgentContext()

        # Context injection
        if context and self._config.agent.context_from_memory:
            try:
                from openjarvis.cli.ask import _get_memory_backend
                from openjarvis.memory.context import ContextConfig, inject_context

                backend = _get_memory_backend(self._config)
                if backend is not None:
                    ctx_cfg = ContextConfig(
                        top_k=self._config.memory.context_top_k,
                        min_score=self._config.memory.context_min_score,
                        max_context_tokens=self._config.memory.context_max_tokens,
                    )
                    context_messages = inject_context(
                        query, [], backend, config=ctx_cfg,
                    )
                    for msg in context_messages:
                        ctx.conversation.add(msg)
            except Exception:
                pass

        result = agent_obj.run(query, context=ctx)
        return {
            "content": result.content,
            "usage": {},
            "tool_results": [
                {
                    "tool_name": tr.tool_name,
                    "content": tr.content,
                    "success": tr.success,
                }
                for tr in result.tool_results
            ],
            "turns": result.turns,
            "model": model_name,
            "engine": self._resolved_engine_key,
        }

    def _inject_context(
        self, query: str, messages: List[Message],
    ) -> List[Message]:
        """Inject memory context into messages."""
        try:
            from openjarvis.cli.ask import _get_memory_backend
            from openjarvis.memory.context import ContextConfig, inject_context

            backend = _get_memory_backend(self._config)
            if backend is not None:
                ctx_cfg = ContextConfig(
                    top_k=self._config.memory.context_top_k,
                    min_score=self._config.memory.context_min_score,
                    max_context_tokens=self._config.memory.context_max_tokens,
                )
                return inject_context(query, messages, backend, config=ctx_cfg)
        except Exception:
            pass
        return messages

    def list_models(self) -> List[str]:
        """Return a list of available model identifiers."""
        self._ensure_engine()
        return self._engine.list_models()

    def list_engines(self) -> List[str]:
        """Return a list of registered engine keys."""
        from openjarvis.core.registry import EngineRegistry

        return list(EngineRegistry.keys())

    def close(self) -> None:
        """Release all resources."""
        self.memory.close()
        if self._telem_store is not None:
            try:
                self._telem_store.close()
            except Exception:
                pass
            self._telem_store = None
        if self._audit_logger is not None:
            try:
                self._audit_logger.close()
            except Exception:
                pass
            self._audit_logger = None
        self._engine = None


__all__ = ["Jarvis", "JarvisSystem", "MemoryHandle", "SystemBuilder"]
