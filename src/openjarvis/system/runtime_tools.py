"""Shared factory for resolving runtime tools and skills.

``jarvis serve``, ``SystemBuilder`` and other entry points all need to:

1. Decide which tools the agent should expose (config.tools.enabled is the
   canonical source; ``config.agent.tools`` is the legacy fallback).
2. Instantiate those tools and inject dependencies (engine, model, memory,
   channel).
3. Optionally discover Skills and surface them as additional tools.

Centralising this in one place keeps the multi-entry-point picture coherent
so a tool enabled in config shows up identically whether you launch via
``jarvis ask``, ``jarvis chat``, ``jarvis serve``, or programmatically via
``SystemBuilder``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

# Hardcoded "safe defaults" used when the user supplies no tool list anywhere.
# Mirrors the historical behaviour of ``serve.py``.
DEFAULT_TOOL_NAMES = ("think", "calculator", "web_search")


def resolve_tool_names(
    config: Any,
    *,
    override: Optional[List[str] | str] = None,
) -> List[str]:
    """Decide which tool names should be active.

    Resolution order:

    1. ``override`` (explicit CLI arg, e.g. ``--tools calculator,think``).
    2. ``config.tools.enabled`` — the canonical config source.
    3. ``config.agent.tools`` — legacy fallback.
    4. :data:`DEFAULT_TOOL_NAMES`.
    """

    def _split(raw: Any) -> List[str]:
        if not raw:
            return []
        if isinstance(raw, list):
            return [s.strip() for s in raw if isinstance(s, str) and s.strip()]
        if isinstance(raw, str):
            return [s.strip() for s in raw.split(",") if s.strip()]
        return []

    for candidate in (override, getattr(config.tools, "enabled", None)):
        names = _split(candidate)
        if names:
            return names

    legacy = _split(getattr(config.agent, "tools", None))
    if legacy:
        return legacy

    return list(DEFAULT_TOOL_NAMES)


@dataclass(slots=True)
class RuntimeToolBundle:
    """Result of :func:`build_runtime_tools`."""

    tools: List[Any] = field(default_factory=list)
    skill_manager: Any = None
    skill_few_shot_examples: List[str] = field(default_factory=list)


def _instantiate(tool_cls, *, engine, model, memory_backend, channel_backend):
    """Instantiate a tool class with the right dependency injection."""
    from openjarvis.tools._stubs import BaseTool

    # Treat already-instantiated tools as-is so the same factory works for
    # both class-registered and instance-registered tools.
    if not isinstance(tool_cls, type):
        return tool_cls if isinstance(tool_cls, BaseTool) else None

    name = getattr(tool_cls, "tool_id", "") or tool_cls.__name__
    try:
        if name in {"retrieval", "memory_store", "memory_search",
                    "memory_index", "memory_retrieve"}:
            return tool_cls(backend=memory_backend)
        if name in {"channel_send", "channel_list", "channel_status"}:
            return tool_cls(channel=channel_backend)
        if name == "llm":
            return tool_cls(engine=engine, model=model)
        return tool_cls()
    except TypeError:
        # Last-ditch: construct with no args; better to skip silently than
        # to fail the whole boot because one tool needs different kwargs.
        try:
            return tool_cls()
        except Exception as exc:
            logger.warning("Tool %r failed to instantiate: %s", name, exc)
            return None


def build_runtime_tools(
    config: Any,
    *,
    bus: Any,
    engine: Any,
    model: str,
    memory_backend: Any = None,
    channel_backend: Any = None,
    capability_policy: Any = None,
    override_tool_names: Optional[List[str] | str] = None,
    include_skills: bool = True,
) -> RuntimeToolBundle:
    """Build the runtime tool set + optional skill manager.

    Reads config to decide tool names, instantiates them with the right
    dependencies, and (when ``include_skills``) discovers Skills from the
    configured directory and exposes them as additional tools.
    """
    import openjarvis.tools  # noqa: F401  trigger tool registration
    from openjarvis.core.registry import ToolRegistry

    bundle = RuntimeToolBundle()

    wanted = resolve_tool_names(config, override=override_tool_names)
    for name in wanted:
        if not ToolRegistry.contains(name):
            logger.debug("Skipping unregistered tool %r", name)
            continue
        tool_cls = ToolRegistry.get(name)
        inst = _instantiate(
            tool_cls,
            engine=engine,
            model=model,
            memory_backend=memory_backend,
            channel_backend=channel_backend,
        )
        if inst is not None:
            bundle.tools.append(inst)

    if include_skills and getattr(config.skills, "enabled", False):
        try:
            from openjarvis.skills.manager import SkillManager
            from openjarvis.tools._stubs import ToolExecutor

            sm = SkillManager(bus, capability_policy=capability_policy)
            search_paths = [Path(config.skills.skills_dir).expanduser()]
            workspace = Path("./skills")
            if workspace.exists():
                search_paths.insert(0, workspace)
            sm.discover(paths=search_paths)
            executor = ToolExecutor(bundle.tools, bus) if bundle.tools else None
            if executor is not None:
                sm.set_tool_executor(executor)
            bundle.tools.extend(sm.get_skill_tools(tool_executor=executor))
            bundle.skill_manager = sm
            bundle.skill_few_shot_examples = sm.get_few_shot_examples()
        except Exception as exc:
            logger.warning("Skill discovery failed: %s", exc)

    return bundle


__all__ = [
    "DEFAULT_TOOL_NAMES",
    "RuntimeToolBundle",
    "build_runtime_tools",
    "resolve_tool_names",
]
