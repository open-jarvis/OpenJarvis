"""Operator type definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class OperatorManifest:
    """Manifest describing a persistent autonomous operator."""

    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    # Agent config
    tools: List[str] = field(default_factory=list)
    system_prompt: str = ""
    system_prompt_path: str = ""
    max_turns: int = 20
    temperature: float = 0.3
    # Schedule (time-based)
    schedule_type: str = "interval"
    schedule_value: str = "300"
    # Event-driven triggers (list of raw config dicts, one per trigger)
    # Each dict must have a ``type`` key:
    #   "file"          -- watch filesystem path for changes
    #   "system_metric" -- fire when CPU/memory/disk crosses a threshold
    #   "http_poll"     -- fire when a URL's content changes
    #   "bus_event"     -- fire when an EventBus event matches
    event_triggers: List[Dict[str, Any]] = field(default_factory=list)
    # Monitoring
    metrics: List[str] = field(default_factory=list)
    # Security
    required_capabilities: List[str] = field(default_factory=list)
    # Extra
    settings: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = ["OperatorManifest"]
