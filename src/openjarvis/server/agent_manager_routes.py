"""FastAPI routes for the Agent Manager."""

from __future__ import annotations

import logging
import re as _re
import threading
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents.manager import AgentManager
from openjarvis.agents.tool_resolver import (
    BROWSER_SUB_TOOLS as _BROWSER_SUB_TOOLS,
)
from openjarvis.agents.tool_resolver import (
    build_deep_research_tools,
    instantiate_registered_tool,
    resolve_agent_tools,
    resolve_tool_specs,
)
from openjarvis.agents.tool_resolver import (
    ensure_registries_populated as _ensure_registries_populated,
)
from openjarvis.server.model_capabilities import is_embed_only_model

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel
except ImportError:
    raise ImportError("fastapi and pydantic are required for server routes")

logger = logging.getLogger("openjarvis.server.agent_manager")
_MEMORY_BACKEND_LOCK_SETUP = threading.Lock()
_MCP_LOCK_SETUP = threading.Lock()


def _get_runtime_event_bus(runtime: Any = None) -> Any:
    """Return the server-owned event bus, falling back outside app runtimes."""

    from openjarvis.core.events import get_event_bus

    bus = getattr(runtime, "bus", None)
    return bus if bus is not None else get_event_bus()


def _start_managed_worker(app_state: Any, target: Any, *, name: str) -> Any:
    """Start and track a managed-agent worker for orderly app shutdown."""

    lock = getattr(app_state, "_managed_worker_lock", None)
    if lock is None:
        lock = threading.Lock()
        app_state._managed_worker_lock = lock
    workers = getattr(app_state, "_managed_workers", None)
    if workers is None:
        workers = set()
        app_state._managed_workers = workers

    thread: threading.Thread

    def _run() -> None:
        try:
            target()
        finally:
            with lock:
                workers.discard(thread)

    with lock:
        if getattr(app_state, "_managed_runtime_stopping", False):
            raise RuntimeError("managed-agent runtime is shutting down")
        thread = threading.Thread(target=_run, daemon=True, name=name)
        workers.add(thread)
        try:
            # Shutdown must never snapshot an added-but-not-started thread,
            # because joining such a thread raises instead of draining it.
            thread.start()
        except Exception:
            workers.discard(thread)
            raise
    return thread


class CreateAgentRequest(BaseModel):
    name: str
    agent_type: str = "monitor_operative"
    config: Optional[Dict[str, Any]] = None
    template_id: Optional[str] = None


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    agent_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class CreateTaskRequest(BaseModel):
    description: str


class UpdateTaskRequest(BaseModel):
    description: Optional[str] = None
    status: Optional[str] = None
    progress: Optional[Dict[str, Any]] = None
    findings: Optional[List[Any]] = None


class BindChannelRequest(BaseModel):
    channel_type: str
    config: Optional[Dict[str, Any]] = None
    routing_mode: str = "dedicated"


class SendMessageRequest(BaseModel):
    content: str
    mode: str = "queued"
    stream: bool = False  # SSE streaming mode


class FeedbackRequest(BaseModel):
    score: float
    reason: Optional[str] = None


def _resolve_memory_backend(config: Any) -> Any:
    """Instantiate the configured memory backend, or None if unavailable.

    Memory storage is a tool dependency, independent of whether retrieved
    context is injected into prompts.  ``context_from_memory`` controls only
    that prompt enrichment; explicitly configured ``memory_*`` tools still
    need a backend when it is false.
    """
    if config is None:
        return None
    try:
        import openjarvis.tools.storage  # noqa: F401
        from openjarvis.core.registry import MemoryRegistry

        key = config.memory.default_backend
        if MemoryRegistry.contains(key):
            return MemoryRegistry.create(key, db_path=config.memory.db_path)
    except Exception:
        logger.debug("Lightweight system: memory backend init failed", exc_info=True)
    return None


def _memory_backend_lock(app_state: Any) -> threading.Lock:
    """Return the per-runtime lock, creating it safely for lightweight tests."""

    lock = getattr(app_state, "_memory_backend_lock", None)
    if lock is not None:
        return lock
    with _MEMORY_BACKEND_LOCK_SETUP:
        lock = getattr(app_state, "_memory_backend_lock", None)
        if lock is None:
            lock = threading.Lock()
            app_state._memory_backend_lock = lock
    return lock


def _get_or_create_memory_backend(app_state: Any, config: Any = None) -> Any:
    """Return one runtime-owned memory backend, even under concurrent ticks."""

    if app_state is None:
        return None
    backend = getattr(app_state, "memory_backend", None)
    if backend is not None:
        return backend

    lock = _memory_backend_lock(app_state)
    with lock:
        backend = getattr(app_state, "memory_backend", None)
        if backend is not None:
            return backend
        if getattr(app_state, "_managed_runtime_stopping", False):
            return None
        backend = _resolve_memory_backend(
            config if config is not None else getattr(app_state, "config", None)
        )
        if backend is not None:
            app_state.memory_backend = backend
            app_state._owns_memory_backend = True
        return backend


def _mcp_state_lock(app_state: Any, attr: str) -> threading.Lock:
    """Return a named per-runtime MCP lock, creating it atomically."""

    lock = getattr(app_state, attr, None)
    if lock is not None:
        return lock
    with _MCP_LOCK_SETUP:
        lock = getattr(app_state, attr, None)
        if lock is None:
            lock = threading.Lock()
            setattr(app_state, attr, lock)
    return lock


def _register_mcp_client(app_state: Any, client: Any) -> bool:
    """Publish a client before blocking I/O so shutdown can interrupt it."""

    lock = _mcp_state_lock(app_state, "_mcp_clients_lock")
    with lock:
        if getattr(app_state, "_managed_runtime_stopping", False):
            return False
        clients = getattr(app_state, "_mcp_clients", None)
        if not isinstance(clients, list):
            clients = list(clients or [])
            app_state._mcp_clients = clients
        clients.append(client)
        return True


def _unregister_mcp_client(app_state: Any, client: Any) -> None:
    """Remove a client that failed discovery or exposed no usable tools."""

    lock = _mcp_state_lock(app_state, "_mcp_clients_lock")
    with lock:
        clients = getattr(app_state, "_mcp_clients", None)
        if isinstance(clients, list):
            try:
                clients.remove(client)
            except ValueError:
                pass


class _LightweightSystem:
    """Minimal system facade for the executor — avoids rebuilding the
    full JarvisSystem (which picks a random model from Ollama)."""

    def __init__(
        self,
        engine: Any,
        model: str,
        config: Any = None,
        runtime: Any = None,
    ):
        self.engine = engine
        self.model = model
        self.config = config
        self._runtime = runtime
        # Wire the configured memory backend so an agent's memory_store /
        # memory_retrieve tools work when the tick runs through the server.
        # The executor injects system.memory_backend into those tools; this
        # facade previously left it None, so they reported "No memory backend
        # configured" even though the backend was configured and active.
        self.memory_backend = _get_or_create_memory_backend(runtime, config)
        self.channel_backend = None
        self.mcp_tools: list[Any] = []
        self._mcp_clients: list[Any] = []
        self.knowledge_db_path = None
        if runtime is not None:
            self.channel_backend = getattr(runtime, "channel_backend", None) or getattr(
                runtime, "channel_bridge", None
            )
            self.knowledge_db_path = getattr(runtime, "knowledge_db_path", None)

    def get_managed_agent_mcp_tools(self) -> tuple[list[Any], list[Any]]:
        """Lazily discover MCP tools only after the agent allows them."""

        if self.mcp_tools:
            return self.mcp_tools, self._mcp_clients
        if self._runtime is None:
            return [], []

        runtime_tools = list(getattr(self._runtime, "mcp_tools", []) or [])
        if runtime_tools:
            self.mcp_tools = runtime_tools
        else:
            _, adapters = _get_mcp_tools(self._runtime)
            self.mcp_tools = list(adapters.values())
        self._mcp_clients = list(getattr(self._runtime, "_mcp_clients", []) or [])
        return self.mcp_tools, self._mcp_clients


