"""FastAPI routes for the Agent Manager."""

from __future__ import annotations

import logging
import re as _re
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents.manager import AgentManager

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel
except ImportError:
    raise ImportError("fastapi and pydantic are required for server routes")

logger = logging.getLogger("openjarvis.server.agent_manager")


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


_BROWSER_SUB_TOOLS = {
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "browser_extract",
    "browser_axtree",
}


class _LightweightSystem:
    """Minimal system facade for the executor — avoids rebuilding the
    full JarvisSystem (which picks a random model from Ollama)."""

    def __init__(self, engine: Any, model: str, config: Any = None):
        self.engine = engine
        self.model = model
        self.config = config
        self.memory_backend = None


def _make_lightweight_system(
    engine: Any,
    model: str,
    config: Any = None,
) -> _LightweightSystem:
    """Build a minimal system with a plain OllamaEngine.

    The server's ``app.state.engine`` is heavily wrapped
    (MultiEngine -> InstrumentedEngine -> GuardrailsEngine) and can
    return empty content from background threads.  Create a fresh
    OllamaEngine directly (no health checks or model discovery that
    could interfere with in-flight Ollama requests).
    """
    try:
        from openjarvis.engine.ollama import OllamaEngine

        cfg = config
        if cfg is None:
            from openjarvis.core.config import load_config

            cfg = load_config()
        host = cfg.engine.ollama.host if cfg else ""
        plain_engine = OllamaEngine(host=host) if host else OllamaEngine()
        # Wrap with InstrumentedEngine so agent ticks are recorded
        # in telemetry (FLOPs, energy, cost savings).
        try:
            from openjarvis.core.events import get_event_bus
            from openjarvis.telemetry.instrumented_engine import (
                InstrumentedEngine,
            )

            plain_engine = InstrumentedEngine(
                plain_engine,
                get_event_bus(),
            )
        except Exception:
            pass  # telemetry is optional
        return _LightweightSystem(plain_engine, model, cfg)
    except Exception:
        pass
    return _LightweightSystem(engine, model, config)


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
    """Pick the second-largest local model from a list."""
    local = [m for m in model_ids if not any(m.startswith(p) for p in _CLOUD_PREFIXES)]
    if not local:
        return {
            "model": model_ids[0] if model_ids else "",
            "reason": "Only model available",
        }
    sized = sorted(local, key=_parse_param_count, reverse=True)
    if len(sized) == 1:
        return {"model": sized[0], "reason": "Only local model available"}
    pick = sized[1]  # second-largest
    params = _parse_param_count(pick)
    return {
        "model": pick,
        "reason": f"Second-largest local model ({params}B parameters)",
    }


