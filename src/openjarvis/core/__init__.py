"""Core module — registries, types, configuration, and event bus."""

from __future__ import annotations

# Run env-var alias pass before anything else imports cloud/engine code so
# canonical names (e.g. OPENAI_API_KEY) are populated from aliases (e.g.
# OpenAI_API) before SDKs and engines read os.environ.
from openjarvis.core.env import apply_aliases as _apply_env_aliases

_apply_env_aliases()

from openjarvis.core.registry import (  # noqa: E402  — must follow alias pass
    AgentRegistry,
    EngineRegistry,
    MemoryRegistry,
    ModelRegistry,
    ToolRegistry,
)
from openjarvis.core.types import (
    Conversation,
    Message,
    ModelSpec,
    Quantization,
    Role,
    TelemetryRecord,
    ToolCall,
    ToolResult,
)

__all__ = [
    "AgentRegistry",
    "Conversation",
    "EngineRegistry",
    "MemoryRegistry",
    "Message",
    "ModelRegistry",
    "ModelSpec",
    "Quantization",
    "Role",
    "TelemetryRecord",
    "ToolCall",
    "ToolRegistry",
    "ToolResult",
]