def _make_lightweight_system(
    engine: Any,
    model: str,
    config: Any = None,
    runtime: Any = None,
) -> _LightweightSystem:
    """Build a minimal system with a fresh inference engine.

    The server's ``app.state.engine`` is heavily wrapped
    (MultiEngine -> InstrumentedEngine -> GuardrailsEngine) and can
    return empty content from background threads. Create a fresh
    engine directly (no health checks or model discovery that
    could interfere with in-flight requests).
    """
    try:
        from openjarvis.engine._discovery import get_engine

        cfg = config
        if cfg is None:
            from openjarvis.core.config import load_config

            cfg = load_config()

        pref = cfg.intelligence.preferred_engine
        key = pref or cfg.engine.default
        resolved = get_engine(cfg, key)

        if resolved is not None:
            plain_engine = resolved[1]
        else:
            from openjarvis.engine.ollama import OllamaEngine

            host = cfg.engine.ollama.host if cfg else ""
            plain_engine = OllamaEngine(host=host) if host else OllamaEngine()

        # Wrap with InstrumentedEngine so agent ticks are recorded
        # in telemetry (FLOPs, energy, cost savings).
        try:
            from openjarvis.telemetry.instrumented_engine import (
                InstrumentedEngine,
            )

            plain_engine = InstrumentedEngine(
                plain_engine,
                _get_runtime_event_bus(runtime),
            )
        except Exception:
            pass  # telemetry is optional
        return _LightweightSystem(plain_engine, model, cfg, runtime)
    except Exception:
        pass
    return _LightweightSystem(engine, model, config, runtime)


def _parse_param_count(model_name: str) -> float:
    """Extract parameter count in billions from model name.

    Examples: 'qwen3.5:9b' -> 9.0, 'qwen3.5:0.8b' -> 0.8
    """
    m = _re.search(r":(\d+(?:\.\d+)?)b", model_name.lower())
    return float(m.group(1)) if m else 0.0


_CLOUD_PREFIXES = ("gpt-", "claude-", "gemini-", "o1-", "o3-", "o4-")


def _pick_recommended_model(
    model_ids: list[str],
) -> dict[str, str]:
    """Pick the second-largest local *chat* model from a list.

    Embedding-only models (nomic-embed-text, etc.) are excluded — they return
    HTTP 400 "does not support chat" when used as the generation model.
    """
    local = [
        m
        for m in model_ids
        if not any(m.startswith(p) for p in _CLOUD_PREFIXES)
        and not is_embed_only_model(m)
    ]
    if not local:
        # Fall back to any non-cloud model, still skipping embedders.
        local = [m for m in model_ids if not is_embed_only_model(m)]
    if not local:
        # Never recommend an embed-only model — chat would 400.
        return {
            "model": "",
            "reason": "No local chat model available",
        }
    sized = sorted(local, key=_parse_param_count, reverse=True)
    if len(sized) == 1:
        return {"model": sized[0], "reason": "Only local chat model available"}
    pick = sized[1]  # second-largest
    params = _parse_param_count(pick)
    return {
        "model": pick,
        "reason": f"Second-largest local model ({params}B parameters)",
    }


def build_tools_list() -> List[Dict[str, Any]]:
    """Build unified tools list from ToolRegistry + ChannelRegistry."""
    import os

    from openjarvis.core.credentials import TOOL_CREDENTIALS
    from openjarvis.core.registry import ChannelRegistry, ToolRegistry

    _ensure_registries_populated()

    items: List[Dict[str, Any]] = []

    for name, tool_cls in ToolRegistry.items():
        if name in _BROWSER_SUB_TOOLS:
            continue
        # `spec` is an instance @property on BaseTool subclasses, so
        # we have to instantiate the tool to read it. The earlier
        # implementation used getattr(tool_cls, 'spec') which returns
        # the property descriptor and crashed on spec.description,
        # silently dropping every real tool from the picker.
        try:
            tool_instance = tool_cls()
            spec = tool_instance.spec
        except Exception as exc:
            logger.debug("Could not instantiate tool %s: %s", name, exc)
            spec = None
        cred_keys = TOOL_CREDENTIALS.get(name, [])
        has_fallback = bool(spec and spec.metadata.get("fallback"))
        credentials_configured = (
            spec.metadata.get("credentials_configured") if spec else None
        )
        items.append(
            {
                "name": name,
                "description": spec.description if spec else "",
                "category": spec.category if spec else "",
                "source": "tool",
                "requires_credentials": len(cred_keys) > 0 and not has_fallback,
                "credential_keys": cred_keys,
                "configured": (
                    has_fallback
                    or (
                        bool(credentials_configured)
                        if credentials_configured is not None
                        else all(bool(os.environ.get(k)) for k in cred_keys)
                    )
                    if cred_keys
                    else True
                ),
            }
        )

    try:
        if any(ToolRegistry.contains(n) for n in _BROWSER_SUB_TOOLS):
            items.append(
                {
                    "name": "browser",
                    "description": (
                        "Web browser automation"
                        " (navigate, click, type, screenshot, extract)"
                    ),
                    "category": "browser",
                    "source": "tool",
                    "requires_credentials": False,
                    "credential_keys": [],
                    "configured": True,
                }
            )
    except Exception:
        pass

    try:
        for name, _cls in ChannelRegistry.items():
            cred_keys = TOOL_CREDENTIALS.get(name, [])
            items.append(
                {
                    "name": name,
                    "description": (
                        f"{name.replace('_', ' ').title()} messaging channel"
                    ),
                    "category": "communication",
                    "source": "channel",
                    "requires_credentials": len(cred_keys) > 0,
                    "credential_keys": cred_keys,
                    "configured": (
                        all(bool(os.environ.get(k)) for k in cred_keys)
                        if cred_keys
                        else True
                    ),
                }
            )
    except Exception:
        pass

    return items


def _resolve_tool_specs(tool_config: Any) -> List[Dict[str, Any]]:
    """Compatibility wrapper for callers of the former route-local helper."""

    return resolve_tool_specs(tool_config)


# Per-agent sampler params forwarded to the engine when present in config.
# The OpenAI-compat engine passes **kwargs straight through to the upstream
# payload, so these reach local servers (vLLM / mlx_lm / etc.) that support
# them. Only forwarded when explicitly set, so default agents send nothing
# extra and engines that don't support a key never receive it. (#386)
_SAMPLER_PARAM_KEYS = (
    "top_p",
    "top_k",
    "min_p",
    "repetition_penalty",
    "frequency_penalty",
    "presence_penalty",
)


def _build_managed_system_prompt(system_prompt: str, app_config: Any) -> str:
    """Build the streaming managed-agent system prompt via SystemPromptBuilder.

    Routes the agent's own ``system_prompt`` through the same builder the
    CLI/ask path uses, so SOUL.md / MEMORY.md / USER.md persona files are
    injected for streaming chat too (#431). Returns the assembled prompt
    (caller decides whether to append a SYSTEM message); an agent with
    neither persona nor template yields an empty string, preserving the
    prior no-SYSTEM-message behavior.
    """
    from openjarvis.prompt.builder import SystemPromptBuilder

    builder = SystemPromptBuilder(
        agent_template=system_prompt or "",
        memory_files_config=getattr(app_config, "memory_files", None),
        system_prompt_config=getattr(app_config, "system_prompt", None),
    )
    return builder.build()


def _sampler_kwargs(config: Dict[str, Any]) -> Dict[str, Any]:
    """Extract per-agent sampler params from a managed agent's config (#386)."""
    out: Dict[str, Any] = {}
    for key in _SAMPLER_PARAM_KEYS:
        val = config.get(key)
        if val is not None:
            out[key] = val
    return out


def _replay_history_messages(
    history: List[Dict[str, Any]],
    exclude_id: str,
) -> List[Any]:
    """Rebuild prior-turn LLM messages from stored managed-agent history.

    When a stored assistant turn recorded ``tool_calls``, replay them as an
    assistant tool-use message followed by the corresponding tool-result
    messages — so the model sees its own prior tool pattern instead of
    regressing to fabricated tool output on later turns. Without this, only
    the assistant's text is replayed and the tool-use signal is lost (#382).
    """
    from openjarvis.core.types import Message, Role, ToolCall

    messages: List[Any] = []
    for m in reversed(history):
        if m.get("id") == exclude_id:
            continue
        direction = m.get("direction")
        if direction == "user_to_agent":
            messages.append(Message(role=Role.USER, content=m.get("content") or ""))
        elif direction == "agent_to_user":
            stored = m.get("tool_calls")
            if stored:
                calls = []
                results = []
                for i, tc in enumerate(stored):
                    call_id = f"hist-{m.get('id', '')}-{i}"
                    calls.append(
                        ToolCall(
                            id=call_id,
                            name=tc.get("tool", ""),
                            arguments=tc.get("arguments") or "",
                        )
                    )
                    results.append(
                        Message(
                            role=Role.TOOL,
                            content=str(tc.get("result", "")),
                            tool_call_id=call_id,
                            name=tc.get("tool", ""),
                        )
                    )
                messages.append(
                    Message(
                        role=Role.ASSISTANT,
                        content=m.get("content") or None,
                        tool_calls=calls,
                    )
                )
                messages.extend(results)
            else:
                messages.append(
                    Message(role=Role.ASSISTANT, content=m.get("content") or "")
                )
    return messages


