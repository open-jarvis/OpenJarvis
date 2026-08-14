"""Branding configuration for NORA AI — name, colors, logo, UI text."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, Any

from openjarvis.core.paths import get_config_dir


@dataclass(slots=True)
class ColorPalette:
    """Color scheme configuration."""

    primary: str = "#6366f1"  # Indigo
    secondary: str = "#ec4899"  # Pink
    accent: str = "#f59e0b"  # Amber
    success: str = "#10b981"  # Emerald
    danger: str = "#ef4444"  # Red
    warning: str = "#f97316"  # Orange
    neutral: str = "#64748b"  # Slate
    background: str = "#0f172a"  # Dark blue
    surface: str = "#1e293b"  # Slate 800
    text_primary: str = "#f1f5f9"  # Slate 100
    text_secondary: str = "#cbd5e1"  # Slate 300


@dataclass(slots=True)
class LogoConfig:
    """Logo configuration."""

    path: str = ""  # Path to logo image (relative to config dir)
    url: str = ""  # Remote URL for logo
    format: str = "png"  # png, svg, jpg
    size_px: int = 256


@dataclass(slots=True)
class UITextConfig:
    """Customizable UI text strings."""

    app_name: str = "NORA AI"
    tagline: str = "Intelligent AI Agent"
    welcome_message: str = "Hello! I'm NORA AI. How can I assist you?"
    thinking_indicator: str = "NORA is thinking..."
    ready_indicator: str = "NORA is ready"
    offline_indicator: str = "Running offline"
    online_indicator: str = "Connected online"
    permission_request_prefix: str = "I'd like to"
    error_message: str = "I encountered an issue"


@dataclass
class BrandingConfig:
    """Complete branding configuration for NORA AI."""

    name: str = "NORA AI"
    description: str = "Personal AI agent running on your device"
    version: str = "1.0.0"
    author: str = "User"
    
    colors: ColorPalette = field(default_factory=ColorPalette)
    logo: LogoConfig = field(default_factory=LogoConfig)
    ui_text: UITextConfig = field(default_factory=UITextConfig)
    
    # Metadata
    homepage: str = "https://github.com/Demola3223/OpenJarvis"
    documentation_url: str = "https://github.com/Demola3223/OpenJarvis"
    support_email: str = ""
    
    # Brand appearance in responses
    show_branding: bool = True  # Show logo/name in UI
    brand_prefix: bool = True  # Prepend app name to agent responses
    enable_analytics: bool = False  # Privacy-first default

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BrandingConfig:
        """Load from dictionary."""
        colors_data = data.pop("colors", {})
        logo_data = data.pop("logo", {})
        ui_text_data = data.pop("ui_text", {})
        
        return cls(
            **data,
            colors=ColorPalette(**colors_data),
            logo=LogoConfig(**logo_data),
            ui_text=UITextConfig(**ui_text_data),
        )


def load_branding(config_dir: Optional[Path] = None) -> BrandingConfig:
    """Load branding configuration from JSON file.
    
    Searches for `branding.json` in config directory.
    Falls back to defaults if not found.
    """
    if config_dir is None:
        config_dir = get_config_dir()
    
    branding_path = config_dir / "branding.json"
    
    if branding_path.exists():
        try:
            with open(branding_path, "r") as f:
                data = json.load(f)
            return BrandingConfig.from_dict(data)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Failed to load branding config: {e}. Using defaults.")
            return BrandingConfig()
    
    return BrandingConfig()


def save_branding(config: BrandingConfig, config_dir: Optional[Path] = None) -> Path:
    """Save branding configuration to JSON file."""
    if config_dir is None:
        config_dir = get_config_dir()
    
    config_dir.mkdir(parents=True, exist_ok=True)
    branding_path = config_dir / "branding.json"
    
    with open(branding_path, "w") as f:
        json.dump(config.to_dict(), f, indent=2)
    
    return branding_path


__all__ = [
    "BrandingConfig",
    "ColorPalette",
    "LogoConfig",
    "UITextConfig",
    "load_branding",
    "save_branding",
]
