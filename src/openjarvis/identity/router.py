"""Model Router for NORA AI — intelligent selection between local and cloud models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class RouterMode(str, Enum):
    """Router operating modes."""
    AUTO = "auto"          # Intelligent selection
    OFFLINE = "offline"    # Local only
    ONLINE = "online"      # Cloud preferred


@dataclass
class ModelRoute:
    """Selected model routing configuration."""
    model_id: str
    provider: str  # ollama, openai, anthropic, etc.
    is_local: bool
    is_fallback: bool = False
    reason: str = ""  # Why this model was selected


class ModelRouter:
    """Intelligent model selection for NORA AI."""

    def __init__(self, config):
        self.config = config
        self.mode = RouterMode.AUTO
        self.is_online = True
        self.preferred_local_model = "qwen3.5:7b"
        self.preferred_cloud_model = "gpt-4o-mini"

    def set_mode(self, mode: RouterMode) -> None:
        """Set routing mode."""
        self.mode = mode
        logger.info(f"Router mode set to: {mode.value}")

    def set_connectivity(self, is_online: bool) -> None:
        """Update network connectivity status."""
        self.is_online = is_online
        logger.info(f"Network status: {'ONLINE' if is_online else 'OFFLINE'}")

    def select_model(self, task_type: str = "general") -> ModelRoute:
        """Select best model for the task based on mode and connectivity.
        
        Parameters
        ----------
        task_type
            Type of task: general, coding, research, creative, analysis, blender
        
        Returns
        -------
        ModelRoute
            Selected model with routing information
        """
        if self.mode == RouterMode.OFFLINE:
            return self._select_local_model(task_type)
        elif self.mode == RouterMode.ONLINE:
            return self._select_cloud_model(task_type)
        else:  # AUTO
            if not self.is_online:
                logger.info("No internet connection. Falling back to local model.")
                return self._select_local_model(task_type)
            return self._select_auto(task_type)

    def _select_local_model(self, task_type: str) -> ModelRoute:
        """Select from available local models."""
        # Map task types to model preferences
        model_map = {
            "coding": "mistral-nemo",
            "research": "qwen3.5:7b",
            "creative": "neural-chat",
            "analysis": "qwen3.5:7b",
            "general": self.preferred_local_model,
        }
        model = model_map.get(task_type, self.preferred_local_model)
        return ModelRoute(
            model_id=model,
            provider="ollama",
            is_local=True,
            reason=f"Local model selected for {task_type} task",
        )

    def _select_cloud_model(self, task_type: str) -> ModelRoute:
        """Select from available cloud models."""
        model_map = {
            "coding": "gpt-4o",
            "research": "gpt-4o",
            "creative": "claude-3-opus-20250219",
            "analysis": "gpt-4o",
            "general": self.preferred_cloud_model,
        }
        model = model_map.get(task_type, self.preferred_cloud_model)
        provider = "openai" if model.startswith("gpt") else "anthropic"
        return ModelRoute(
            model_id=model,
            provider=provider,
            is_local=False,
            reason=f"Cloud model selected for {task_type} task",
        )

    def _select_auto(self, task_type: str) -> ModelRoute:
        """Intelligent selection based on task complexity and resource availability."""
        # Simple heuristic: complex tasks use cloud, simple use local
        complex_tasks = {"coding", "research", "creative", "analysis", "blender"}
        if task_type in complex_tasks:
            return self._select_cloud_model(task_type)
        else:
            return self._select_local_model(task_type)

    def get_status(self) -> dict:
        """Get current router status."""
        return {
            "mode": self.mode.value,
            "is_online": self.is_online,
            "preferred_local": self.preferred_local_model,
            "preferred_cloud": self.preferred_cloud_model,
        }


__all__ = ["ModelRouter", "RouterMode", "ModelRoute"]