def _instantiate_managed_tool(
    tool_cls: Any,
    name: str,
    *,
    engine: Any,
    model: str,
    app_state: Any,
) -> Any:
    """Compatibility adapter for tests and non-managed route callers."""

    memory_backend = _get_or_create_memory_backend(
        app_state,
        getattr(app_state, "config", None) if app_state is not None else None,
    )
    channel_backend = None
    if app_state is not None:
        channel_backend = getattr(app_state, "channel_backend", None) or getattr(
            app_state, "channel_bridge", None
        )
    return instantiate_registered_tool(
        tool_cls,
        name,
        engine=engine,
        model=model,
        memory_backend=memory_backend,
        channel_backend=channel_backend,
    )


def _build_deep_research_tools(
    engine: Any,
    model: str,
    knowledge_db_path: str = "",
) -> list[Any]:
    """Compatibility wrapper for existing channel and server integrations."""

    return build_deep_research_tools(engine, model, knowledge_db_path)


def _merge_tool_call_fragments(
    accumulated: Dict[int, Dict[str, Any]],
    fragments: List[Dict[str, Any]],
) -> None:
    """Merge incremental tool_call delta fragments into accumulated state.

    OpenAI-compatible APIs send tool_calls as incremental fragments keyed
    by ``index``. Each fragment may contain partial ``function.name`` and/or
    ``function.arguments`` strings that must be concatenated.
    """
    for frag in fragments:
        idx = frag.get("index", 0)
        if idx not in accumulated:
            accumulated[idx] = {
                "id": frag.get("id", ""),
                "type": "function",
                "function": {"name": "", "arguments": ""},
            }
        entry = accumulated[idx]
        if frag.get("id"):
            entry["id"] = frag["id"]
        fn = frag.get("function", {})
        if fn.get("name"):
            entry["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            entry["function"]["arguments"] += fn["arguments"]


def _get_mcp_tools(app_state: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return (openai_tools_list, mcp_adapters_by_name).

    Lazily discovers MCP tools from config and caches them on ``app_state``
    so that subsequent requests reuse the same connections.
    """
    lock = _mcp_state_lock(app_state, "_mcp_discovery_lock")
    with lock:
        return _get_mcp_tools_locked(app_state)


def _get_mcp_tools_locked(
    app_state: Any,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Discover MCP tools while the runtime's discovery lock is held."""

    if getattr(app_state, "_managed_runtime_stopping", False):
        return [], {}

    cached = getattr(app_state, "_mcp_tools_cache", None)
    if cached is not None:
        return cached

    preloaded = list(getattr(app_state, "mcp_tools", []) or [])
    if preloaded:
        adapters_by_name: Dict[str, Any] = {}
        for tool in preloaded:
            spec = getattr(tool, "spec", None)
            if spec is not None and spec.name not in adapters_by_name:
                adapters_by_name[spec.name] = tool
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.spec.name,
                    "description": tool.spec.description,
                    "parameters": tool.spec.parameters,
                },
            }
            for tool in adapters_by_name.values()
        ]
        app_state._mcp_tools_cache = (openai_tools, adapters_by_name)
        return app_state._mcp_tools_cache

    from openjarvis.core.config import load_config, resolve_mcp_servers

    openai_tools: List[Dict[str, Any]] = []
    adapters_by_name: Dict[str, Any] = {}

    try:
        app_config = load_config()
    except Exception as exc:
        logger.warning("Failed to load config for MCP discovery: %s", exc)
        return openai_tools, adapters_by_name

    if not app_config.tools.mcp.enabled or not app_config.tools.mcp.servers:
        return openai_tools, adapters_by_name

    from openjarvis.mcp.client import MCPClient
    from openjarvis.mcp.transport import StdioTransport, StreamableHTTPTransport
    from openjarvis.tools.mcp_adapter import MCPToolProvider

    try:
        server_list = resolve_mcp_servers(
            app_config.tools.mcp.servers,
            app_config._config_dir,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse MCP server config: %s", exc)
        return openai_tools, adapters_by_name

    for server_cfg in server_list:
        cfg = server_cfg
        name = cfg.get("name", "<unnamed>")
        url = cfg.get("url")
        # Bearer token from config — mirrors the builder.py fix for #461.
        token = cfg.get("token")
        command = cfg.get("command", "")
        args = cfg.get("args", [])

        client = None
        try:
            if url:
                transport = StreamableHTTPTransport(url=url, token=token)
            elif command:
                transport = StdioTransport(command=[command] + args)
            else:
                logger.warning(
                    "MCP server '%s' has neither 'url' nor 'command' — skipping",
                    name,
                )
                continue

            client = MCPClient(transport)
            if not _register_mcp_client(app_state, client):
                client.close()
                client = None
                break
            client.initialize()

            provider = MCPToolProvider(client)
            discovered = provider.discover()

            # Per-server tool filtering
            include_tools = set(cfg.get("include_tools", []))
            exclude_tools = set(cfg.get("exclude_tools", []))
            if include_tools:
                discovered = [t for t in discovered if t.spec.name in include_tools]
            if exclude_tools:
                discovered = [t for t in discovered if t.spec.name not in exclude_tools]

            staged: list[tuple[Any, Any]] = []
            staged_names = set(adapters_by_name)
            for adapter in discovered:
                spec = adapter.spec
                if spec.name in staged_names:
                    continue
                staged.append((adapter, spec))
                staged_names.add(spec.name)

            for adapter, spec in staged:
                openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": spec.name,
                            "description": spec.description,
                            "parameters": spec.parameters,
                        },
                    }
                )
                adapters_by_name[spec.name] = adapter

            if not staged:
                client.close()
                _unregister_mcp_client(app_state, client)
            client = None

            logger.info(
                "Discovered %d MCP tools from server '%s'",
                len(staged),
                name,
            )
        except Exception as exc:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    logger.debug("Failed to close unusable MCP client", exc_info=True)
                else:
                    _unregister_mcp_client(app_state, client)
            logger.warning(
                "Failed to discover MCP tools from '%s': %s",
                name,
                exc,
            )

    if openai_tools:
        clients_lock = _mcp_state_lock(app_state, "_mcp_clients_lock")
        with clients_lock:
            if not getattr(app_state, "_managed_runtime_stopping", False):
                app_state._mcp_tools_cache = (openai_tools, adapters_by_name)
                return openai_tools, adapters_by_name
    return [], {}


def _sse_chunk(chunk_id: str, model: str, content: str) -> str:
    """Build a single SSE content chunk."""
    import json as _json

    data = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": content},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {_json.dumps(data)}\n\n"


def _tool_progress_label(tool_name: str, args: str) -> str:
    """Human-readable label for a tool call in progress."""
    labels = {
        "knowledge_search": "Searching your knowledge base",
        "knowledge_sql": "Querying data with SQL",
        "scan_chunks": "Scanning documents for semantic matches",
        "think": "Planning next step",
    }
    label = labels.get(tool_name, f"Using {tool_name}")
    if args and tool_name != "think":
        # Try to extract the query/question from args JSON
        try:
            import json as _json

            parsed = _json.loads(args)
            q = parsed.get("query") or parsed.get("question") or ""
            if q:
                label += f' — "{q[:50]}"'
        except Exception:
            pass
    return label


