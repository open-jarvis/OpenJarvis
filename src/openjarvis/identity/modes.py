"""Operating modes for NORA AI — role-based agent configurations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List


class OperatingMode(str, Enum):
    """NORA's operating modes — each optimizes for a specific task type."""

    GENERAL = "general"  # Normal personal assistant
    DEVELOPER = "developer"  # Code, terminal, Git, debugging
    RESEARCH = "research"  # Web research, source comparison, analysis
    BUILDER = "builder"  # Create apps, websites, scripts, projects
    VOICE = "voice"  # Optimized for voice interaction
    CREATIVE = "creative"  # Creative writing, art, design
    ANALYST = "analyst"  # Data analysis, visualization
    BLENDER = "blender"  # 3D modeling and rendering
    OFFLINE = "offline"  # Pure local operation (no internet)


@dataclass(slots=True)
class ModeConfig:
    """Configuration for a specific operating mode."""

    mode: OperatingMode
    description: str
    recommended_model_size: str  # lightweight, balanced, powerful
    preferred_tools: List[str]
    system_prompt_suffix: str  # Appended to base system prompt
    default_temperature: float = 0.7
    default_max_tokens: int = 2048
    enable_web_access: bool = True
    enable_code_execution: bool = True
    enable_file_operations: bool = True


# Define all operating modes
OPERATING_MODES = {
    OperatingMode.GENERAL: ModeConfig(
        mode=OperatingMode.GENERAL,
        description="General-purpose personal assistant",
        recommended_model_size="balanced",
        preferred_tools=["web_search", "file_read", "think"],
        system_prompt_suffix="You are a general-purpose personal assistant. Provide helpful, accurate information and assistance with everyday tasks.",
    ),
    OperatingMode.DEVELOPER: ModeConfig(
        mode=OperatingMode.DEVELOPER,
        description="Development and coding mode",
        recommended_model_size="powerful",
        preferred_tools=[
            "code_interpreter",
            "terminal",
            "git",
            "github",
            "file_read",
            "file_write",
            "web_search",
        ],
        system_prompt_suffix="You are an expert developer. Help with coding, debugging, testing, and software development. Use terminal commands and code execution. Always test code before claiming it works.",
        default_max_tokens=4096,
    ),
    OperatingMode.RESEARCH: ModeConfig(
        mode=OperatingMode.RESEARCH,
        description="Web research and analysis mode",
        recommended_model_size="powerful",
        preferred_tools=["web_search", "browser", "file_read", "think"],
        system_prompt_suffix="You are a research assistant. Find current information, compare sources, and provide well-cited analysis. Always indicate source URLs.",
        enable_code_execution=False,
    ),
    OperatingMode.BUILDER: ModeConfig(
        mode=OperatingMode.BUILDER,
        description="Application and project building mode",
        recommended_model_size="powerful",
        preferred_tools=[
            "code_interpreter",
            "file_write",
            "terminal",
            "git",
            "web_search",
        ],
        system_prompt_suffix="You are a project architect. Design, scaffold, and build complete applications. Provide working, tested solutions. Organize code into proper project structures.",
        default_max_tokens=4096,
    ),
    OperatingMode.VOICE: ModeConfig(
        mode=OperatingMode.VOICE,
        description="Voice-optimized mode",
        recommended_model_size="balanced",
        preferred_tools=["web_search", "think"],
        system_prompt_suffix="You are optimized for voice interaction. Keep responses concise and natural. Avoid long lists. Speak conversationally.",
        default_max_tokens=1024,
    ),
    OperatingMode.CREATIVE: ModeConfig(
        mode=OperatingMode.CREATIVE,
        description="Creative writing and design mode",
        recommended_model_size="powerful",
        preferred_tools=["file_write", "think"],
        system_prompt_suffix="You are a creative collaborator. Help with writing, design, brainstorming, and artistic projects. Be imaginative and encouraging.",
        enable_code_execution=False,
        enable_web_access=False,
    ),
    OperatingMode.ANALYST: ModeConfig(
        mode=OperatingMode.ANALYST,
        description="Data analysis and visualization mode",
        recommended_model_size="powerful",
        preferred_tools=["code_interpreter", "file_read", "file_write"],
        system_prompt_suffix="You are a data analyst. Process, analyze, and visualize data. Write Python code for analysis. Explain findings clearly.",
        default_max_tokens=4096,
        enable_web_access=False,
    ),
    OperatingMode.BLENDER: ModeConfig(
        mode=OperatingMode.BLENDER,
        description="3D modeling and rendering mode",
        recommended_model_size="powerful",
        preferred_tools=["blender", "code_interpreter", "file_read", "file_write"],
        system_prompt_suffix="You are a 3D artist and Blender expert. Create scenes, models, materials, and animations. Use Blender's Python API for automation.",
        default_max_tokens=4096,
        enable_web_access=False,
    ),
    OperatingMode.OFFLINE: ModeConfig(
        mode=OperatingMode.OFFLINE,
        description="Offline-only mode (no internet)",
        recommended_model_size="lightweight",
        preferred_tools=["file_read", "terminal", "code_interpreter", "think"],
        system_prompt_suffix="You are running offline with no internet access. You cannot search the web or access online resources. Work with local information only.",
        enable_web_access=False,
    ),
}


def get_mode_config(mode: OperatingMode) -> ModeConfig:
    """Get configuration for a specific operating mode."""
    return OPERATING_MODES[mode]


def get_mode_system_prompt_suffix(mode: OperatingMode) -> str:
    """Get system prompt suffix for a mode."""
    return get_mode_config(mode).system_prompt_suffix


__all__ = [
    "OperatingMode",
    "ModeConfig",
    "OPERATING_MODES",
    "get_mode_config",
    "get_mode_system_prompt_suffix",
]
