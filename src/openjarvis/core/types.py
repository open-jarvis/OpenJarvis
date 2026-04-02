"""Canonical data types shared across all OpenJarvis primitives."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence  # noqa: I001

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """Chat message roles (OpenAI-compatible)."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Quantization(str, Enum):
    """Model quantization formats."""

    NONE = "none"
    FP8 = "fp8"
    FP4 = "fp4"
    INT8 = "int8"
    INT4 = "int4"
    GGUF = "gguf"
    GGUF_Q4 = "gguf_q4"
    GGUF_Q8 = "gguf_q8"


class StepType(str, Enum):
    """Types of steps within an agent trace."""

    ROUTE = "route"
    RETRIEVE = "retrieve"
    GENERATE = "generate"
    TOOL_CALL = "tool_call"
    RESPOND = "respond"


# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToolCall:
    """A single tool invocation request embedded in an assistant message."""

    id: str
    name: str
    arguments: str  # JSON string


@dataclass(slots=True)
class Message:
    """A single chat message (OpenAI-compatible structure)."""

    role: Role
    content: str = ""
    name: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Conversation:
    """Ordered list of messages with an optional sliding-window cap."""

    messages: List[Message] = field(default_factory=list)
    max_messages: Optional[int] = None

    def add(self, message: Message) -> None:
        """Append a message, trimming oldest if *max_messages* is set."""
        self.messages.append(message)
        if self.max_messages is not None and len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages :]

    def window(self, n: int) -> List[Message]:
        """Return the last *n* messages."""
        if n <= 0:
            return []
        return self.messages[-n:]


# ---------------------------------------------------------------------------
# Model / tool / telemetry records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelSpec:
    """Metadata describing a language model."""

    model_id: str
    name: str
    parameter_count_b: float
    context_length: int
    active_parameter_count_b: Optional[float] = None  # MoE active params
    quantization: Quantization = Quantization.NONE
    min_vram_gb: float = 0.0
    supported_engines: Sequence[str] = ()
    provider: str = ""
    requires_api_key: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    """Result returned by a tool invocation."""

    tool_name: str
    content: str
    success: bool = True
    usage: Dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TelemetryRecord:
    """Single telemetry observation recorded after an inference call."""

    timestamp: float
    model_id: str
    prompt_tokens: int = 0
    prompt_tokens_evaluated: int = 0  # KV-cache-aware: actual tokens processed
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0
    ttft: float = 0.0  # time to first token
    cost_usd: float = 0.0
    energy_joules: float = 0.0
    power_watts: float = 0.0
    gpu_utilization_pct: float = 0.0
    gpu_memory_used_gb: float = 0.0
    gpu_temperature_c: float = 0.0
    throughput_tok_per_sec: float = 0.0
    energy_per_output_token_joules: float = 0.0
    throughput_per_watt: float = 0.0
    prefill_latency_seconds: float = 0.0
    decode_latency_seconds: float = 0.0
    prefill_energy_joules: float = 0.0
    decode_energy_joules: float = 0.0
    mean_itl_ms: float = 0.0
    median_itl_ms: float = 0.0
    p90_itl_ms: float = 0.0
    p95_itl_ms: float = 0.0
    p99_itl_ms: float = 0.0
    std_itl_ms: float = 0.0
    is_streaming: bool = False
    engine: str = ""
    agent: str = ""
    energy_method: str = ""
    energy_vendor: str = ""
    batch_id: str = ""
    is_warmup: bool = False
    cpu_energy_joules: float = 0.0
    gpu_energy_joules: float = 0.0
    dram_energy_joules: float = 0.0
    tokens_per_joule: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Trace types — full interaction-level recording
# ---------------------------------------------------------------------------


def _trace_id() -> str:
    return uuid.uuid4().hex[:16]


def _message_to_dict(msg: "Message") -> Dict[str, Any]:
    """Serialize a Message to a JSON-safe dict."""
    d: Dict[str, Any] = {"role": msg.role.value, "content": msg.content}
    if msg.name:
        d["name"] = msg.name
    if msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id:
        d["tool_call_id"] = msg.tool_call_id
    return d


@dataclass(slots=True)
class TraceStep:
    """A single step within an agent trace.

    Each step records what the agent did (route, retrieve, generate,
    tool_call, respond), its inputs and outputs, and timing.
    """

    step_type: StepType
    timestamp: float
    duration_seconds: float = 0.0
    input: Dict[str, Any] = field(default_factory=dict)
    output: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Trace:
    """Complete trace of an agent handling a query.

    A trace captures the full sequence of steps an agent took to handle a
    query — which model was selected, what memory was retrieved, which tools
    were called, and the final response.  Traces are the primary input to the
    learning system: by analyzing which decisions led to good outcomes, the
    system can improve routing, tool selection, and memory strategies.
    """

    trace_id: str = field(default_factory=_trace_id)
    query: str = ""
    agent: str = ""
    model: str = ""
    engine: str = ""
    steps: List[TraceStep] = field(default_factory=list)
    result: str = ""
    outcome: Optional[str] = None  # None=unknown, "success", "failure"
    feedback: Optional[float] = None  # user quality score [0, 1]
    started_at: float = 0.0
    ended_at: float = 0.0
    total_tokens: int = 0
    total_latency_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    messages: List[Dict[str, Any]] = field(default_factory=list)

    def add_step(self, step: TraceStep) -> None:
        """Append a step and update running totals."""
        self.steps.append(step)
        self.total_latency_seconds += step.duration_seconds
        self.total_tokens += step.output.get("tokens", 0)


@dataclass(slots=True)
class RoutingContext:
    """Context describing a query for model routing decisions."""

    query: str = ""
    query_length: int = 0
    has_code: bool = False
    has_math: bool = False
    has_reasoning: bool = False
    language: str = "en"
    urgency: float = 0.5
    complexity_score: float = 0.0  # 0.0 (trivial) to 1.0 (very complex)
    suggested_max_tokens: int = 1024
    metadata: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "Conversation",
    "Message",
    "ModelSpec",
    "Quantization",
    "Role",
    "RoutingContext",
    "StepType",
    "TelemetryRecord",
    "ToolCall",
    "ToolResult",
    "Trace",
    "TraceStep",
    "_message_to_dict",
]
