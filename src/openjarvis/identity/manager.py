"""Identity Manager for NORA AI — unified interface for branding, personality, and operating modes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from openjarvis.identity.branding import BrandingConfig, load_branding, save_branding
from openjarvis.identity.personality import (
    PersonalityConfig,
    load_personality,
    save_personality,
    get_system_prompt,
)
from openjarvis.identity.modes import OperatingMode, get_mode_system_prompt_suffix
from openjarvis.core.paths import get_config_dir

logger = logging.getLogger(__name__)


class IdentityManager:
    """Manages NORA AI's complete identity: branding, personality, and modes."""

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        personality_name: str = "default",
    ):
        """Initialize the identity manager.
        
        Parameters
        ----------
        config_dir
            Configuration directory. Defaults to ~/.openjarvis/
        personality_name
            Which personality config to load (default, professional, casual, etc.)
        """
        self.config_dir = config_dir or get_config_dir()
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Load branding and personality
        self._branding = load_branding(self.config_dir)
        self._personality = load_personality(self.config_dir, personality_name)
        self._current_mode = OperatingMode.GENERAL
        
        logger.info(
            f"Loaded identity: {self._branding.name} ({self._personality.name})"
        )

    @property
    def branding(self) -> BrandingConfig:
        """Get current branding configuration."""
        return self._branding

    @property
    def personality(self) -> PersonalityConfig:
        """Get current personality configuration."""
        return self._personality

    @property
    def current_mode(self) -> OperatingMode:
        """Get current operating mode."""
        return self._current_mode

    def set_mode(self, mode: OperatingMode) -> None:
        """Switch to a different operating mode."""
        self._current_mode = mode
        logger.info(f"Switched to {mode.value} mode")

    def get_system_prompt(self, include_mode: bool = True) -> str:
        """Generate complete system prompt for NORA.
        
        Combines:
        1. Branding info
        2. Personality base prompt
        3. Operating mode suffix (if enabled)
        
        Parameters
        ----------
        include_mode
            Include the current operating mode's system prompt suffix
        """
        prompt = get_system_prompt(self._personality, self._branding.name)
        
        if include_mode:
            mode_suffix = get_mode_system_prompt_suffix(self._current_mode)
            prompt += f"\n\n# Operating Mode: {self._current_mode.value.upper()}\n{mode_suffix}"
        
        return prompt

    def update_branding(self, **updates) -> None:
        """Update branding configuration.
        
        Example:
            manager.update_branding(name="My AI", show_branding=True)
        """
        for key, value in updates.items():
            if hasattr(self._branding, key):
                setattr(self._branding, key, value)
        
        save_branding(self._branding, self.config_dir)
        logger.info("Branding updated and saved")

    def update_personality(self, **updates) -> None:
        """Update personality configuration.
        
        Example:
            manager.update_personality(
                name="NORA",
                communication={"tone": "casual"}
            )
        """
        for key, value in updates.items():
            if isinstance(value, dict) and hasattr(self._personality, key):
                # Nested update
                nested_obj = getattr(self._personality, key)
                for nested_key, nested_val in value.items():
                    if hasattr(nested_obj, nested_key):
                        setattr(nested_obj, nested_key, nested_val)
            elif hasattr(self._personality, key):
                setattr(self._personality, key, value)
        
        save_personality(self._personality, self.config_dir)
        logger.info("Personality updated and saved")

    def get_identity_summary(self) -> str:
        """Get a human-readable summary of current identity."""
        branding = self._branding
        personality = self._personality
        comm = personality.communication
        caps = personality.capabilities
        
        summary = f"""
╔════════════════════════════════════════════════════════════╗
║ NORA AI IDENTITY SUMMARY
╚════════════════════════════════════════════════════════════╝

📛 Branding:
  Name:        {branding.name}
  Description: {branding.description}
  Homepage:    {branding.homepage}

🧠 Personality:
  Name:        {personality.name}
  Role:        {personality.role}
  Tone:        {comm.tone}
  Verbosity:   {comm.verbosity}

⚙️ Capabilities:
  Code Execution:        {caps.can_execute_code}
  Web Access:            {caps.can_access_web}
  File Operations:       {caps.can_access_files}
  Terminal Access:       {caps.can_access_terminal}
  Application Control:   {caps.can_control_applications}

🎯 Current Mode:
  {self._current_mode.value.upper()}

🎨 Colors:
  Primary:   {branding.colors.primary}
  Secondary: {branding.colors.secondary}
  Accent:    {branding.colors.accent}
"""
        return summary

    def export_config(self) -> dict:
        """Export complete identity configuration as dictionary."""
        return {
            "branding": self._branding.to_dict(),
            "personality": self._personality.to_dict(),
            "current_mode": self._current_mode.value,
        }

    def __repr__(self) -> str:
        return (
            f"IdentityManager(branding={self._branding.name}, "
            f"personality={self._personality.name}, "
            f"mode={self._current_mode.value})"
        )


__all__ = ["IdentityManager"]
