"""Hook system for OpenJarvis — inspired by the Claude Agent SDK cookbook.

Provides lifecycle hooks around tool execution, generation, and agent
orchestration.  Hooks are registered globally and executed in priority
order.  The system also persists an audit trail so every tool call,
generation, and routing decision can be inspected later.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Protocol, Union

logger = logging.getLogger("openjarvis.hooks")

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class HookStage(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    PRE_GENERATE = "pre_generate"
    POST_GENERATE = "post_generate"
    PRE_AGENT_RUN = "pre_agent_run"
    POST_AGENT_RUN = "post_agent_run"
    ROUTING_DECISION = "routing_decision"


class HookResult:
    """Immutable result returned by a hook."""

    def __init__(
        self,
        *,
        allowed: bool = True,
        modified_payload: Optional[Any] = None,
        error: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        self.allowed = allowed
        self.modified_payload = modified_payload
        self.error = error
        self.metadata = metadata or {}

    @classmethod
    def allow(cls, payload: Optional[Any] = None, metadata: Optional[dict] = None):
        return cls(allowed=True, modified_payload=payload, metadata=metadata)

    @classmethod
    def deny(cls, error: str, metadata: Optional[dict] = None):
        return cls(allowed=False, error=error, metadata=metadata)


# Convenient alias
HR = HookResult

# Signature variants
SyncHook = Callable[..., HookResult]
AsyncHook = Callable[..., Coroutine[Any, Any, HookResult]]
AnyHook = Union[SyncHook, AsyncHook]


# ---------------------------------------------------------------------------
# Registration decorator / helper
# ---------------------------------------------------------------------------


def _ensure_async(fn: AnyHook) -> AsyncHook:
    """Wrap a sync function so it looks async."""
    if asyncio.iscoroutinefunction(fn):
        return fn

    @functools.wraps(fn)
    async def _wrapper(*args: Any, **kwargs: Any) -> HookResult:
        return fn(*args, **kwargs)

    return _wrapper


# ---------------------------------------------------------------------------
# HookRegistry
# ---------------------------------------------------------------------------


class HookRegistry:
    """Central registry for lifecycle hooks.

    Usage::

        @HookRegistry.on(HookStage.PRE_TOOL_USE)
        def validate_pool_size(tool_name, payload):
            if tool_name == "set_pool_size" and payload.get("size", 0) > 100:
                return HookResult.deny("Pool size exceeds maximum of 100")
            return HookResult.allow()
    """

    _hooks: dict[HookStage, List[tuple[int, str, AsyncHook]]] = {
        stage: [] for stage in HookStage
    }
    _lock = asyncio.Lock()

    @classmethod
    def on(
        cls,
        stage: HookStage,
        *,
        name: Optional[str] = None,
        priority: int = 50,
    ) -> Callable[[AnyHook], AnyHook]:
        """Decorator that registers *func* for *stage* with *priority*.

        Lower numbers run first.  The default priority is 50.
        """

        def decorator(func: AnyHook) -> AnyHook:
            hook_name = name or func.__name__
            cls.register(stage, hook_name, func, priority=priority)
            return func

        return decorator

    @classmethod
    def register(
        cls,
        stage: HookStage,
        name: str,
        func: AnyHook,
        *,
        priority: int = 50,
    ) -> None:
        """Register a hook function for a stage."""
        async_fn = _ensure_async(func)
        cls._hooks[stage].append((priority, name, async_fn))
        cls._hooks[stage].sort(key=lambda t: t[0])
        logger.debug("Registered hook %s for stage %s (prio=%d)", name, stage, priority)

    @classmethod
    def unregister(cls, stage: HookStage, name: str) -> bool:
        """Remove a named hook from a stage."""
        before = len(cls._hooks[stage])
        cls._hooks[stage] = [
            (p, n, f) for p, n, f in cls._hooks[stage] if n != name
        ]
        return len(cls._hooks[stage]) < before

    @classmethod
    async def run(
        cls,
        stage: HookStage,
        *,
        payload: Any,
        context: Optional[dict] = None,
    ) -> HookResult:
        """Execute all hooks for *stage* in priority order.

        If any hook denies, execution stops immediately and the denial
        result is returned.  Otherwise each hook may optionally modify
        the payload — modifications are chained (last writer wins).
        """
        ctx = context or {}
        current_payload = payload
        for prio, name, hook in cls._hooks[stage]:
            try:
                result = await hook(payload=current_payload, context=ctx)
                if not result.allowed:
                    logger.warning(
                        "Hook %s denied stage %s: %s",
                        name,
                        stage.value,
                        result.error,
                    )
                    return result
                if result.modified_payload is not None:
                    current_payload = result.modified_payload
            except Exception as exc:
                logger.exception("Hook %s crashed in stage %s", name, stage.value)
                return HookResult.deny(
                    error=f"Hook '{name}' crashed: {exc}",
                    metadata={"traceback": traceback.format_exc()},
                )
        return HookResult.allow(payload=current_payload)

    @classmethod
    def list_hooks(cls, stage: Optional[HookStage] = None) -> dict:
        """Return a dict of registered hooks for inspection."""
        if stage:
            return {stage.value: [(p, n) for p, n, _ in cls._hooks[stage]]}
        return {
            s.value: [(p, n) for p, n, _ in cls._hooks[s]]
            for s in HookStage
        }

    @classmethod
    def reset(cls) -> None:
        """Clear all registrations (mostly for tests)."""
        cls._hooks = {stage: [] for stage in HookStage}


# ---------------------------------------------------------------------------
# Audit Trail
# ---------------------------------------------------------------------------


@dataclass
class AuditEntry:
    """Single audit-trail record."""

    timestamp: float
    stage: str
    agent_id: str
    conversation_id: Optional[str]
    details: dict = field(default_factory=dict)
    allowed: bool = True
    error: Optional[str] = None


class AuditTrail:
    """In-memory ring-buffer audit trail with optional async callbacks.

    When *persist_path* is set, every entry is append-only written to a
    JSON-lines file so the trail survives process restarts.
    """

    def __init__(self, capacity: int = 10_000, persist_path: Optional[str] = None) -> None:
        self._entries: deque[AuditEntry] = deque(maxlen=capacity)
        self._callbacks: List[Callable[[AuditEntry], Any]] = []
        self._persist_path: Optional[str] = persist_path
        self._lock = threading.Lock()
        if persist_path:
            self._load_from_disk()

    def set_persist_path(self, path: str) -> None:
        """Enable persistence after construction (e.g. for the global singleton)."""
        with self._lock:
            self._persist_path = path
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    self._entries.append(AuditEntry(**data))
        except Exception:
            logger.exception("Failed to load audit trail from %s", self._persist_path)

    def _append_to_disk(self, entry: AuditEntry) -> None:
        if not self._persist_path:
            return
        try:
            with self._lock:
                with open(self._persist_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry.__dict__, default=str) + "\n")
        except Exception:
            logger.exception("Failed to append audit entry to %s", self._persist_path)

    def add(
        self,
        stage: str,
        agent_id: str,
        *,
        conversation_id: Optional[str] = None,
        details: Optional[dict] = None,
        allowed: bool = True,
        error: Optional[str] = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            timestamp=time.time(),
            stage=stage,
            agent_id=agent_id,
            conversation_id=conversation_id,
            details=details or {},
            allowed=allowed,
            error=error,
        )
        self._entries.append(entry)
        self._append_to_disk(entry)
        for cb in self._callbacks:
            try:
                cb(entry)
            except Exception:
                logger.exception("Audit callback failed")
        return entry

    def entries(
        self,
        *,
        agent_id: Optional[str] = None,
        stage: Optional[str] = None,
        limit: int = 100,
        since: Optional[float] = None,
    ) -> List[AuditEntry]:
        results = list(self._entries)
        if agent_id:
            results = [e for e in results if e.agent_id == agent_id]
        if stage:
            results = [e for e in results if e.stage == stage]
        if since:
            results = [e for e in results if e.timestamp >= since]
        return results[-limit:]

    def subscribe(self, callback: Callable[[AuditEntry], Any]) -> None:
        self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[AuditEntry], Any]) -> None:
        try:
            self._callbacks.remove(callback)
        except ValueError:
            pass

    def to_dicts(self, limit: int = 100) -> List[dict]:
        return [
            {
                "timestamp": e.timestamp,
                "stage": e.stage,
                "agent_id": e.agent_id,
                "conversation_id": e.conversation_id,
                "details": e.details,
                "allowed": e.allowed,
                "error": e.error,
            }
            for e in self.entries(limit=limit)
        ]


# Global singletons
global_audit_trail = AuditTrail()


# ---------------------------------------------------------------------------
# Built-in hooks (safety / compliance)
# ---------------------------------------------------------------------------


def register_default_hooks() -> None:
    """Register the built-in safety and compliance hooks."""

    # --- PreToolUse: block dangerous shell commands -------------------------
    @HookRegistry.on(HookStage.PRE_TOOL_USE, name="dangerous_command_filter", priority=10)
    def _block_dangerous_commands(payload, context):
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {})
        if tool_name in {"shell_exec", "bash", "execute"}:
            cmd = str(tool_input).lower()
            forbidden = ["rm -rf /", "mkfs", "dd if=/dev/zero", ":(){ :|:& };:"]
            for f in forbidden:
                if f in cmd:
                    return HookResult.deny(
                        f"Blocked dangerous command pattern: {f}",
                        metadata={"matched_pattern": f},
                    )
        return HookResult.allow()

    # --- PreToolUse: validate write-operation ranges ------------------------
    @HookRegistry.on(HookStage.PRE_TOOL_USE, name="write_range_validator", priority=20)
    def _validate_write_ranges(payload, context):
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {})
        if tool_name in {"set_pool_size", "scale_workers"}:
            size = tool_input.get("size", tool_input.get("count", 0))
            if size > 100 or size < 0:
                return HookResult.deny(
                    f"{tool_name} size {size} is outside allowed range 0-100",
                    metadata={"requested_size": size},
                )
        return HookResult.allow()

    # --- PostToolUse: audit log -------------------------------------------
    @HookRegistry.on(HookStage.POST_TOOL_USE, name="audit_logger", priority=99)
    def _audit_tool_use(payload, context):
        tool_name = payload.get("tool_name", "")
        agent_id = context.get("agent_id", "unknown")
        conv_id = context.get("conversation_id", "")
        global_audit_trail.add(
            stage="post_tool_use",
            agent_id=agent_id,
            conversation_id=conv_id,
            details={
                "tool_name": tool_name,
                "tool_input": payload.get("tool_input"),
                "tool_output_preview": str(payload.get("tool_output", ""))[:200],
            },
        )
        return HookResult.allow()

    # --- PostGenerate: audit log ------------------------------------------
    @HookRegistry.on(HookStage.POST_GENERATE, name="generation_audit_logger", priority=99)
    def _audit_generation(payload, context):
        agent_id = context.get("agent_id", "unknown")
        conv_id = context.get("conversation_id", "")
        global_audit_trail.add(
            stage="post_generate",
            agent_id=agent_id,
            conversation_id=conv_id,
            details={
                "model": payload.get("model"),
                "prompt_tokens": payload.get("usage", {}).get("prompt_tokens"),
                "completion_tokens": payload.get("usage", {}).get("completion_tokens"),
            },
        )
        return HookResult.allow()

    logger.info("Default hooks registered.")


def ensure_default_hooks() -> None:
    """Idempotent: register defaults only once."""
    if not getattr(ensure_default_hooks, "_done", False):
        register_default_hooks()
        ensure_default_hooks._done = True  # type: ignore[attr-defined]


__all__ = [
    "HookStage",
    "HookResult",
    "HookRegistry",
    "AuditTrail",
    "AuditEntry",
    "global_audit_trail",
    "register_default_hooks",
    "ensure_default_hooks",
]
