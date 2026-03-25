"""MCP JSON-RPC 2.0 protocol message types."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

# Error codes per JSON-RPC 2.0 / MCP spec
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


@dataclass
class MCPRequest:
    """JSON-RPC 2.0 request message.

    Set *id* to ``None`` to create a JSON-RPC **notification** (no ``id``
    field will appear in the serialized output, and no response is expected).
    """

    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int | str] = 0
    jsonrpc: str = "2.0"

    def to_dict(self) -> Dict[str, Any]:
        """Return a dict suitable for JSON serialization.

        Omits the ``id`` key when it is ``None`` (notification).
        """
        obj: Dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
            "params": self.params,
        }
        if self.id is not None:
            obj["id"] = self.id
        return obj

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, data: str) -> MCPRequest:
        """Deserialize from JSON string."""
        parsed = json.loads(data)
        return cls(
            method=parsed["method"],
            params=parsed.get("params", {}),
            id=parsed.get("id", 0),
            jsonrpc=parsed.get("jsonrpc", "2.0"),
        )


@dataclass
class MCPResponse:
    """JSON-RPC 2.0 response message."""

    result: Any = None
    error: Optional[Dict[str, Any]] = None
    id: int | str = 0
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        """Serialize to JSON string."""
        obj: Dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            obj["error"] = self.error
        else:
            obj["result"] = self.result
        return json.dumps(obj)

    @classmethod
    def from_json(cls, data: str) -> MCPResponse:
        """Deserialize from JSON string."""
        parsed = json.loads(data)
        return cls(
            result=parsed.get("result"),
            error=parsed.get("error"),
            id=parsed.get("id", 0),
            jsonrpc=parsed.get("jsonrpc", "2.0"),
        )

    @classmethod
    def error_response(
        cls,
        id: int | str,
        code: int,
        message: str,
        data: Any = None,
    ) -> MCPResponse:
        """Create an error response."""
        error: Dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return cls(error=error, id=id)


@dataclass
class MCPNotification:
    """JSON-RPC 2.0 notification (no id, no response expected)."""

    method: str
    params: Dict[str, Any] = field(default_factory=dict)
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(
            {
                "jsonrpc": self.jsonrpc,
                "method": self.method,
                "params": self.params,
            }
        )


@dataclass
class MCPError(Exception):
    """MCP protocol error with JSON-RPC error code."""

    code: int
    message: str
    data: Any = None

    def __str__(self) -> str:
        return f"MCPError({self.code}): {self.message}"


__all__ = [
    "INTERNAL_ERROR",
    "INVALID_PARAMS",
    "INVALID_REQUEST",
    "MCPError",
    "MCPNotification",
    "MCPRequest",
    "MCPResponse",
    "METHOD_NOT_FOUND",
    "PARSE_ERROR",
]
