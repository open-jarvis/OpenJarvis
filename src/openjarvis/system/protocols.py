"""Structural protocols for substituting fakes in place of JarvisSystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Protocol

if TYPE_CHECKING:
    from openjarvis.core.config import JarvisConfig
    from openjarvis.core.events import EventBus
    from openjarvis.engine._stubs import InferenceEngine
    from openjarvis.security.capabilities import CapabilityPolicy
    from openjarvis.sessions.session import SessionStore
    from openjarvis.tools._stubs import BaseTool
    from openjarvis.tools.storage._stubs import MemoryBackend
    from openjarvis.traces.collector import TraceCollector
    from openjarvis.traces.store import TraceStore


class OrchestratorDeps(Protocol):
    """Minimum surface of JarvisSystem that QueryOrchestrator depends on.

    Tests can satisfy this with a lightweight class — no need to construct
    the full JarvisSystem dataclass or materialize every subsystem.
    """

    config: JarvisConfig
    bus: EventBus
    engine: InferenceEngine
    engine_key: str
    model: str
    agent_name: str
    tools: List[BaseTool]
    memory_backend: Optional[MemoryBackend]
    capability_policy: Optional[CapabilityPolicy]
    session_store: Optional[SessionStore]
    trace_store: Optional[TraceStore]
    trace_collector: Optional[TraceCollector]  # written by _run_agent

    # Optional attribute (getattr with default) — declared for type clarity.
    _skill_few_shot_examples: Any
