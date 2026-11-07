"""Bundle dataclasses that group cohesive subsystems of FridaySystem."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from friday_ai.agents._stubs import BaseAgent
    from friday_ai.agents.executor import AgentExecutor
    from friday_ai.agents.manager import AgentManager
    from friday_ai.agents.scheduler import AgentScheduler
    from friday_ai.scheduler.scheduler import TaskScheduler
    from friday_ai.scheduler.store import SchedulerStore
    from friday_ai.security.audit import AuditLogger
    from friday_ai.security.boundary import BoundaryGuard
    from friday_ai.security.capabilities import CapabilityPolicy
    from friday_ai.telemetry.gpu_monitor import GpuMonitor
    from friday_ai.telemetry.store import TelemetryStore
    from friday_ai.traces.collector import TraceCollector
    from friday_ai.traces.store import TraceStore


@dataclass
class SecurityContext:
    """Security policy, audit, and boundary enforcement."""

    capability_policy: Optional[CapabilityPolicy] = None
    audit_logger: Optional[AuditLogger] = None
    boundary_guard: Optional[BoundaryGuard] = None
    rate_limiter: Optional[Any] = None


@dataclass
class Observability:
    """Telemetry, traces, and hardware monitoring."""

    telemetry_store: Optional[TelemetryStore] = None
    trace_store: Optional[TraceStore] = None
    trace_collector: Optional[TraceCollector] = None
    gpu_monitor: Optional[GpuMonitor] = None


@dataclass
class AgentRuntime:
    """Active agent and agent lifecycle managers."""

    agent: Optional[BaseAgent] = None
    agent_name: str = ""
    manager: Optional[AgentManager] = None
    scheduler: Optional[AgentScheduler] = None
    executor: Optional[AgentExecutor] = None


@dataclass
class Scheduling:
    """Task scheduler and its persistent store."""

    store: Optional[SchedulerStore] = None
    runner: Optional[TaskScheduler] = None
