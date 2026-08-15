"""Shared construction seam for registered OpenJarvis Agents.

One place that turns an ``AgentRegistry`` key plus a bag of system-owned
dependencies into a live agent. Callers pass everything they have; this
module forwards only what the target agent's ``__init__`` actually accepts.

Without this seam every caller has to guess the constructor shape, and the
usual guard -- ``try: cls(**kwargs) except TypeError: cls(engine, model)`` --
silently drops tools, bus and max_turns the moment one keyword does not fit.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from openjarvis.agents._stubs import BaseAgent
from openjarvis.core.registry import AgentRegistry


def resolve_agent_system_prompt(agent_config: Any) -> str | None:
    """Resolve the configured Agent system prompt.

    Precedence: non-empty inline ``agent.system_prompt``, then the UTF-8
    contents of ``agent.system_prompt_path``, then ``None``. A configured but
    unreadable path is a startup error -- falling back to generic behavior
    would silently drop the Agent's instructions.
    """
    inline = (getattr(agent_config, "system_prompt", "") or "").strip()
    if inline:
        return inline
    configured_path = (getattr(agent_config, "system_prompt_path", "") or "").strip()
    if not configured_path:
        return None
    path = Path(configured_path).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"agent.system_prompt_path is not readable: {path}"
        ) from exc


def construct_registered_agent(
    *,
    agent_name: str,
    engine: Any,
    model: str,
    tools: list[Any] | None = None,
    bus: Any = None,
    max_turns: int | None = None,
    capability_policy: Any = None,
    memory_backend: Any = None,
    session_store: Any = None,
    operator_id: str | None = None,
    system_prompt: str | None = None,
    parallel_tools: bool | None = None,
    extra_kwargs: dict[str, Any] | None = None,
) -> BaseAgent:
    """Construct a registered Agent with only the dependencies it accepts.

    Every keyword is optional from the agent's point of view: one that the
    target ``__init__`` does not declare is dropped rather than raising
    ``TypeError``. ``tools`` is additionally gated on ``accepts_tools`` so
    tool-less agents are never handed a tool list.
    """
    agent_cls = AgentRegistry.get(agent_name)

    shared_candidates: dict[str, Any] = {
        "bus": bus,
        "tools": tools,
        "max_turns": max_turns,
        "capability_policy": capability_policy,
        "memory_backend": memory_backend,
        "session_store": session_store,
        "operator_id": operator_id,
        "system_prompt": system_prompt,
        # False is meaningful here, so it survives the None filter below as an
        # explicit value rather than being treated as "not supplied".
        "parallel_tools": parallel_tools,
    }

    signature = inspect.signature(agent_cls.__init__)
    accepts_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )

    kwargs = {
        name: value
        for name, value in shared_candidates.items()
        if value is not None
        and name in signature.parameters
        and (name != "tools" or getattr(agent_cls, "accepts_tools", False))
    }
    kwargs.update(
        {
            name: value
            for name, value in (extra_kwargs or {}).items()
            if value is not None
            and (accepts_kwargs or name in signature.parameters)
            and (name != "tools" or getattr(agent_cls, "accepts_tools", False))
        }
    )

    return agent_cls(engine, model, **kwargs)


__all__ = ["construct_registered_agent", "resolve_agent_system_prompt"]
