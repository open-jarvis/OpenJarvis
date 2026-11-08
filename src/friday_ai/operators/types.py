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
    # Schedule
    schedule_type: str = "interval"
    schedule_value: str = "300"
    # Monitoring
    metrics: List[str] = field(default_factory=list)
    # Security
    required_capabilities: List[str] = field(default_factory=list)
    # Extra
    settings: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = ["OperatorManifest"]
