"""Resource awareness for NORA AI — memory, GPU, storage monitoring."""

from __future__ import annotations

import logging
import psutil
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SystemResources:
    """Snapshot of available system resources."""
    cpu_percent: float  # CPU utilization 0-100
    memory_available_gb: float
    memory_percent: float  # Memory utilization 0-100
    disk_available_gb: float
    disk_percent: float  # Disk utilization 0-100
    gpu_memory_available_gb: Optional[float] = None
    gpu_utilization_percent: Optional[float] = None


class ResourceMonitor:
    """Monitor system resources for NORA."""

    def __init__(self):
        self.low_memory_threshold_gb = 2.0
        self.low_disk_threshold_gb = 5.0
        self.high_cpu_threshold = 80.0

    def get_resources(self) -> SystemResources:
        """Get current system resource usage."""
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        cpu = psutil.cpu_percent(interval=0.1)
        
        return SystemResources(
            cpu_percent=cpu,
            memory_available_gb=mem.available / (1024**3),
            memory_percent=mem.percent,
            disk_available_gb=disk.free / (1024**3),
            disk_percent=disk.percent,
        )

    def is_memory_critical(self) -> bool:
        """Check if system memory is critically low."""
        resources = self.get_resources()
        return resources.memory_available_gb < self.low_memory_threshold_gb

    def is_disk_critical(self) -> bool:
        """Check if disk space is critically low."""
        resources = self.get_resources()
        return resources.disk_available_gb < self.low_disk_threshold_gb

    def get_recommended_model_size(self) -> str:
        """Get recommended model size based on available resources."""
        resources = self.get_resources()
        
        # Lightweight: <4GB RAM
        if resources.memory_available_gb < 4:
            return "lightweight"
        # Balanced: 4-16GB RAM
        elif resources.memory_available_gb < 16:
            return "balanced"
        # Powerful: >16GB RAM
        else:
            return "powerful"

    def get_status_message(self) -> str:
        """Get human-readable resource status."""
        resources = self.get_resources()
        return (
            f"Memory: {resources.memory_percent:.1f}% "
            f"({resources.memory_available_gb:.1f}GB available) | "
            f"Disk: {resources.disk_percent:.1f}% "
            f"({resources.disk_available_gb:.1f}GB available) | "
            f"CPU: {resources.cpu_percent:.1f}%"
        )


__all__ = ["ResourceMonitor", "SystemResources"]
