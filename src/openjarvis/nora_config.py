"""Enhanced configuration for NORA AI with identity and model routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class NoraIdentityConfig:
    """NORA AI identity configuration section."""

    # Branding
    app_name: str = "NORA AI"
    app_description: str = "Your Personal AI Assistant"
    enable_branding: bool = True
    show_mode_indicator: bool = True
    show_connectivity_indicator: bool = True
    
    # Personality
    default_personality: str = "default"
    available_personalities: str = "default,developer,research,creative,analyst,blender"
    
    # Model routing
    router_mode: str = "auto"  # auto, offline, online
    prefer_local_models: bool = True
    local_model_fallback: bool = True
    
    # Resource awareness
    enable_resource_monitoring: bool = True
    critical_memory_threshold_gb: float = 2.0
    critical_disk_threshold_gb: float = 5.0
    auto_downgrade_on_low_resources: bool = True
    
    # Voice
    enable_voice_mode: bool = True
    default_voice_model: str = "faster-whisper"
    
    # Debugging
    verbose_routing: bool = False
    log_model_selection: bool = True


# Add to JarvisConfig in src/openjarvis/core/config.py
# Simply add this field to the JarvisConfig dataclass:
# nora: NoraIdentityConfig = field(default_factory=NoraIdentityConfig)
