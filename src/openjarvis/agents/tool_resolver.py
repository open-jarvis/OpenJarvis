"""Canonical managed-agent tool resolution.

Managed agents can run through streaming HTTP, immediate/scheduled ticks, or
the persistent-agent CLI.  Those paths must bind the same live tool instances:
agent-type grants first, then configured native tools, then MCP adapters.
"""

from __future__ import annotations

import importlib
import logging
import sys
import weakref
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

BROWSER_SUB_TOOLS = (
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "browser_extract",
    "browser_axtree",
)

_MEMORY_TOOLS = frozenset(
    {"retrieval", "memory_store", "memory_search", "memory_index", "memory_retrieve"}
)
_CHANNEL_TOOLS = frozenset({"channel_send", "channel_list", "channel_status"})


class _SpecOverrideTool:
    """Delegate execution while exposing an agent-configured OpenAI schema."""

    def __init__(self, wrapped: Any, advertised_spec: dict[str, Any]) -> None:
        self._wrapped = wrapped
        self._advertised_spec = advertised_spec

    @property
    def spec(self) -> Any:
        base = self._wrapped.spec
        function = self._advertised_spec.get("function", {})
        return replace(
            base,
            name=function.get("name", base.name),
            description=function.get("description", base.description),
            parameters=function.get("parameters", base.parameters),
        )

    def execute(self, **params: Any) -> Any:
        return self._wrapped.execute(**params)

    def to_openai_function(self) -> dict[str, Any]:
        return self._advertised_spec

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def _tool_name(tool: Any) -> str:
    try:
        return str(tool.spec.name)
    except Exception:
        return ""


def _spec_name(spec: Mapping[str, Any]) -> str:
    function = spec.get("function")
    if not isinstance(function, Mapping):
        return ""
    name = function.get("name")
    return str(name) if name else ""