async def _stream_managed_agent(
    *,
    manager: AgentManager,
    agent_record: Dict[str, Any],
    user_content: str,
    message_id: str,
    engine: Any,
    bus: Any,
    app_state: Any = None,
) -> StreamingResponse:
    """Run a managed agent with real LLM token streaming via SSE.

    Uses ``engine.stream_full()`` to yield tokens as they arrive from the
    LLM. Supports multi-turn tool-calling: when the model emits tool_calls,
    they are executed and the results fed back for the next turn.
    """
    import json
    import uuid

    from starlette.background import BackgroundTask

    from openjarvis.core.types import Message, Role

    agent_id = agent_record["id"]
    config = agent_record.get("config", {})
    # Resolve the model: prefer the agent's own config, then the server's
    # resolved model (app.state.model — what the engine was booted with),
    # and only then the legacy engine._model attr. OllamaEngine takes the
    # model per-call and exposes no _model attr, so without the app_state
    # fallback this resolved to "" and Ollama 400'd on an empty model.
    model = (
        config.get("model")
        or getattr(app_state, "model", None)
        or getattr(engine, "_model", "")
    )
    system_prompt = config.get("system_prompt")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 1024)
    max_turns = config.get("max_turns", 10)

    # Build conversation messages from history + current input
    llm_messages: List[Message] = []

    # Wire the SystemPromptBuilder to inject SOUL.md / MEMORY.md / USER.md
    # persona files (parity with the CLI/ask path) — see #431.
    app_config = getattr(app_state, "config", None)
    if app_config is None:
        from openjarvis.core.config import load_config

        app_config = load_config()

    final_system_prompt = _build_managed_system_prompt(system_prompt or "", app_config)

    if final_system_prompt and final_system_prompt.strip():
        llm_messages.append(
            Message(role=Role.SYSTEM, content=final_system_prompt.strip())
        )

    # Resolve one live toolkit for every managed-agent path.  The same
    # instances are advertised to the model and used for execution below.
    agent_type = agent_record.get("agent_type", "")
    mcp_adapters: Dict[str, Any] = {}
    mcp_clients: list[Any] = []
    if app_state is not None and config.get("mcp_tools", True) is not False:
        try:
            _, mcp_adapters = _get_mcp_tools(app_state)
            mcp_clients = list(getattr(app_state, "_mcp_clients", []))
        except Exception as exc:
            logger.warning(
                "Failed to get MCP tools for managed agent: %s",
                exc,
                exc_info=True,
            )

    memory_backend = _get_or_create_memory_backend(app_state, app_config)
    channel_backend = getattr(app_state, "channel_backend", None) or getattr(
        app_state, "channel_bridge", None
    )
    resolved_toolkit = resolve_agent_tools(
        agent_record,
        engine=engine,
        model=model,
        memory_backend=memory_backend,
        channel_backend=channel_backend,
        mcp_tools=mcp_adapters.values(),
        mcp_clients=mcp_clients,
        knowledge_db_path=getattr(app_state, "knowledge_db_path", None),
    )

    # Load prior conversation context (DESC order, reverse for chronological).
    # Replaying recorded tool_calls (assistant tool-use + tool results) keeps
    # multi-turn tool behaviour from regressing to fabricated output (#382).
    history = manager.list_messages(agent_id, limit=50)
    llm_messages.extend(_replay_history_messages(history, message_id))

    # Append the current user message
    llm_messages.append(Message(role=Role.USER, content=user_content))

    # Mark the user message as delivered
    manager.mark_message_delivered(message_id)

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # For deep_research agents: run the full agent loop, not raw streaming
    if agent_type == "deep_research":
        dr_tools = resolved_toolkit.instances
        if dr_tools:

            async def generate_deep_research():
                """Run DeepResearchAgent in thread, stream progress + result."""
                import asyncio
                import queue
                import time as _dr_time

                from openjarvis.agents.deep_research import DeepResearchAgent

                progress_q: queue.Queue = queue.Queue()

                # Log query start
                _dr_start = _dr_time.time()
                try:
                    manager.add_learning_log(
                        agent_id,
                        "query_start",
                        f"Query: {user_content[:100]}",
                        {"full_query": user_content},
                    )
                except Exception as _log_exc:
                    logger.warning(
                        "Failed to log query_start: %s",
                        _log_exc,
                    )

                # Patch the agent's tool executor to emit progress
                dr_agent = DeepResearchAgent(
                    engine=engine,
                    model=model,
                    tools=dr_tools,
                    max_turns=int(config.get("max_turns", 8)),
                    temperature=float(config.get("temperature", 0.3)),
                    interactive=True,
                    confirm_callback=lambda _prompt: True,
                )
                if resolved_toolkit.mcp_clients:
                    dr_agent._mcp_clients = resolved_toolkit.mcp_clients

                # Wrap the executor to capture tool calls
                original_execute = dr_agent._executor.execute

                def _tracked_execute(tc):
                    tool_name = tc.name
                    full_args = tc.arguments or ""
                    args_str = full_args[:80]
                    # Log tool call start
                    try:
                        manager.add_learning_log(
                            agent_id,
                            "tool_call",
                            f"Calling {tool_name}: {args_str}",
                            {"tool": tool_name, "arguments": full_args},
                        )
                    except Exception as _tc_exc:
                        logger.warning("Log tool_call failed: %s", _tc_exc)

                    progress_q.put(
                        {
                            "type": "tool_start",
                            "tool": tool_name,
                            "args": args_str,
                            "full_args": full_args,
                        }
                    )
                    _tool_start = _dr_time.monotonic()
                    result = original_execute(tc)
                    _tool_latency_ms = (_dr_time.monotonic() - _tool_start) * 1000

                    # Log tool result
                    try:
                        _ok = "succeeded" if result.success else "failed"
                        _clen = len(result.content) if result.content else 0
                        manager.add_learning_log(
                            agent_id,
                            "tool_result",
                            f"{tool_name} {_ok} ({_clen} chars)",
                            {
                                "tool": tool_name,
                                "success": result.success,
                                "output_length": _clen,
                            },
                        )
                    except Exception as _tr_exc:
                        logger.warning("Log tool_result failed: %s", _tr_exc)

                    progress_q.put(
                        {
                            "type": "tool_end",
                            "tool": tool_name,
                            "arguments": full_args,
                            "success": result.success,
                            "latency": _tool_latency_ms,
                            "result": result.content or "",
                        }
                    )
                    return result

                dr_agent._executor.execute = _tracked_execute

                def _run_agent():
                    agent_metadata = {}
                    try:
                        result = dr_agent.run(user_content)
                        content = result.content or "No results found."
                        agent_metadata = result.metadata or {}
                    except Exception as exc:
                        content = f"Error: {exc}"
                    finally:
                        resolved_toolkit.close()

                    elapsed = _dr_time.time() - _dr_start

                    # Log BEFORE queue put (put triggers SSE end)
                    try:
                        is_err = content.startswith("Error:")
                        manager.add_learning_log(
                            agent_id,
                            "query_error" if is_err else "query_complete",
                            f"{'Error' if is_err else 'Response'}: "
                            f"{len(content)} chars in {elapsed:.1f}s",
                            {
                                "response_length": len(content),
                                "elapsed_seconds": round(elapsed, 2),
                            },
                        )
                    except Exception as _qc_exc:
                        logger.warning(
                            "Log failed: %s",
                            _qc_exc,
                        )

                    progress_q.put(
                        {
                            "type": "error" if content.startswith("Error:") else "done",
                            "content": content,
                            "metadata": agent_metadata,
                            "elapsed": elapsed,
                        }
                    )

                try:
                    _start_managed_worker(
                        app_state,
                        _run_agent,
                        name=f"managed-agent-deep-research-{agent_id}",
                    )
                except Exception as exc:
                    resolved_toolkit.close()
                    progress_q.put(
                        {
                            "type": "error",
                            "content": f"Error: {exc}",
                            "metadata": {},
                            "elapsed": _dr_time.time() - _dr_start,
                        }
                    )

                # Collect tool calls from deep-research so we can persist them
                # alongside the final response (and the UI can re-render them
                # after a page reload).
                dr_tool_calls: List[Dict[str, Any]] = []
                _pending_dr_starts: Dict[str, str] = {}

                # Stream progress events and final content
                while True:
                    try:
                        event = await asyncio.to_thread(progress_q.get, timeout=600)
                    except Exception:
                        # Timeout
                        yield _sse_chunk(chunk_id, model, "Agent timed out.")
                        break

                    if event["type"] == "tool_start":
                        tool = event["tool"]
                        args = event.get("args", "")
                        full_args = event.get("full_args", "")
                        _pending_dr_starts[tool] = full_args
                        # Structured event so the UI can render a tool_call
                        # message card (same shape as the non-DR path).
                        _start_payload = json.dumps(
                            {"tool": tool, "arguments": full_args}
                        )
                        yield f"event: tool_call_start\ndata: {_start_payload}\n\n"
                        # Keep the human-readable progress label for the
                        # thinking-bubble fallback.
                        label = _tool_progress_label(tool, args)
                        progress_data = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": None,
                                    "tool_progress": label,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(progress_data)}\n\n"

                    elif event["type"] == "tool_end":
                        tool = event["tool"]
                        dr_tool_calls.append(
                            {
                                "tool": tool,
                                "arguments": event.get(
                                    "arguments", _pending_dr_starts.get(tool, "")
                                ),
                                "result": event.get("result", ""),
                                "success": bool(event.get("success", False)),
                                "latency": float(event.get("latency", 0.0)),
                            }
                        )
                        _pending_dr_starts.pop(tool, None)
                        _end_payload = json.dumps(
                            {
                                "tool": tool,
                                "success": bool(event.get("success", False)),
                                "latency": float(event.get("latency", 0.0)),
                                "result": event.get("result", ""),
                            }
                        )
                        yield f"event: tool_call_end\ndata: {_end_payload}\n\n"

                    elif event["type"] in ("done", "error"):
                        content = event["content"]
                        meta = event.get("metadata", {})
                        elapsed_s = event.get("elapsed", 0)

                        # Stream content word-by-word
                        words = content.split(" ")
                        for i, word in enumerate(words):
                            token = word if i == 0 else " " + word
                            yield _sse_chunk(chunk_id, model, token)

                        # Build usage + telemetry
                        prompt_tok = meta.get("prompt_tokens", 0)
                        comp_tok = meta.get("completion_tokens", 0)
                        total_tok = meta.get("total_tokens", 0)
                        word_count = len(words)
                        speed = round(word_count / elapsed_s) if elapsed_s > 0 else 0

                        # Final chunk with usage + telemetry
                        finish_data = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": "stop",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": prompt_tok,
                                "completion_tokens": comp_tok,
                                "total_tokens": total_tok or (prompt_tok + comp_tok),
                            },
                            "telemetry": {
                                "engine": "ollama",
                                "model_id": model,
                                "total_ms": round(elapsed_s * 1000),
                                "tokens_per_sec": speed,
                                "tool_calls": len(meta.get("sources", [])),
                            },
                        }
                        yield f"data: {json.dumps(finish_data)}\n\n"
                        yield "data: [DONE]\n\n"

                        # Persist (with the tool calls captured during
                        # the deep-research turn so they survive reload).
                        manager.store_agent_response(
                            agent_id,
                            content,
                            tool_calls=dr_tool_calls or None,
                        )
                        break

            return StreamingResponse(
                generate_deep_research(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

    # The canonical resolver exposes the same live instances as OpenAI specs
    # for engines that run the generic streaming loop.
    stream_kwargs: Dict[str, Any] = {}
    if resolved_toolkit.openai_specs:
        stream_kwargs["tools"] = resolved_toolkit.openai_specs

    from openjarvis.tools._stubs import ToolExecutor

    resolved_by_name = resolved_toolkit.by_name
    stream_tool_executor = ToolExecutor(
        tools=resolved_toolkit.instances,
        bus=bus,
        interactive=True,
        confirm_callback=lambda _prompt: True,
    )

    # Forward any per-agent sampler params (repetition_penalty, top_p, …) so
    # locally-hosted models can be tuned per agent (#386).
    stream_kwargs.update(_sampler_kwargs(config))

    # Shared state between the generator and the BackgroundTask that
    # runs after the SSE response completes (or the client disconnects
    # mid-stream). Starlette guarantees the BackgroundTask runs in both
    # cases, so we use it as the single, reliable persistence point.
    persist_state: Dict[str, Any] = {
        "content": "",
        "tool_calls": [],
        "persisted": False,
    }

    def _persist_final() -> None:
        if persist_state["persisted"]:
            return
        persist_state["persisted"] = True
        if persist_state["content"]:
            try:
                manager.store_agent_response(
                    agent_id,
                    persist_state["content"],
                    tool_calls=persist_state["tool_calls"] or None,
                )
            except Exception as store_exc:
                logger.error(
                    "Failed to store agent response: %s",
                    store_exc,
                    exc_info=True,
                )
        try:
            content = persist_state["content"] or ""
            manager.add_learning_log(
                agent_id,
                "query_complete",
                f"Response: {len(content)} chars, "
                f"{len(persist_state['tool_calls'])} tool calls",
                {
                    "response_length": len(content),
                    "tool_calls": len(persist_state["tool_calls"]),
                },
            )
        except Exception as _qc_exc:
            logger.warning("Log query_complete failed: %s", _qc_exc)

    def _finalize_stream() -> None:
        try:
            _persist_final()
        finally:
            resolved_toolkit.close()

    async def generate():
        """Async generator yielding SSE-formatted chunks with real token streaming."""

        collected_content = ""
        collected_tool_calls: List[Dict[str, Any]] = []
        messages_for_llm = list(llm_messages)
        turns = 0

        import time as _lgtime

        _query_start_ts = _lgtime.time()
        try:
            manager.add_learning_log(
                agent_id,
                "query_start",
                f"Query: {user_content[:100]}",
                {"full_query": user_content},
            )
        except Exception as _qs_exc:
            logger.warning("Log query_start failed: %s", _qs_exc)

        while turns < max_turns:
            turns += 1
            turn_content = ""
            tool_call_fragments: Dict[int, Dict[str, Any]] = {}
            current_finish_reason = None

            try:
                async for chunk in engine.stream_full(
                    messages_for_llm,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **stream_kwargs,
                ):
                    # Stream content tokens immediately to the client
                    if chunk.content:
                        turn_content += chunk.content
                        # Mirror partial content so a disconnect during
                        # generation still saves what we've produced.
                        persist_state["content"] = collected_content + turn_content
                        chunk_data = {
                            "id": chunk_id,
                            "object": "chat.completion.chunk",
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": chunk.content},
                                    "finish_reason": None,
                                }
                            ],
                        }
                        yield f"data: {json.dumps(chunk_data)}\n\n"

                    # Accumulate tool_call fragments
                    if chunk.tool_calls:
                        _merge_tool_call_fragments(
                            tool_call_fragments,
                            chunk.tool_calls,
                        )

                    if chunk.finish_reason:
                        current_finish_reason = chunk.finish_reason

            except Exception as exc:
                logger.error("Managed agent stream error: %s", exc, exc_info=True)
                error_data = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"Error: {exc}"},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(error_data)}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Handle tool calls: execute tools and loop for next turn
            if tool_call_fragments and current_finish_reason == "tool_calls":
                # Build the assistant message with tool_calls
                sorted_tcs = [
                    tool_call_fragments[i] for i in sorted(tool_call_fragments.keys())
                ]

                # Add assistant message with tool_calls to conversation
                from openjarvis.core.types import ToolCall as MsgToolCall

                assistant_msg = Message(
                    role=Role.ASSISTANT,
                    content=turn_content or None,
                    tool_calls=[
                        MsgToolCall(
                            id=tc["id"],
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        )
                        for tc in sorted_tcs
                    ],
                )
                messages_for_llm.append(assistant_msg)

                # Execute each tool call and append results. Emit
                # tool_call_start/tool_call_end around each call so the UI
                # can render them live (same event names as the main chat
                # in stream_bridge.py).
                import time as _time

                for tc in sorted_tcs:
                    tool_name = tc["function"]["name"]
                    tool_args = tc["function"]["arguments"]
                    tool_result_content = f"Tool '{tool_name}' not available"
                    tool_succeeded = False

                    _start_payload = json.dumps(
                        {"tool": tool_name, "arguments": tool_args}
                    )
                    yield f"event: tool_call_start\ndata: {_start_payload}\n\n"
                    try:
                        manager.add_learning_log(
                            agent_id,
                            "tool_call",
                            f"Calling {tool_name}: {tool_args[:80]}",
                            {"tool": tool_name, "arguments": tool_args or ""},
                        )
                    except Exception as _tc_exc:
                        logger.warning("Log tool_call failed: %s", _tc_exc)
                    tool_start_ms = _time.monotonic() * 1000

                    try:
                        if tool_name in resolved_by_name:
                            result = stream_tool_executor.execute(
                                MsgToolCall(
                                    id=tc["id"],
                                    name=tool_name,
                                    arguments=tool_args,
                                )
                            )
                            tool_result_content = result.content
                            tool_succeeded = bool(result.success)
                        else:
                            logger.warning(
                                "Tool '%s' was not included in the resolved toolkit",
                                tool_name,
                            )
                    except Exception as tool_exc:
                        logger.error(
                            "Tool execution error for %s: %s",
                            tool_name,
                            tool_exc,
                            exc_info=True,
                        )
                        tool_result_content = f"Error executing {tool_name}: {tool_exc}"

                    tool_latency_ms = (_time.monotonic() * 1000) - tool_start_ms
                    collected_tool_calls.append(
                        {
                            "tool": tool_name,
                            "arguments": tool_args,
                            "result": tool_result_content,
                            "success": tool_succeeded,
                            "latency": tool_latency_ms,
                        }
                    )
                    # Update the shared persist state so mid-stream
                    # disconnects still capture already-executed tools.
                    persist_state["tool_calls"] = list(collected_tool_calls)
                    try:
                        _ok = "succeeded" if tool_succeeded else "failed"
                        _clen = len(tool_result_content) if tool_result_content else 0
                        manager.add_learning_log(
                            agent_id,
                            "tool_result",
                            f"{tool_name} {_ok} ({_clen} chars)",
                            {
                                "tool": tool_name,
                                "success": tool_succeeded,
                                "output_length": _clen,
                            },
                        )
                    except Exception as _tr_exc:
                        logger.warning("Log tool_result failed: %s", _tr_exc)
                    _end_payload = json.dumps(
                        {
                            "tool": tool_name,
                            "success": tool_succeeded,
                            "latency": tool_latency_ms,
                            "result": tool_result_content,
                        }
                    )
                    yield f"event: tool_call_end\ndata: {_end_payload}\n\n"

                    # Add tool result message to conversation
                    messages_for_llm.append(
                        Message(
                            role=Role.TOOL,
                            content=tool_result_content,
                            tool_call_id=tc["id"],
                            name=tool_name,
                        )
                    )

                # Continue to next turn (loop back to stream_full)
                collected_content += turn_content
                # Mirror to shared state so BackgroundTask can persist
                # even if the client disconnects mid-stream.
                persist_state["content"] = collected_content
                persist_state["tool_calls"] = list(collected_tool_calls)
                continue

            # No tool calls — this is the final response
            collected_content += turn_content
            persist_state["content"] = collected_content
            persist_state["tool_calls"] = list(collected_tool_calls)
            break

        # Final chunk with finish_reason
        final_data = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_data)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        background=BackgroundTask(_finalize_stream),
    )


