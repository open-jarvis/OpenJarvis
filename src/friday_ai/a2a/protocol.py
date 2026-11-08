"""A2A protocol types — Google A2A spec (JSON-RPC 2.0)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


@dataclass(slots=True)
class AgentCard:
    """Agent discovery card served at /.well-known/agent.json."""

    name: str
    description: str = ""
    url: str = ""
    version: str = "0.1.0"
    capabilities: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    authentication: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": self.capabilities,
            "skills": self.skills,
            "authentication": self.authentication,
        }


@dataclass
class A2ATask:
    """An A2A task with state machine."""

    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    state: TaskState = TaskState.SUBMITTED
    input_text: str = ""
    output_text: str = ""
    history: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.task_id,
            "state": self.state.value,
            "input": self.input_text,
            "output": self.output_text,
            "history": self.history,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class A2ARequest:
    """JSON-RPC 2.0 request for A2A."""

    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": self.method,
            "params": self.params,
            "id": self.request_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


@dataclass(slots=True)
class A2AResponse:
    """JSON-RPC 2.0 response for A2A."""

    result: Any = None
    error: Optional[Dict[str, Any]] = None
    request_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        resp: Dict[str, Any] = {"jsonrpc": "2.0", "id": self.request_id}
        if self.error:
            resp["error"] = self.error
        else:
            resp["result"] = self.result
        return resp

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, data: str) -> A2AResponse:
        parsed = json.loads(data)
        return cls(
            result=parsed.get("result"),
            error=parsed.get("error"),
            request_id=parsed.get("id", ""),
        )


__all__ = ["A2ARequest", "A2AResponse", "A2ATask", "AgentCard", "TaskState"]
