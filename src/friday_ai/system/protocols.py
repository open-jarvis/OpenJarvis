"""Structural protocols for substituting fakes in place of FridaySystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Protocol

if TYPE_CHECKING:
    from friday_ai.core.config import FridayConfig
    from friday_ai.core.events import EventBus
    from friday_ai.engine._stubs import InferenceEngine
    from friday_ai.security.capabilities import CapabilityPolicy
    from friday_ai.sessions.session import SessionStore
    from friday_ai.tools._stubs import BaseTool
    from friday_ai.tools.storage._stubs import MemoryBackend
    from friday_ai.traces.collector import TraceCollector
    from friday_ai.traces.store import TraceStore


class OrchestratorDeps(Protocol):
    """Minimum surface of FridaySystem that QueryOrchestrator depends on.

    Tests can satisfy this with a lightweight class — no need to construct
    the full FridaySystem dataclass or materialize every subsystem.
    """

    config: FridayConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent_name: str
    tools: List[BaseTool]
    memory_backend: Optional[MemoryBackend]
    capability_policy: Optional[CapabilityPolicy]
    rate_limiter: Optional[Any]
    session_store: Optional[SessionStore]
    trace_store: Optional[TraceStore]
    trace_collector: Optional[TraceCollector]  # written by _run_agent

    # Optional attribute (getattr with default) — declared for type clarity.
    _skill_few_shot_examples: Any
