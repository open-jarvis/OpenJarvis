"""Shared helpers for securing agent and direct tool execution paths."""

from __future__ import annotations

import inspect
import json
import uuid
from typing import Any, Dict, Iterable


def _accepts_kwarg(agent_cls: Any, name: str) -> bool:
    """Return whether ``agent_cls.__init__`` accepts *name*."""
    try:
        parameters = inspect.signature(agent_cls.__init__).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def agent_security_kwargs(
    agent_cls: Any,
    *,
    capability_policy: Any = None,
    rate_limiter: Any = None,
    agent_id: str = "",
) -> Dict[str, Any]:
    """Build supported tool-security kwargs for an agent constructor.

    Plain agents do not own a ToolExecutor, so passing tool-only security
    kwargs to them is both ineffective and constructor-breaking. Tool-capable
    agents receive only the kwargs their constructor explicitly supports (or
    accepts via ``**kwargs``); :func:`wire_agent_security` is the final backstop
    for custom tool agents that construct an executor without exposing those
    parameters.
    """
    if not (
        getattr(agent_cls, "accepts_tools", False)
        or getattr(agent_cls, "uses_direct_operations", False)
        or getattr(agent_cls, "required_capabilities", ())
    ):
        return {}

    values = {
        "capability_policy": capability_policy,
        "rate_limiter": rate_limiter,
        "agent_id": agent_id,
    }
    return {
        name: value
        for name, value in values.items()
        if value is not None and _accepts_kwarg(agent_cls, name)
    }


def wire_agent_security(
    agent: Any,
    *,
    bus: Any = None,
    capability_policy: Any = None,
    rate_limiter: Any = None,
    agent_id: str = "",
    overwrite: bool = True,
    synchronize_runtime_cache: bool = False,
) -> None:
    """Wire runtime security into an already-created agent and executor."""
    if agent is None:
        return
    if bus is not None:
        # The audit logger subscribes to this runtime bus. An executor left on
        # a stale/None bus can enforce policy but silently lose its audit trail.
        agent._bus = bus
    if capability_policy is not None and (
        overwrite or getattr(agent, "_capability_policy", None) is None
    ):
        agent._capability_policy = capability_policy
    if rate_limiter is not None and (
        overwrite or getattr(agent, "_rate_limiter", None) is None
    ):
        agent._rate_limiter = rate_limiter
    if agent_id and (overwrite or not getattr(agent, "_runtime_agent_id", "")):
        agent._runtime_agent_id = agent_id

    if synchronize_runtime_cache:
        # Some agents (notably RLM) cache construction-time primitives for
        # executors created lazily inside run(). A server factory wiring a
        # prebuilt agent must synchronize those caches with the effective
        # runtime values or the lazy executor silently falls back to the
        # original None/default identity. Preserve explicit per-agent policy
        # and limiter values selected above when overwrite=False.
        if bus is not None and hasattr(agent, "_runtime_bus"):
            agent._runtime_bus = bus
        if hasattr(agent, "_runtime_capability_policy"):
            agent._runtime_capability_policy = getattr(
                agent,
                "_capability_policy",
                capability_policy,
            )
        if hasattr(agent, "_runtime_rate_limiter"):
            agent._runtime_rate_limiter = getattr(
                agent,
                "_rate_limiter",
                rate_limiter,
            )
        if agent_id:
            agent._runtime_agent_id = agent_id

    executor = getattr(agent, "_executor", None)
    if executor is None:
        return
    if bus is not None:
        executor._bus = bus
    if capability_policy is not None and (
        overwrite or getattr(executor, "_capability_policy", None) is None
    ):
        executor._capability_policy = capability_policy
    if rate_limiter is not None and (
        overwrite or getattr(executor, "_rate_limiter", None) is None
    ):
        executor._rate_limiter = rate_limiter
    if agent_id and (
        overwrite or synchronize_runtime_cache or not getattr(executor, "_agent_id", "")
    ):
        # A prebuilt agent crossing a server/runtime boundary must use the
        # boundary identity for both its direct-operation cache and its
        # already-created ToolExecutor.  Otherwise a class-default identity
        # (for example ``orchestrator``) can consume grants intended for a
        # different principal even though the server labels the run with
        # ``agent_name``.
        executor._agent_id = agent_id


def execute_secured_tool(
    tool: Any,
    params: Dict[str, Any],
    *,
    bus: Any = None,
    capability_policy: Any = None,
    rate_limiter: Any = None,
    agent_id: str,
):
    """Run one direct operation through the canonical ToolExecutor gates."""
    from openjarvis.core.types import ToolCall
    from openjarvis.tools._stubs import ToolExecutor

    executor = ToolExecutor(
        [tool],
        bus=bus,
        capability_policy=capability_policy,
        rate_limiter=rate_limiter,
        agent_id=agent_id,
    )
    return executor.execute(
        ToolCall(
            id=f"direct-{uuid.uuid4().hex[:12]}",
            name=tool.spec.name,
            arguments=json.dumps(params),
        )
    )


def authorize_secured_operation(
    operation: str,
    required_capabilities: Iterable[str],
    *,
    bus: Any = None,
    capability_policy: Any = None,
    rate_limiter: Any = None,
    agent_id: str,
):
    """Authorize one non-``BaseTool`` operation through standard gates."""
    from openjarvis.core.types import ToolResult
    from openjarvis.tools._stubs import BaseTool, ToolSpec

    capabilities = list(dict.fromkeys(str(cap) for cap in required_capabilities))

    class _OperationGate(BaseTool):
        @property
        def spec(self) -> ToolSpec:
            return ToolSpec(
                name=operation,
                description="Authorize a direct agent runtime operation.",
                required_capabilities=capabilities,
            )

        def execute(self, **params: Any) -> ToolResult:
            return ToolResult(tool_name=operation, content="authorized")

    return execute_secured_tool(
        _OperationGate(),
        {},
        bus=bus,
        capability_policy=capability_policy,
        rate_limiter=rate_limiter,
        agent_id=agent_id,
    )


__all__ = [
    "agent_security_kwargs",
    "authorize_secured_operation",
    "execute_secured_tool",
    "wire_agent_security",
]
