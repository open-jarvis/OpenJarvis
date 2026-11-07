"""Agent-to-Agent protocol — Google A2A spec implementation."""

from friday_ai.a2a.client import A2AClient
from friday_ai.a2a.protocol import A2ARequest, A2AResponse, A2ATask, AgentCard
from friday_ai.a2a.server import A2AServer
from friday_ai.a2a.tool import A2AAgentTool

__all__ = [
    "A2AAgentTool",
    "A2AClient",
    "A2ARequest",
    "A2AResponse",
    "A2AServer",
    "A2ATask",
    "AgentCard",
]