def _openai_spec(tool: Any) -> dict[str, Any]:
    to_openai_function = getattr(tool, "to_openai_function", None)
    if callable(to_openai_function):
        try:
            advertised = to_openai_function()
        except Exception:
            logger.debug(
                "Failed to build advertised schema for tool %r; falling back "
                "to its ToolSpec",
                _tool_name(tool),
                exc_info=True,
            )
        else:
            if isinstance(advertised, Mapping) and _spec_name(advertised):
                return dict(advertised)
            logger.debug(
                "Tool %r returned an invalid advertised schema; falling back "
                "to its ToolSpec",
                _tool_name(tool),
            )

    spec = tool.spec
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _close_resources(resources: tuple[Any, ...]) -> None:
    for resource in reversed(resources):
        close = getattr(resource, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.debug("Failed to close resolved tool resource", exc_info=True)


@dataclass
class ResolvedAgentTools:
    """One resolved toolkit, with views for agent loops and raw streaming."""

    instances: list[Any] = field(default_factory=list)
    extra_specs: list[dict[str, Any]] = field(default_factory=list)
    advertised_specs: list[dict[str, Any]] = field(default_factory=list)
    mcp_clients: list[Any] = field(default_factory=list)
    owned_resources: list[Any] = field(default_factory=list, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _finalizer: weakref.finalize = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # This fallback covers exceptions anywhere after resolution, including
        # before an executor/response installs its normal explicit cleanup.
        self._finalizer = weakref.finalize(
            self,
            _close_resources,
            tuple(self.owned_resources),
        )

    @property
    def by_name(self) -> dict[str, Any]:
        return {name: tool for tool in self.instances if (name := _tool_name(tool))}

    @property
    def openai_specs(self) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        seen: set[str] = set()
        advertised = self.advertised_specs
        if not advertised:
            advertised = [*map(_openai_spec, self.instances), *self.extra_specs]
        for spec in advertised:
            name = _spec_name(spec)
            if name and name in seen:
                continue
            specs.append(spec)
            if name:
                seen.add(name)
        return specs

    def close(self) -> None:
        """Close request-local resources without touching shared MCP clients."""

        if self._closed:
            return
        self._closed = True
        self._finalizer()

    def __enter__(self) -> ResolvedAgentTools:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def ensure_registries_populated() -> None:
    """Populate tool/channel registries, including after tests clear them."""

    from openjarvis.core.registry import ChannelRegistry, ToolRegistry

    try:
        import openjarvis.channels  # noqa: F401
    except Exception:
        pass

    try:
        import openjarvis.tools  # noqa: F401
    except Exception:
        pass

    browser_modules = ("openjarvis.tools.browser", "openjarvis.tools.browser_axtree")
    for module_name in browser_modules:
        try:
            importlib.import_module(module_name)
        except Exception:
            pass

    if not ChannelRegistry.keys():
        for module_name in list(sys.modules):
            if module_name.startswith(
                "openjarvis.channels."
            ) and not module_name.endswith("_stubs"):
                try:
                    importlib.reload(sys.modules[module_name])
                except Exception:
                    pass

    if not ToolRegistry.keys():
        for module_name in list(sys.modules):
            if (
                module_name.startswith("openjarvis.tools.")
                and not module_name.endswith("_stubs")
                and not module_name.endswith("agent_tools")
            ):
                try:
                    importlib.reload(sys.modules[module_name])
                except Exception:
                    pass

    if not any(ToolRegistry.contains(name) for name in BROWSER_SUB_TOOLS):
        for module_name in browser_modules:
            module = sys.modules.get(module_name)
            if module is not None:
                try:
                    importlib.reload(module)
                except Exception:
                    pass


def instantiate_registered_tool(
    tool_cls: Any,
    name: str,
    *,
    engine: Any,
    model: str,
    memory_backend: Any = None,
    channel_backend: Any = None,
) -> Any:
    """Instantiate a registry tool with its runtime dependencies."""

    if name in _MEMORY_TOOLS:
        if memory_backend is None:
            logger.warning(
                "Memory tool %r instantiated without a backend — calls will "
                "return no results.",
                name,
            )
        return tool_cls(backend=memory_backend)
    if name in _CHANNEL_TOOLS:
        if channel_backend is None:
            logger.warning(
                "Channel tool %r instantiated without a channel — calls will "
                "fail with 'No channel backend configured'.",
                name,
            )
        return tool_cls(channel=channel_backend)
    if name == "llm":
        return tool_cls(engine=engine, model=model)
    return tool_cls()


def build_deep_research_tools(
    engine: Any,
    model: str,
    knowledge_db_path: str | Path | None = None,
) -> list[Any]:
    """Construct the live knowledge tools granted to ``deep_research``."""

    if not knowledge_db_path:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR

        knowledge_db_path = DEFAULT_CONFIG_DIR / "knowledge.db"

    path = Path(knowledge_db_path)
    if not path.exists():
        return []

    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    store = KnowledgeStore(str(path))
    try:
        retriever = TwoStageRetriever(store)
        return [
            KnowledgeSearchTool(retriever=retriever),
            KnowledgeSQLTool(store=store),
            ScanChunksTool(store=store, engine=engine, model=model),
            ThinkTool(),
        ]
    except Exception:
        store.close()
        raise


def _normalized_tool_config(tool_config: Any) -> list[Any]:
    if not tool_config:
        return []
    if isinstance(tool_config, str):
        return [part.strip() for part in tool_config.split(",") if part.strip()]
    if isinstance(tool_config, Mapping):
        return [dict(tool_config)]
    try:
        return list(tool_config)
    except TypeError:
        return []


def resolve_agent_tools(
    agent_record: Mapping[str, Any],
    *,
    engine: Any,
    model: str,
    memory_backend: Any = None,
    channel_backend: Any = None,
    mcp_tools: Iterable[Any] = (),
    mcp_clients: Iterable[Any] = (),
    knowledge_db_path: str | Path | None = None,
) -> ResolvedAgentTools:
    """Resolve the effective live toolkit for a managed agent.

    Resolution is stable and first-wins: agent-type grants take precedence
    over configured registry tools, which take precedence over MCP adapters.
    ``config["mcp_tools"] = false`` excludes MCP adapters from this agent;
    process-wide runtimes may still own connections used by other agents.
    """

    ensure_registries_populated()
    from openjarvis.core.registry import ChannelRegistry, ToolRegistry

    config = agent_record.get("config") or {}
    if not isinstance(config, Mapping):
        config = {}

    instances: list[Any] = []
    extra_specs: list[dict[str, Any]] = []
    advertised_specs: list[dict[str, Any]] = []
    owned_resources: list[Any] = []
    seen: set[str] = set()

    def add_instance(
        tool: Any,
        *,
        advertised_spec: dict[str, Any] | None = None,
    ) -> None:
        name = _tool_name(tool)
        if not name or name in seen:
            return
        instances.append(tool)
        advertised_specs.append(advertised_spec or _openai_spec(tool))
        seen.add(name)

    use_mcp = config.get("mcp_tools", True) is not False
    mcp_tool_list = list(mcp_tools) if use_mcp else []
    mcp_by_name: dict[str, Any] = {}
    for tool in mcp_tool_list:
        name = _tool_name(tool)
        if name and name not in mcp_by_name:
            mcp_by_name[name] = tool

    if agent_record.get("agent_type") == "deep_research":
        granted_tools = build_deep_research_tools(
            engine=engine,
            model=model,
            knowledge_db_path=knowledge_db_path,
        )
        owned_ids: set[int] = set()
        for tool in granted_tools:
            resource = getattr(tool, "_store", None)
            if (
                resource is not None
                and callable(getattr(resource, "close", None))
                and id(resource) not in owned_ids
            ):
                owned_resources.append(resource)
                owned_ids.add(id(resource))
            add_instance(tool)

    for entry in _normalized_tool_config(config.get("tools")):
        if isinstance(entry, Mapping):
            raw_spec = entry if isinstance(entry, dict) else dict(entry)
            name = _spec_name(raw_spec)
            if name and name in seen:
                continue

            backing_tool = None
            if name and not ChannelRegistry.contains(name):
                if ToolRegistry.contains(name):
                    try:
                        backing_tool = instantiate_registered_tool(
                            ToolRegistry.get(name),
                            name,
                            engine=engine,
                            model=model,
                            memory_backend=memory_backend,
                            channel_backend=channel_backend,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Could not instantiate tool '%s' (%s) — "
                            "advertising its custom spec without execution",
                            name,
                            exc,
                        )
                elif name in mcp_by_name:
                    backing_tool = mcp_by_name[name]

            if backing_tool is not None:
                add_instance(
                    _SpecOverrideTool(backing_tool, raw_spec),
                    advertised_spec=raw_spec,
                )
            else:
                logger.warning(
                    "Custom tool spec '%s' has no registered or MCP execution "
                    "backend — dropping",
                    name or "<unnamed>",
                )
            continue
        if not isinstance(entry, str):
            continue

        names = BROWSER_SUB_TOOLS if entry == "browser" else (entry,)
        for name in names:
            if name in seen:
                continue
            if ChannelRegistry.contains(name):
                continue
            if not ToolRegistry.contains(name):
                logger.warning(
                    "Tool '%s' referenced in agent config but not in ToolRegistry",
                    name,
                )
                continue
            try:
                add_instance(
                    instantiate_registered_tool(
                        ToolRegistry.get(name),
                        name,
                        engine=engine,
                        model=model,
                        memory_backend=memory_backend,
                        channel_backend=channel_backend,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Could not instantiate tool '%s' (%s) — dropping", name, exc
                )

    if use_mcp:
        for tool in mcp_tool_list:
            add_instance(tool)

    return ResolvedAgentTools(
        instances=instances,
        extra_specs=extra_specs,
        advertised_specs=advertised_specs,
        mcp_clients=list(mcp_clients) if use_mcp else [],
        owned_resources=owned_resources,
    )


def resolve_tool_specs(tool_config: Any) -> list[dict[str, Any]]:
    """Compatibility view for callers that only need configured specs."""

    specs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in _normalized_tool_config(tool_config):
        if isinstance(entry, dict):
            specs.append(entry)
            name = _spec_name(entry)
            if name:
                seen.add(name)
            continue
        resolved = resolve_agent_tools(
            {"config": {"tools": [entry]}},
            engine=None,
            model="",
        )
        for spec in resolved.openai_specs:
            name = _spec_name(spec)
            if name and name in seen:
                continue
            specs.append(spec)
            if name:
                seen.add(name)
    return specs


__all__ = [
    "BROWSER_SUB_TOOLS",
    "ResolvedAgentTools",
    "build_deep_research_tools",
    "ensure_registries_populated",
    "instantiate_registered_tool",
    "resolve_agent_tools",
    "resolve_tool_specs",
]
