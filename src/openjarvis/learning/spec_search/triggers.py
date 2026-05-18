"""Trigger types for the spec-search subsystem.

A trigger is what kicks off a learning session. Four trigger types exist,
all funneling into ``SpecSearchOrchestrator.run(trigger)``. The trigger
object is stored on the ``LearningSession`` for queryability.

See spec §3.3.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from openjarvis.learning.spec_search.models import TriggerKind


@dataclass
class OnDemandTrigger:
    """Caller invoked ``SpecSearchOrchestrator.run(trigger)`` directly."""

    kind: TriggerKind = TriggerKind.ON_DEMAND
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserFlagTrigger:
    """User flagged a specific trace for improvement."""

    trace_id: str = ""
    kind: TriggerKind = TriggerKind.USER_FLAG

    @property
    def metadata(self) -> dict[str, Any]:
        return {"trace_id": self.trace_id}


@dataclass
class ScheduledTrigger:
    """Cron-based scheduled trigger."""

    cron: str = "0 3 * * *"
    new_trace_count: int = 0
    kind: TriggerKind = TriggerKind.SCHEDULED

    @property
    def metadata(self) -> dict[str, Any]:
        return {"cron": self.cron, "new_trace_count": self.new_trace_count}


@dataclass
class ClusterTrigger:
    """Fired when a failure cluster exceeds a threshold."""

    cluster_description: str = ""
    trace_ids: list[str] = field(default_factory=list)
    failure_rate: float = 0.0
    kind: TriggerKind = TriggerKind.CLUSTER

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "cluster_description": self.cluster_description,
            "trace_ids": self.trace_ids,
            "failure_rate": self.failure_rate,
        }
