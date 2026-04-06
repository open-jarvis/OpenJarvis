"""Standardized error hierarchy for OpenJarvis.

This module provides a consistent error handling pattern across the entire
OpenJarvis codebase. All custom exceptions should inherit from these base
classes.
"""

from __future__ import annotations

from typing import Any, Optional


class OpenJarvisError(Exception):
    """Base exception for all OpenJarvis errors.

    All custom exceptions in OpenJarvis should inherit from this class.
    It provides consistent error handling and automatic error tracking.
    """

    code: str = "OPENJARVIS_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: Optional[dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.cause = cause

    def __str__(self) -> str:
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({detail_str})"
        return self.message

    def to_dict(self) -> dict[str, Any]:
        """Convert error to a dictionary for API responses."""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


# ---------------------------------------------------------------------------
# Configuration Errors
# ---------------------------------------------------------------------------


class ConfigError(OpenJarvisError):
    """Base class for configuration-related errors."""

    code = "CONFIG_ERROR"
    status_code = 400


class ConfigNotFoundError(ConfigError):
    """Raised when a required configuration file or key is not found."""

    code = "CONFIG_NOT_FOUND"
    status_code = 404


class ConfigValidationError(ConfigError):
    """Raised when configuration validation fails."""

    code = "CONFIG_VALIDATION_ERROR"
    status_code = 422


# ---------------------------------------------------------------------------
# Engine Errors
# ------------------------------------------------------------------------


class EngineError(OpenJarvisError):
    """Base class for inference engine errors."""

    code = "ENGINE_ERROR"
    status_code = 500


class EngineNotFoundError(EngineError):
    """Raised when no inference engine is available."""

    code = "ENGINE_NOT_FOUND"
    status_code = 503


class EngineTimeoutError(EngineError):
    """Raised when engine request times out."""

    code = "ENGINE_TIMEOUT"
    status_code = 504


class EngineRateLimitError(EngineError):
    """Raised when engine rate limit is exceeded."""

    code = "ENGINE_RATE_LIMIT"
    status_code = 429


# ---------------------------------------------------------------------------
# Agent Errors
# ------------------------------------------------------------------------


class AgentError(OpenJarvisError):
    """Base class for agent-related errors."""

    code = "AGENT_ERROR"
    status_code = 500


class AgentNotFoundError(AgentError):
    """Raised when a requested agent is not found."""

    code = "AGENT_NOT_FOUND"
    status_code = 404


class AgentTimeoutError(AgentError):
    """Raised when agent execution times out."""

    code = "AGENT_TIMEOUT"
    status_code = 504


class AgentMaxTurnsError(AgentError):
    """Raised when agent exceeds maximum turn limit."""

    code = "AGENT_MAX_TURNS"
    status_code = 400


# ---------------------------------------------------------------------------
# Tool Errors
# ------------------------------------------------------------------------


class ToolError(OpenJarvisError):
    """Base class for tool-related errors."""

    code = "TOOL_ERROR"
    status_code = 500