def _ensure_registries_populated() -> None:
    """Ensure ToolRegistry and ChannelRegistry are populated.

    If the registries are empty (e.g. cleared by test fixtures) but the
    modules are already cached in sys.modules, reload the individual
    submodules to re-execute their @register decorators.
    """
    import importlib
    import sys

    from openjarvis.core.registry import ChannelRegistry, ToolRegistry

    # First, try a normal import (works if modules haven't been imported yet)
    try:
        import openjarvis.channels  # noqa: F401
    except Exception:
        pass

    try:
        import openjarvis.tools  # noqa: F401
    except Exception:
        pass

    # Also try to import browser tools (not included in openjarvis.tools.__init__)
    for _browser_mod in ("openjarvis.tools.browser", "openjarvis.tools.browser_axtree"):
        try:
            importlib.import_module(_browser_mod)
        except Exception:
            pass

    # If registries are still empty, reload individual submodules from sys.modules
    if not ChannelRegistry.keys():
        for mod_name in list(sys.modules):
            if mod_name.startswith("openjarvis.channels.") and not mod_name.endswith(
                "_stubs"
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass

    if not ToolRegistry.keys():
        for mod_name in list(sys.modules):
            if (
                mod_name.startswith("openjarvis.tools.")
                and not mod_name.endswith("_stubs")
                and not mod_name.endswith("agent_tools")
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass

    # After reloading tools, also try browser tools if still not registered
    if not any(ToolRegistry.contains(n) for n in _BROWSER_SUB_TOOLS):
        for _browser_mod in (
            "openjarvis.tools.browser",
            "openjarvis.tools.browser_axtree",
        ):
            mod = sys.modules.get(_browser_mod)
            if mod is not None:
                try:
                    importlib.reload(mod)
                except Exception:
                    pass


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
            spec = tool_cls().spec
        except Exception as exc:
            logger.debug("Could not instantiate tool %s: %s", name, exc)
            spec = None
        cred_keys = TOOL_CREDENTIALS.get(name, [])
        items.append(
            {
                "name": name,
                "description": spec.description if spec else "",
                "category": spec.category if spec else "",
                "source": "tool",
                "requires_credentials": len(cred_keys) > 0,
                "credential_keys": cred_keys,
                "configured": (
                    all(bool(os.environ.get(k)) for k in cred_keys)
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


def _resolve_tool_specs(
    tool_config: Any,
) -> List[Dict[str, Any]]:
    """Convert a template's ``tools`` config into OpenAI-format function specs.

    The template TOML stores tools as a list of string names (e.g.
    ``["file_read", "shell_exec"]``). Engines expect OpenAI-shaped dicts:
    ``{"type": "function", "function": {"name, description, parameters"}}``.

    Special handling:
      * Dict entries pass through as-is (allows advanced configs to
        supply fully-formed specs).
      * ``browser`` is a synthetic display-only meta-tool that expands
        to the 6 real browser sub-tools (browser_navigate, click, …).
      * Channel names (``slack``, ``gmail``, …) come from the
        ``ChannelRegistry`` and are not directly callable by the LLM —
        they're destinations for ``channel_send``. Silently skip them.
      * Unknown tool names are dropped with a warning.
    """
    if not tool_config:
        return []

    from openjarvis.core.registry import ChannelRegistry, ToolRegistry

    _ensure_registries_populated()

    def _spec_dict_for(name: str) -> Optional[Dict[str, Any]]:
        try:
            spec = ToolRegistry.get(name)().spec
        except Exception as exc:
            logger.warning(
                "Could not build spec for tool '%s' (%s) — dropping",
                name,
                exc,
            )
            return None
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }

    resolved: List[Dict[str, Any]] = []
    seen: set = set()

    for entry in tool_config:
        if isinstance(entry, dict):
            resolved.append(entry)
            continue
        if not isinstance(entry, str):
            continue

        # Expand the synthetic "browser" meta-tool into its sub-tools.
        if entry == "browser":
            for sub in _BROWSER_SUB_TOOLS:
                if sub in seen or not ToolRegistry.contains(sub):
                    continue
                spec_dict = _spec_dict_for(sub)
                if spec_dict:
                    resolved.append(spec_dict)
                    seen.add(sub)
            continue

        # Channels (slack, gmail, …) live in ChannelRegistry and aren't
        # callable by the LLM. Skip silently — the agent talks to them
        # through the `channel_send` tool with a `channel` argument.
        if ChannelRegistry.contains(entry):
            continue

        if not ToolRegistry.contains(entry):
            logger.warning(
                "Tool '%s' referenced in agent config but not in ToolRegistry",
                entry,
            )
            continue

        if entry in seen:
            continue
        spec_dict = _spec_dict_for(entry)
        if spec_dict:
            resolved.append(spec_dict)
            seen.add(entry)

    return resolved


def _build_deep_research_tools(
    engine: Any,
    model: str,
    knowledge_db_path: str = "",
) -> list:
    """Build the 4 DeepResearch tools from a KnowledgeStore.

    Returns an empty list if the knowledge DB does not exist.
    """
    from pathlib import Path

    if not knowledge_db_path:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR

        knowledge_db_path = str(DEFAULT_CONFIG_DIR / "knowledge.db")

    if not Path(knowledge_db_path).exists():
        return []

    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    store = KnowledgeStore(knowledge_db_path)
    retriever = TwoStageRetriever(store)
    return [
        KnowledgeSearchTool(retriever=retriever),
        KnowledgeSQLTool(store=store),
        ScanChunksTool(store=store, engine=engine, model=model),
        ThinkTool(),
    ]


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
    cached = getattr(app_state, "_mcp_tools_cache", None)
    if cached is not None:
        return cached

    import json as _json

    from openjarvis.core.config import load_config

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

    # Keep clients alive so transports persist for tool calls at runtime
    mcp_clients: list = getattr(app_state, "_mcp_clients", [])

    try:
        server_list = _json.loads(app_config.tools.mcp.servers)
    except (_json.JSONDecodeError, TypeError) as exc:
        logger.warning("Failed to parse MCP server config: %s", exc)
        return openai_tools, adapters_by_name

    if not isinstance(server_list, list):
        return openai_tools, adapters_by_name

    for server_cfg in server_list:
        cfg = _json.loads(server_cfg) if isinstance(server_cfg, str) else server_cfg
        name = cfg.get("name", "<unnamed>")
        url = cfg.get("url")
        command = cfg.get("command", "")
        args = cfg.get("args", [])

        try:
            if url:
                transport = StreamableHTTPTransport(url=url)
            elif command:
                transport = StdioTransport(command=[command] + args)
            else:
                logger.warning(
                    "MCP server '%s' has neither 'url' nor 'command' — skipping",
                    name,
                )
                continue

            client = MCPClient(transport)
            client.initialize()
            mcp_clients.append(client)

            provider = MCPToolProvider(client)
            discovered = provider.discover()

            # Per-server tool filtering
            include_tools = set(cfg.get("include_tools", []))
            exclude_tools = set(cfg.get("exclude_tools", []))
            if include_tools:
                discovered = [t for t in discovered if t.spec.name in include_tools]
            if exclude_tools:
                discovered = [t for t in discovered if t.spec.name not in exclude_tools]

            for adapter in discovered:
                spec = adapter.spec
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

            logger.info(
                "Discovered %d MCP tools from server '%s'",
                len(discovered),
                name,
            )
        except Exception as exc:
            logger.warning(
                "Failed to discover MCP tools from '%s': %s",
                name,
                exc,
            )

    app_state._mcp_clients = mcp_clients
    if openai_tools:
        app_state._mcp_tools_cache = (openai_tools, adapters_by_name)
    return openai_tools, adapters_by_name


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

    from openjarvis.core.types import Message, Role

    agent_id = agent_record["id"]
    config = agent_record.get("config", {})
    model = config.get("model", getattr(engine, "_model", ""))
    system_prompt = config.get("system_prompt")
    temperature = config.get("temperature", 0.7)
    max_tokens = config.get("max_tokens", 1024)
    max_turns = config.get("max_turns", 10)

    # Build conversation messages from history + current input
    llm_messages: List[Message] = []
    if system_prompt:
        llm_messages.append(Message(role=Role.SYSTEM, content=system_prompt))

    # Resolve agent type and class for DeepResearch tool wiring
    agent_type = agent_record.get("agent_type", "")
    if agent_type == "deep_research":
        dr_tools = _build_deep_research_tools(
            engine=engine,
            model=model,
        )
        # Store on app_state so streaming loop can access them
        if app_state is not None and dr_tools:
            app_state._dr_tools = dr_tools

    # Load prior conversation context (DESC order, reverse for chronological)
    history = manager.list_messages(agent_id, limit=50)
    for m in reversed(history):
        if m["id"] == message_id:
            continue
        if m["direction"] == "user_to_agent":
            llm_messages.append(Message(role=Role.USER, content=m["content"]))
        elif m["direction"] == "agent_to_user":
            llm_messages.append(Message(role=Role.ASSISTANT, content=m["content"]))

    # Append the current user message
    llm_messages.append(Message(role=Role.USER, content=user_content))

    # Mark the user message as delivered
    manager.mark_message_delivered(message_id)

    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    # For deep_research agents: run the full agent loop, not raw streaming
    if agent_type == "deep_research" and app_state is not None:
        dr_tools = getattr(app_state, "_dr_tools", None)
        if dr_tools:

            async def generate_deep_research():
                """Run DeepResearchAgent in thread, stream progress + result."""
                import asyncio
                import queue
                import threading
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

                thread = threading.Thread(target=_run_agent, daemon=True)
                thread.start()

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

    # Build extra kwargs for stream_full (e.g. tools from config).
    # Template stores tool names as strings; convert to OpenAI function specs
    # so the engine can actually bind them to the model.
    stream_kwargs: Dict[str, Any] = {}
    resolved_tools = _resolve_tool_specs(config.get("tools"))
    if resolved_tools:
        stream_kwargs["tools"] = resolved_tools

    # Discover MCP tools and merge into stream_kwargs
    mcp_adapters: Dict[str, Any] = {}
    if app_state is not None:
        try:
            mcp_openai_tools, mcp_adapters = _get_mcp_tools(app_state)
            if mcp_openai_tools:
                existing_tools = stream_kwargs.get("tools", [])
                stream_kwargs["tools"] = existing_tools + mcp_openai_tools
                logger.info(
                    "Added %d MCP tools to streaming request",
                    len(mcp_openai_tools),
                )
        except Exception as exc:
            logger.warning(
                "Failed to get MCP tools for streaming: %s", exc, exc_info=True
            )

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
                        # Try MCP adapter first (external tools)
                        mcp_adapter = mcp_adapters.get(tool_name)
                        if mcp_adapter is not None:
                            try:
                                parsed_args = json.loads(tool_args) if tool_args else {}
                            except (json.JSONDecodeError, TypeError):
                                parsed_args = {}
                            result = mcp_adapter.execute(**parsed_args)
                            tool_result_content = result.content
                        else:
                            # Try to use ToolExecutor if tools are configured
                            from openjarvis.core.registry import ToolRegistry
                            from openjarvis.tools._stubs import (
                                ToolCall as StubToolCall,
                            )
                            from openjarvis.tools._stubs import (
                                ToolExecutor,
                            )

                            tool_cls = ToolRegistry.get(tool_name)
                            if tool_cls is not None:
                                tool_instance = tool_cls()
                                # Tools the user explicitly added to this
                                # agent's toolkit are considered pre-approved —
                                # selecting them in the wizard is the
                                # confirmation. Without this, tools that have
                                # `requires_confirmation=True` (shell_exec,
                                # apply_patch) would fail with "requires
                                # confirmation but no callback available" on
                                # every call.
                                executor = ToolExecutor(
                                    tools=[tool_instance],
                                    bus=bus,
                                    interactive=True,
                                    confirm_callback=lambda _prompt: True,
                                )
                                result = executor.execute(
                                    StubToolCall(
                                        id=tc["id"],
                                        name=tool_name,
                                        arguments=tool_args,
                                    ),
                                )
                                tool_result_content = result.content
                            else:
                                logger.warning(
                                    "Tool '%s' not found in registry or MCP adapters",
                                    tool_name,
                                )
                        tool_succeeded = True
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

    from starlette.background import BackgroundTask

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        background=BackgroundTask(_persist_final),
    )


def create_agent_manager_router(
    manager: AgentManager,
) -> Tuple[APIRouter, APIRouter, APIRouter, APIRouter]:
    """Create FastAPI routers with agent management endpoints.

    Returns a 4-tuple: (agents_router, templates_router, global_router, tools_router).
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
        import threading

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
        server_engine = getattr(request.app.state, "engine", None)
        server_model = getattr(request.app.state, "model", "")
        server_config = getattr(request.app.state, "config", None)

        def _run_tick():
            try:
                from openjarvis.agents.executor import AgentExecutor
                from openjarvis.core.events import get_event_bus

                _ts = getattr(request.app.state, "trace_store", None)
                executor = AgentExecutor(
                    manager=manager,
                    event_bus=get_event_bus(),
                    trace_store=_ts,
                )
                system = _make_lightweight_system(
                    server_engine,
                    server_model,
                    server_config,
                )
                executor.set_system(system)
                executor.execute_tick(agent_id)
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

        threading.Thread(target=_run_tick, daemon=True).start()
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
                            from openjarvis.server.agent_manager_routes import (
                                _build_deep_research_tools,
                            )

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
                            from openjarvis.server.agent_manager_routes import (
                                _build_deep_research_tools as _bdr,
                            )

                            tools = _bdr(engine=engine, model="")
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
            import threading
            import time as _time

            from openjarvis.agents.executor import AgentExecutor
            from openjarvis.core.events import get_event_bus

            _srv_engine = getattr(request.app.state, "engine", None)
            _srv_model = getattr(request.app.state, "model", "")
            _srv_config = getattr(request.app.state, "config", None)

            def _immediate_tick():
                _start = _time.time()
                logger.info(
                    "Immediate tick starting for agent %s (model=%s)",
                    agent_id,
                    _srv_model,
                )
                try:
                    _ts2 = getattr(request.app.state, "trace_store", None)
                    executor = AgentExecutor(
                        manager=manager,
                        event_bus=get_event_bus(),
                        trace_store=_ts2,
                    )
                    system = _make_lightweight_system(
                        _srv_engine,
                        _srv_model,
                        _srv_config,
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

            threading.Thread(
                target=_immediate_tick,
                daemon=True,
            ).start()
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
    def trigger_learning(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        from openjarvis.core.events import EventType, get_event_bus

        bus = get_event_bus()
        bus.publish(EventType.AGENT_LEARNING_STARTED, {"agent_id": agent_id})
        return {"status": "triggered"}

    # ── Traces ───────────────────────────────────────────────

    @agents_router.get("/{agent_id}/traces")
    def list_traces(agent_id: str, limit: int = 20):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        try:
            from openjarvis.core.config import load_config
            from openjarvis.traces.store import TraceStore

            config = load_config()
            store = TraceStore(config.traces.db_path or "~/.openjarvis/traces.db")
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
            from openjarvis.traces.store import TraceStore

            config = load_config()
            store = TraceStore(config.traces.db_path or "~/.openjarvis/traces.db")
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
            resp = httpx.get(
                "https://api.sendblue.co/api/lines",
                headers={
                    "sb-api-key-id": api_key_id,
                    "sb-api-secret-key": api_secret_key,
                },
                timeout=15.0,
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
                num = (
                    line.get("number")
                    or line.get("phone_number")
                    or line.get("from_number")
                    or (line if isinstance(line, str) else "")
                )
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
            resp = httpx.post(
                "https://api.sendblue.co/api/account/webhooks",
                headers={
                    "sb-api-key-id": api_key_id,
                    "sb-api-secret-key": api_secret_key,
                    "Content-Type": "application/json",
                },
                json={
                    "receive": webhook_url,
                },
                timeout=15.0,
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

            resp = httpx.post(
                "https://api.sendblue.co/api/send-message",
                headers={
                    "sb-api-key-id": api_key_id,
                    "sb-api-secret-key": api_secret_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15.0,
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