def create_agent_manager_router(
    manager: AgentManager,
) -> Tuple[APIRouter, APIRouter, APIRouter, APIRouter, APIRouter]:
    """Create FastAPI routers with agent management endpoints.

    Returns a 5-tuple:
    ``(agents_router, templates_router, global_router, tools_router, sendblue_router)``.
    """
    agents_router = APIRouter(prefix="/v1/managed-agents", tags=["managed-agents"])
    templates_router = APIRouter(prefix="/v1/templates", tags=["templates"])

    # ── Agent lifecycle ──────────────────────────────────────

    @agents_router.get("")
    async def list_agents():
        return {"agents": manager.list_agents()}

    @agents_router.post("")
    async def create_agent(req: CreateAgentRequest, request: Request):
        if req.template_id:
            agent = manager.create_from_template(
                req.template_id, req.name, overrides=req.config
            )
        else:
            agent = manager.create_agent(
                name=req.name, agent_type=req.agent_type, config=req.config
            )

        # Register with scheduler if cron/interval
        scheduler = getattr(request.app.state, "agent_scheduler", None)
        sched_type = (req.config or {}).get("schedule_type", "manual")
        if scheduler and sched_type in ("cron", "interval"):
            scheduler.register_agent(agent["id"])

        return agent

    @agents_router.get("/{agent_id}")
    async def get_agent(agent_id: str):
        agent = manager.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent

    @agents_router.patch("/{agent_id}")
    async def update_agent(agent_id: str, req: UpdateAgentRequest):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        kwargs: Dict[str, Any] = {}
        if req.name is not None:
            kwargs["name"] = req.name
        if req.agent_type is not None:
            kwargs["agent_type"] = req.agent_type
        if req.config is not None:
            kwargs["config"] = req.config
        return manager.update_agent(agent_id, **kwargs)

    @agents_router.delete("/{agent_id}")
    async def delete_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        manager.delete_agent(agent_id)
        return {"status": "archived"}

    @agents_router.post("/{agent_id}/pause")
    async def pause_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        manager.pause_agent(agent_id)
        return {"status": "paused"}

    @agents_router.post("/{agent_id}/resume")
    async def resume_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        manager.resume_agent(agent_id)
        return {"status": "idle"}

    @agents_router.post("/{agent_id}/run")
    async def run_agent(agent_id: str, request: Request):
        agent = manager.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent["status"] == "archived":
            raise HTTPException(status_code=400, detail="Agent is archived")

        # Auto-recover from error/needs_attention state
        if agent["status"] in ("error", "needs_attention"):
            manager.update_agent(agent_id, status="idle")

        # Acquire tick BEFORE spawning thread — prevents race
        try:
            manager.start_tick(agent_id)
        except ValueError:
            raise HTTPException(status_code=409, detail="Agent is already running")

        # Re-use the server's engine + model so we don't pick a
        # random model from Ollama's list.
        app_state = request.app.state
        server_engine = getattr(app_state, "engine", None)
        server_model = getattr(app_state, "model", "")
        server_config = getattr(app_state, "config", None)
        server_bus = _get_runtime_event_bus(app_state)

        def _run_tick():
            try:
                from openjarvis.agents.executor import AgentExecutor

                _ts = getattr(app_state, "trace_store", None)
                executor = AgentExecutor(
                    manager=manager,
                    event_bus=server_bus,
                    trace_store=_ts,
                )
                system = _make_lightweight_system(
                    server_engine,
                    server_model,
                    server_config,
                    app_state,
                )
                executor.set_system(system)
                # The route handler above already called start_tick() to
                # serialize concurrent POSTs; tell the executor not to
                # re-acquire, otherwise it bails on its own guard and the
                # tick never runs.
                executor.execute_tick(agent_id, lock_already_held=True)
            except Exception as exc:
                logger.error(
                    "Run-tick failed for agent %s: %s",
                    agent_id,
                    exc,
                    exc_info=True,
                )
                try:
                    manager.end_tick(agent_id)
                except Exception:
                    pass
                manager.update_agent(agent_id, status="error")
                manager.update_summary_memory(
                    agent_id,
                    f"ERROR: {exc}",
                )

        try:
            _start_managed_worker(
                app_state,
                _run_tick,
                name=f"managed-agent-run-{agent_id}",
            )
        except RuntimeError as exc:
            try:
                manager.end_tick(agent_id)
            except Exception:
                pass
            raise HTTPException(status_code=503, detail=str(exc))
        return {"status": "running", "agent_id": agent_id}

    # ── Recover ──────────────────────────────────────────────

    @agents_router.post("/{agent_id}/recover")
    def recover_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        checkpoint = manager.recover_agent(agent_id)
        return {"recovered": True, "checkpoint": checkpoint}

    # ── Tasks ────────────────────────────────────────────────

    @agents_router.get("/{agent_id}/tasks")
    async def list_tasks(agent_id: str, status: Optional[str] = None):
        return {"tasks": manager.list_tasks(agent_id, status=status)}

    @agents_router.post("/{agent_id}/tasks")
    async def create_task(agent_id: str, req: CreateTaskRequest):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        return manager.create_task(agent_id, description=req.description)

    @agents_router.get("/{agent_id}/tasks/{task_id}")
    async def get_task(agent_id: str, task_id: str):
        task = manager._get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @agents_router.patch("/{agent_id}/tasks/{task_id}")
    async def update_task(agent_id: str, task_id: str, req: UpdateTaskRequest):
        kwargs: Dict[str, Any] = {}
        if req.description is not None:
            kwargs["description"] = req.description
        if req.status is not None:
            kwargs["status"] = req.status
        if req.progress is not None:
            kwargs["progress"] = req.progress
        if req.findings is not None:
            kwargs["findings"] = req.findings
        return manager.update_task(task_id, **kwargs)

    @agents_router.delete("/{agent_id}/tasks/{task_id}")
    async def delete_task(agent_id: str, task_id: str):
        manager.delete_task(task_id)
        return {"status": "deleted"}

    # ── Channel bindings ─────────────────────────────────────

    @agents_router.get("/{agent_id}/channels")
    async def list_channels(agent_id: str):
        return {"bindings": manager.list_channel_bindings(agent_id)}

    @agents_router.post("/{agent_id}/channels")
    async def bind_channel(
        agent_id: str,
        req: BindChannelRequest,
        request: Request,
    ):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        binding = manager.bind_channel(
            agent_id,
            channel_type=req.channel_type,
            config=req.config,
            routing_mode=req.routing_mode,
        )

        # Start iMessage daemon if binding iMessage
        if req.channel_type == "imessage":
            identifier = (req.config or {}).get("identifier", "")
            if identifier:
                try:
                    from openjarvis.channels.imessage_daemon import (
                        is_running,
                        run_daemon,
                    )

                    if not is_running():
                        import threading

                        engine = getattr(request.app.state, "engine", None)
                        if engine:
                            tools = _build_deep_research_tools(engine=engine, model="")
                            if tools:
                                from openjarvis.agents.deep_research import (
                                    DeepResearchAgent,
                                )

                                agent_inst = DeepResearchAgent(
                                    engine=engine,
                                    model=getattr(engine, "_model", ""),
                                    tools=tools,
                                    interactive=True,
                                    confirm_callback=lambda _prompt: True,
                                )

                                def handler(text: str) -> str:
                                    result = agent_inst.run(text)
                                    return result.content or "No results."

                                t = threading.Thread(
                                    target=run_daemon,
                                    kwargs={
                                        "chat_identifier": identifier,
                                        "handler": handler,
                                    },
                                    daemon=True,
                                )
                                t.start()
                except Exception as exc:
                    logger.warning("Failed to start iMessage daemon: %s", exc)

        # Initialize SendBlue channel if binding sendblue
        if req.channel_type == "sendblue":
            config = req.config or {}
            api_key_id = config.get("api_key_id", "")
            api_secret_key = config.get("api_secret_key", "")
            from_number = config.get("from_number", "")
            if api_key_id and api_secret_key:
                try:
                    from openjarvis.channels.sendblue import (
                        SendBlueChannel,
                    )

                    sb_channel = SendBlueChannel(
                        api_key_id=api_key_id,
                        api_secret_key=api_secret_key,
                        from_number=from_number,
                    )
                    sb_channel.connect()
                    # Store on app state so webhook route can use it
                    request.app.state.sendblue_channel = sb_channel

                    # Create or update the channel bridge
                    bridge = getattr(request.app.state, "channel_bridge", None)
                    if bridge and hasattr(bridge, "_channels"):
                        bridge._channels["sendblue"] = sb_channel
                    else:
                        # Create a new ChannelBridge with DeepResearch
                        from openjarvis.server.channel_bridge import (
                            ChannelBridge,
                        )
                        from openjarvis.server.session_store import (
                            SessionStore,
                        )

                        session_store = SessionStore()
                        engine = getattr(request.app.state, "engine", None)
                        dr_agent = None
                        if engine:
                            tools = _build_deep_research_tools(engine=engine, model="")
                            if tools:
                                from openjarvis.agents.deep_research import (
                                    DeepResearchAgent,
                                )

                                model_name = getattr(engine, "_model", "") or getattr(
                                    request.app.state,
                                    "model",
                                    "",
                                )
                                dr_agent = DeepResearchAgent(
                                    engine=engine,
                                    model=model_name,
                                    tools=tools,
                                    interactive=True,
                                    confirm_callback=lambda _prompt: True,
                                )
                        bus = getattr(request.app.state, "bus", None)
                        if bus is None:
                            from openjarvis.core.events import EventBus

                            bus = EventBus()
                        bridge = ChannelBridge(
                            channels={"sendblue": sb_channel},
                            session_store=session_store,
                            bus=bus,
                            agent_manager=manager,
                            deep_research_agent=dr_agent,
                        )
                        request.app.state.channel_bridge = bridge

                    logger.info(
                        "SendBlue channel connected: %s",
                        from_number,
                    )
                except Exception as exc:
                    logger.warning("Failed to init SendBlue channel: %s", exc)

        # Start Slack via slack-bolt Socket Mode
        if req.channel_type == "slack":
            config = req.config or {}
            bot_token = config.get("bot_token", "")
            app_token = config.get("app_token", "")
            if bot_token and app_token:
                try:
                    from openjarvis.channels.slack_daemon import (
                        start_slack_daemon,
                    )
                    from openjarvis.channels.slack_daemon import (
                        stop_daemon as stop_slack,
                    )

                    # Stop any existing daemon first
                    stop_slack()

                    # Spawn as subprocess (reliable)
                    srv_model = (
                        getattr(
                            getattr(
                                request.app.state,
                                "engine",
                                None,
                            ),
                            "_model",
                            "qwen3.5:9b",
                        )
                        or "qwen3.5:9b"
                    )
                    pid = start_slack_daemon(
                        bot_token=bot_token,
                        app_token=app_token,
                        model=srv_model,
                    )
                    logger.info(
                        "Slack daemon started (PID %d)",
                        pid,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to start Slack: %s",
                        exc,
                    )

        return binding

    @agents_router.delete("/{agent_id}/channels/{binding_id}")
    async def unbind_channel(
        agent_id: str,
        binding_id: str,
        request: Request,
    ):
        try:
            binding = manager._get_binding(binding_id)
            if binding:
                ch_type = binding.get("channel_type")
                if ch_type == "imessage":
                    from openjarvis.channels.imessage_daemon import (
                        stop_daemon,
                    )

                    stop_daemon()
                elif ch_type == "slack":
                    from openjarvis.channels.slack_daemon import (
                        stop_daemon as stop_slack_daemon,
                    )

                    stop_slack_daemon()
        except Exception:
            pass
        manager.unbind_channel(binding_id)
        return {"status": "unbound"}

    # ── Messaging ────────────────────────────────────────────

    @agents_router.get("/{agent_id}/messages")
    def list_messages(agent_id: str):
        return {"messages": manager.list_messages(agent_id)}

    @agents_router.post("/{agent_id}/messages")
    async def send_message(agent_id: str, req: SendMessageRequest, request: Request):
        agent_record = manager.get_agent(agent_id)
        if not agent_record:
            raise HTTPException(status_code=404, detail="Agent not found")

        # Auto-recover error-state agents on immediate messages
        if req.mode == "immediate" and agent_record["status"] in (
            "error",
            "needs_attention",
        ):
            manager.update_agent(agent_id, status="idle")

        # Store user message in DB (always, regardless of stream mode)
        msg = manager.send_message(agent_id, req.content, mode=req.mode)

        if not req.stream and req.mode != "immediate":
            return msg

        if not req.stream and req.mode == "immediate":
            # Non-streaming immediate: trigger a background tick so the
            # agent processes the message, then return the stored msg.
            # Re-use the server's existing system (correct model/engine).
            import time as _time

            from openjarvis.agents.executor import AgentExecutor

            _app_state = request.app.state
            _srv_engine = getattr(_app_state, "engine", None)
            _srv_model = getattr(_app_state, "model", "")
            _srv_config = getattr(_app_state, "config", None)
            _srv_bus = _get_runtime_event_bus(_app_state)

            def _immediate_tick():
                _start = _time.time()
                logger.info(
                    "Immediate tick starting for agent %s (model=%s)",
                    agent_id,
                    _srv_model,
                )
                try:
                    _ts2 = getattr(_app_state, "trace_store", None)
                    executor = AgentExecutor(
                        manager=manager,
                        event_bus=_srv_bus,
                        trace_store=_ts2,
                    )
                    system = _make_lightweight_system(
                        _srv_engine,
                        _srv_model,
                        _srv_config,
                        _app_state,
                    )
                    executor.set_system(system)
                    logger.info(
                        "Immediate tick: system ready in %.1fs, "
                        "executing tick for agent %s",
                        _time.time() - _start,
                        agent_id,
                    )
                    executor.execute_tick(agent_id)
                    logger.info(
                        "Immediate tick completed for agent %s in %.1fs",
                        agent_id,
                        _time.time() - _start,
                    )
                except Exception as exc:
                    logger.error(
                        "Immediate tick failed for agent %s: %s",
                        agent_id,
                        exc,
                        exc_info=True,
                    )
                    try:
                        manager.end_tick(agent_id)
                    except Exception:
                        pass
                    manager.update_agent(agent_id, status="error")
                    manager.update_summary_memory(
                        agent_id,
                        f"ERROR: {exc}",
                    )

            try:
                _start_managed_worker(
                    _app_state,
                    _immediate_tick,
                    name=f"managed-agent-immediate-{agent_id}",
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc))
            return msg

        # --- Streaming mode: run agent and return SSE response ---
        engine = getattr(request.app.state, "engine", None)
        bus = getattr(request.app.state, "bus", None)
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="Engine not available for streaming",
            )

        return await _stream_managed_agent(
            manager=manager,
            agent_record=agent_record,
            user_content=req.content,
            message_id=msg["id"],
            engine=engine,
            bus=bus,
            app_state=request.app.state,
        )

    # ── State inspection ─────────────────────────────────────

    @agents_router.get("/{agent_id}/state")
    def get_agent_state(agent_id: str):
        agent = manager.get_agent(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "agent": agent,
            "tasks": manager.list_tasks(agent_id),
            "channels": manager.list_channel_bindings(agent_id),
            "messages": manager.list_messages(agent_id),
            "checkpoint": manager.get_latest_checkpoint(agent_id),
        }

    # ── Learning ─────────────────────────────────────────────

    @agents_router.get("/{agent_id}/learning")
    def get_learning_log(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        return {"learning_log": manager.list_learning_log(agent_id)}

    @agents_router.post("/{agent_id}/learning/run")
    def trigger_learning(agent_id: str, request: Request):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        from openjarvis.core.events import EventType

        bus = _get_runtime_event_bus(request.app.state)
        bus.publish(EventType.AGENT_LEARNING_STARTED, {"agent_id": agent_id})
        return {"status": "triggered"}

    # ── Traces ───────────────────────────────────────────────

    @agents_router.get("/{agent_id}/traces")
    def list_traces(agent_id: str, limit: int = 20):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        try:
            from openjarvis.core.config import load_config
            from openjarvis.core.paths import get_config_dir
            from openjarvis.traces.store import TraceStore

            config = load_config()
            store = TraceStore(
                config.traces.db_path or str(get_config_dir() / "traces.db")
            )
            traces = store.list_traces(agent=agent_id, limit=limit)
            return {
                "traces": [
                    {
                        "id": t.trace_id,
                        "outcome": t.outcome,
                        "duration": t.total_latency_seconds,
                        "started_at": t.started_at,
                        "steps": len(t.steps),
                        "metadata": t.metadata,
                    }
                    for t in traces
                ]
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @agents_router.get("/{agent_id}/traces/{trace_id}")
    def get_trace(agent_id: str, trace_id: str):
        try:
            from openjarvis.core.config import load_config
            from openjarvis.core.paths import get_config_dir
            from openjarvis.traces.store import TraceStore

            config = load_config()
            store = TraceStore(
                config.traces.db_path or str(get_config_dir() / "traces.db")
            )
            trace = store.get(trace_id)
            if trace is None:
                raise HTTPException(status_code=404, detail="Trace not found")
            return {
                "id": trace.trace_id,
                "agent": trace.agent,
                "outcome": trace.outcome,
                "duration": trace.total_latency_seconds,
                "started_at": trace.started_at,
                "steps": [
                    {
                        "step_type": s.step_type.value,
                        "input": s.input,
                        "output": s.output,
                        "duration": s.duration_seconds,
                        "metadata": s.metadata,
                    }
                    for s in trace.steps
                ],
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    # ── Templates ────────────────────────────────────────────

    @templates_router.get("")
    async def list_templates():
        return {"templates": AgentManager.list_templates()}

    @templates_router.post("/{template_id}/instantiate")
    async def instantiate_template(template_id: str, req: CreateAgentRequest):
        return manager.create_from_template(template_id, req.name, overrides=req.config)

    # ── Global agent endpoints ───────────────────────────────

    global_router = APIRouter(tags=["agents-global"])

    @global_router.get("/v1/agents/errors")
    def list_error_agents():
        all_agents = manager.list_agents()
        error_agents = [
            a
            for a in all_agents
            if a["status"] in ("error", "needs_attention", "stalled", "budget_exceeded")
        ]
        return {"agents": error_agents}

    @global_router.get("/v1/agents/health")
    def agents_health():
        all_agents = manager.list_agents()
        from collections import Counter

        counts = Counter(a["status"] for a in all_agents)
        return {
            "total": len(all_agents),
            "by_status": dict(counts),
        }

    @global_router.get("/v1/recommended-model")
    def recommended_model(request: Request):
        engine = getattr(request.app.state, "engine", None)
        if engine is None:
            return {"model": "", "reason": "No engine available"}
        try:
            models = engine.list_models()
        except Exception:
            models = []
        return _pick_recommended_model(models)

    # ── Tools & credentials ──────────────────────────────────

    tools_router = APIRouter(prefix="/v1/tools", tags=["tools"])

    @tools_router.get("")
    def list_tools(request: Request):
        items = build_tools_list()
        try:
            mcp_tools, _ = _get_mcp_tools(request.app.state)
            for tool in mcp_tools:
                fn = tool.get("function", {})
                items.append(
                    {
                        "name": fn.get("name", ""),
                        "description": fn.get("description", ""),
                        "category": "mcp",
                        "source": "mcp",
                        "requires_credentials": False,
                        "credential_keys": [],
                        "configured": True,
                    }
                )
        except Exception:
            pass
        return {"tools": items}

    @tools_router.post("/{tool_name}/credentials")
    async def save_tool_credentials(tool_name: str, request: Request):
        from openjarvis.core.credentials import save_credential

        body = await request.json()
        saved = []
        for key, value in body.items():
            save_credential(tool_name, key, value)
            saved.append(key)
        return {"saved": saved}

    @tools_router.delete("/{tool_name}/credentials/{key}")
    def remove_tool_credential(tool_name: str, key: str):
        from openjarvis.core.credentials import delete_credential

        delete_credential(tool_name, key)
        return {"deleted": key}

    @tools_router.get("/{tool_name}/credentials/status")
    def credential_status(tool_name: str):
        from openjarvis.core.credentials import get_credential_status

        return get_credential_status(tool_name)

    # ── SendBlue auto-setup helpers ─────────────────────────

    sendblue_router = APIRouter(prefix="/v1/channels/sendblue", tags=["sendblue"])

    @sendblue_router.post("/verify")
    async def sendblue_verify(request: Request):
        """Verify SendBlue credentials and return assigned phone lines."""
        body = await request.json()
        api_key_id = body.get("api_key_id", "")
        api_secret_key = body.get("api_secret_key", "")
        if not api_key_id or not api_secret_key:
            raise HTTPException(
                status_code=400,
                detail="api_key_id and api_secret_key are required",
            )

        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.sendblue.co/api/lines",
                    headers={
                        "sb-api-key-id": api_key_id,
                        "sb-api-secret-key": api_secret_key,
                    },
                )
            if resp.status_code == 401:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid SendBlue credentials",
                )
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=f"SendBlue API error: {resp.text[:200]}",
                )
            data = resp.json()
            # data might be a list of lines or {"lines": [...]}
            lines = (
                data
                if isinstance(data, list)
                else data.get("lines", data.get("data", []))
            )
            numbers = []
            for line in lines:
                if isinstance(line, str):
                    num = line
                elif isinstance(line, dict):
                    num = (
                        line.get("number")
                        or line.get("phone_number")
                        or line.get("from_number")
                    )
                else:
                    num = None
                if num:
                    numbers.append(num)
            return {
                "valid": True,
                "numbers": numbers,
                "raw": data,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach SendBlue: {exc}",
            )

    @sendblue_router.post("/register-webhook")
    async def sendblue_register_webhook(request: Request):
        """Auto-register the /webhooks/sendblue endpoint with SendBlue."""
        body = await request.json()
        api_key_id = body.get("api_key_id", "")
        api_secret_key = body.get("api_secret_key", "")
        webhook_url = body.get("webhook_url", "")
        if not webhook_url:
            raise HTTPException(
                status_code=400,
                detail="webhook_url is required",
            )

        import httpx

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.sendblue.co/api/account/webhooks",
                    headers={
                        "sb-api-key-id": api_key_id,
                        "sb-api-secret-key": api_secret_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "receive": webhook_url,
                    },
                )
            return {
                "registered": resp.status_code < 300,
                "status": resp.status_code,
                "response": resp.json() if resp.status_code < 300 else resp.text[:200],
            }
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to register webhook: {exc}",
            )

    @sendblue_router.post("/test")
    async def sendblue_test(request: Request):
        """Send a test message via SendBlue to verify the setup works."""
        body = await request.json()
        api_key_id = body.get("api_key_id", "")
        api_secret_key = body.get("api_secret_key", "")
        from_number = body.get("from_number", "")
        to_number = body.get("to_number", "")
        if not to_number:
            raise HTTPException(
                status_code=400,
                detail="to_number is required",
            )

        import httpx

        try:
            payload: Dict[str, str] = {
                "number": to_number,
                "content": (
                    "Hello from your OpenJarvis agent! "
                    "Text this number anytime to search your "
                    "personal data. Reply with any question to try it."
                ),
            }
            if from_number:
                payload["from_number"] = from_number

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.sendblue.co/api/send-message",
                    headers={
                        "sb-api-key-id": api_key_id,
                        "sb-api-secret-key": api_secret_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            return {
                "sent": resp.status_code < 300,
                "status": resp.status_code,
                "response": resp.json() if resp.status_code < 300 else resp.text[:200],
            }
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to send test message: {exc}",
            )

    @sendblue_router.get("/health")
    async def sendblue_health(request: Request):
        """Check if the SendBlue channel bridge is wired and ready."""
        sb = getattr(request.app.state, "sendblue_channel", None)
        bridge = getattr(request.app.state, "channel_bridge", None)
        has_bridge = bridge is not None and (
            hasattr(bridge, "_channels") and "sendblue" in bridge._channels
        )
        return {
            "channel_connected": sb is not None,
            "bridge_wired": has_bridge,
            "ready": sb is not None and has_bridge,
        }

    return (
        agents_router,
        templates_router,
        global_router,
        tools_router,
        sendblue_router,
    )