class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not found."""

    code = "TOOL_NOT_FOUND"
    status_code = 404


class ToolExecutionError(ToolError):
    """Raised when a tool fails to execute."""

    code = "TOOL_EXECUTION_ERROR"
    status_code = 500


class ToolPermissionError(ToolError):
    """Raised when agent lacks permission to use a tool."""

    code = "TOOL_PERMISSION_DENIED"
    status_code = 403


class ToolTimeoutError(ToolError):
    """Raised when a tool execution times out."""

    code = "TOOL_TIMEOUT"
    status_code = 504


# ---------------------------------------------------------------------------
# Memory Errors
# ------------------------------------------------------------------------


class MemoryError(OpenJarvisError):
    """Base class for memory/storage errors."""

    code = "MEMORY_ERROR"
    status_code = 500


class MemoryNotFoundError(MemoryError):
    """Raised when a memory backend is not found."""

    code = "MEMORY_NOT_FOUND"
    status_code = 404


class MemoryIndexError(MemoryError):
    """Raised when memory indexing fails."""

    code = "MEMORY_INDEX_ERROR"
    status_code = 500


class MemoryRetrievalError(MemoryError):
    """Raised when memory retrieval fails."""

    code = "MEMORY_RETRIEVAL_ERROR"
    status_code = 500


# ---------------------------------------------------------------------------
# Channel Errors
# ------------------------------------------------------------------------


class ChannelError(OpenJarvisError):
    """Base class for channel communication errors."""

    code = "CHANNEL_ERROR"
    status_code = 500


class ChannelNotFoundError(ChannelError):
    """Raised when a channel is not found."""

    code = "CHANNEL_NOT_FOUND"
    status_code = 404


class ChannelAuthError(ChannelError):
    """Raised when channel authentication fails."""

    code = "CHANNEL_AUTH_ERROR"
    status_code = 401


class ChannelRateLimitError(ChannelError):
    """Raised when channel rate limit is exceeded."""

    code = "CHANNEL_RATE_LIMIT"
    status_code = 429


# ---------------------------------------------------------------------------
# Security Errors
# ------------------------------------------------------------------------


class SecurityError(OpenJarvisError):
    """Base class for security-related errors."""

    code = "SECURITY_ERROR"
    status_code = 500


class PermissionDeniedError(SecurityError):
    """Raised when an operation is not allowed."""

    code = "PERMISSION_DENIED"
    status_code = 403


class InvalidCredentialError(SecurityError):
    """Raised when credentials are invalid."""

    code = "INVALID_CREDENTIAL"
    status_code = 401


class RateLimitExceededError(SecurityError):
    """Raised when rate limit is exceeded."""

    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429


# ---------------------------------------------------------------------------
# Telemetry Errors
# ------------------------------------------------------------------------


class TelemetryError(OpenJarvisError):
    """Base class for telemetry errors."""

    code = "TELEMETRY_ERROR"
    status_code = 500


class TelemetryNotAvailableError(TelemetryError):
    """Raised when telemetry is not available."""

    code = "TELEMETRY_NOT_AVAILABLE"
    status_code = 503


# ---------------------------------------------------------------------------
# Learning Errors
# ------------------------------------------------------------------------


class LearningError(OpenJarvisError):
    """Base class for learning/training errors."""

    code = "LEARNING_ERROR"
    status_code = 500


class TrainingError(LearningError):
    """Raised when training fails."""

    code = "TRAINING_ERROR"
    status_code = 500


class OptimizationError(LearningError):
    """Raised when optimization fails."""

    code = "OPTIMIZATION_ERROR"
    status_code = 500


# ---------------------------------------------------------------------------
# Registry Errors
# ------------------------------------------------------------------------


class RegistryError(OpenJarvisError):
    """Base class for registry errors."""

    code = "REGISTRY_ERROR"
    status_code = 500


class RegistryNotFoundError(RegistryError):
    """Raised when a registry key is not found."""

    code = "REGISTRY_NOT_FOUND"
    status_code = 404


class RegistryDuplicateError(RegistryError):
    """Raised when trying to register a duplicate."""

    code = "REGISTRY_DUPLICATE"
    status_code = 409


# ---------------------------------------------------------------------------
# Utility functions
# ------------------------------------------------------------------------


def format_error(error: Exception) -> dict[str, Any]:
    """Format any exception into a standardized error response.

    Args:
        error: Any exception

    Returns:
        Dictionary with error information suitable for API responses
    """
    if isinstance(error, OpenJarvisError):
        return error.to_dict()

    return {
        "error": "INTERNAL_ERROR",
        "message": str(error),
        "details": {"type": type(error).__name__},
    }


__all__ = [
    "OpenJarvisError",
    # Config
    "ConfigError",
    "ConfigNotFoundError",
    "ConfigValidationError",
    # Engine
    "EngineError",
    "EngineNotFoundError",
    "EngineTimeoutError",
    "EngineRateLimitError",
    # Agent
    "AgentError",
    "AgentNotFoundError",
    "AgentTimeoutError",
    "AgentMaxTurnsError",
    # Tool
    "ToolError",
    "ToolNotFoundError",
    "ToolExecutionError",
    "ToolPermissionError",
    "ToolTimeoutError",
    # Memory
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryIndexError",
    "MemoryRetrievalError",
    # Channel
    "ChannelError",
    "ChannelNotFoundError",
    "ChannelAuthError",
    "ChannelRateLimitError",
    # Security
    "SecurityError",
    "PermissionDeniedError",
    "InvalidCredentialError",
    "RateLimitExceededError",
    # Telemetry
    "TelemetryError",
    "TelemetryNotAvailableError",
    # Learning
    "LearningError",
    "TrainingError",
    "OptimizationError",
    # Registry
    "RegistryError",
    "RegistryNotFoundError",
    "RegistryDuplicateError",
    # Utils
    "format_error",
]
