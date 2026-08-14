"""Personality configuration for NORA AI — communication style, behavior, capabilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Dict, List, Any

from openjarvis.core.paths import get_config_dir


@dataclass(slots=True)
class CommunicationStyle:
    """How NORA communicates with the user."""

    tone: str = "helpful"  # helpful, professional, casual, formal, friendly
    verbosity: str = "concise"  # terse, concise, detailed, verbose
    use_emojis: bool = False
    use_markdown: bool = True
    explain_reasoning: bool = True  # Show chain-of-thought
    use_examples: bool = True
    language: str = "en"  # ISO 639-1 language code


@dataclass(slots=True)
class Capabilities:
    """Declared capabilities and behavioral limits."""

    can_execute_code: bool = True
    can_access_web: bool = True
    can_access_files: bool = True
    can_access_terminal: bool = True
    can_control_applications: bool = True
    can_modify_system: bool = False
    can_delete_data: bool = False
    max_context_tokens: int = 8192
    max_tool_calls_per_turn: int = 10


@dataclass(slots=True)
class Goals:
    """Primary goals and values."""

    primary: str = "Be helpful and provide accurate information"
    secondary: List[str] = field(
        default_factory=lambda: [
            "Learn from interactions",
            "Respect user privacy",
            "Work efficiently",
        ]
    )
    avoid: List[str] = field(
        default_factory=lambda: [
            "Causing harm",
            "Violating privacy",
            "Providing false information",
        ]
    )


@dataclass(slots=True)
class Rules:
    """Behavioral rules and constraints."""

    never_share_system_prompt: bool = True
    never_log_passwords: bool = True
    never_expose_api_keys: bool = True
    always_ask_for_destructive_operations: bool = True
    always_verify_file_operations: bool = True
    require_permission_for_network_access: bool = False
    rate_limit_tool_calls: bool = True
    custom_rules: List[str] = field(default_factory=list)


@dataclass(slots=True)
class PreferencesConfig:
    """User preferences affecting NORA's behavior."""

    preferred_model_size: str = "balanced"  # lightweight, balanced, powerful
    prefer_local_models: bool = True
    explain_tool_usage: bool = True
    confirm_before_executing: bool = False
    auto_retry_on_failure: bool = True
    max_retries: int = 3


@dataclass
class PersonalityConfig:
    """Complete personality configuration for NORA AI."""

    name: str = "NORA"
    role: str = "Personal AI Assistant"
    description: str = "An intelligent, helpful personal AI agent"
    
    communication: CommunicationStyle = field(default_factory=CommunicationStyle)
    capabilities: Capabilities = field(default_factory=Capabilities)
    goals: Goals = field(default_factory=Goals)
    rules: Rules = field(default_factory=Rules)
    preferences: PreferencesConfig = field(default_factory=PreferencesConfig)
    
    # System behavior
    system_prompt_template: str = ""  # Can override default
    initial_greeting: str = "Hello! I'm NORA, your personal AI assistant. How can I help?"
    error_recovery_message: str = "I encountered an error. Let me try again."
    
    # Metadata
    created_at: str = ""
    last_modified: str = ""
    version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PersonalityConfig:
        """Load from dictionary."""
        communication_data = data.pop("communication", {})
        capabilities_data = data.pop("capabilities", {})
        goals_data = data.pop("goals", {})
        rules_data = data.pop("rules", {})
        preferences_data = data.pop("preferences", {})
        
        return cls(
            **data,
            communication=CommunicationStyle(**communication_data),
            capabilities=Capabilities(**capabilities_data),
            goals=Goals(**goals_data),
            rules=Rules(**rules_data),
            preferences=PreferencesConfig(**preferences_data),
        )


def load_personality(
    config_dir: Optional[Path] = None,
    personality_name: str = "default",
) -> PersonalityConfig:
    """Load personality configuration from JSON file.
    
    Searches for `personalities/{name}.json` in config directory.
    Falls back to defaults if not found.
    """
    if config_dir is None:
        config_dir = get_config_dir()
    
    personality_path = config_dir / "personalities" / f"{personality_name}.json"
    
    if personality_path.exists():
        try:
            with open(personality_path, "r") as f:
                data = json.load(f)
            return PersonalityConfig.from_dict(data)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Failed to load personality config: {e}. Using defaults.")
            return PersonalityConfig()
    
    return PersonalityConfig()


def save_personality(
    config: PersonalityConfig,
    config_dir: Optional[Path] = None,
    personality_name: str = "default",
) -> Path:
    """Save personality configuration to JSON file."""
    if config_dir is None:
        config_dir = get_config_dir()
    
    personalities_dir = config_dir / "personalities"
    personalities_dir.mkdir(parents=True, exist_ok=True)
    
    personality_path = personalities_dir / f"{personality_name}.json"
    
    with open(personality_path, "w") as f:
        json.dump(config.to_dict(), f, indent=2)
    
    return personality_path


def get_system_prompt(
    personality: PersonalityConfig,
    branding_name: str = "NORA AI",
) -> str:
    """Generate a system prompt from personality configuration.
    
    If personality has custom template, use that. Otherwise, generate from components.
    """
    if personality.system_prompt_template:
        return personality.system_prompt_template
    
    comm = personality.communication
    caps = personality.capabilities
    goals = personality.goals
    
    prompt_parts = [
        f"You are {personality.name}, {personality.description}.",
        f"You are powered by {branding_name}.",
        "",
        "# Communication Style",
        f"- Tone: {comm.tone}",
        f"- Verbosity: {comm.verbosity}",
        f"- Use markdown: {comm.use_markdown}",
        f"- Explain reasoning: {comm.explain_reasoning}",
        "",
        "# Capabilities",
        f"- Execute code: {caps.can_execute_code}",
        f"- Access web: {caps.can_access_web}",
        f"- Access files: {caps.can_access_files}",
        f"- Control applications: {caps.can_control_applications}",
        f"- Modify system settings: {caps.can_modify_system}",
        "",
        "# Primary Goal",
        f"{goals.primary}",
        "",
        "# Constraints",
        f"- Always ask before destructive operations",
        f"- Never expose API keys or passwords",
        f"- Respect user privacy and security",
    ]
    
    if goals.avoid:
        prompt_parts.append("")
        prompt_parts.append("# Things to Avoid")
        for item in goals.avoid:
            prompt_parts.append(f"- {item}")
    
    return "\n".join(prompt_parts)


__all__ = [
    "PersonalityConfig",
    "CommunicationStyle",
    "Capabilities",
    "Goals",
    "Rules",
    "PreferencesConfig",
    "load_personality",
    "save_personality",
    "get_system_prompt",
]
