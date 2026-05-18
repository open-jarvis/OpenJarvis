"""Canonical registry of external analytics events.

Single source of truth for every event name and property the OpenJarvis
analytics module is allowed to send. Any event not declared here is
dropped at send time. Any property not declared on a known event is
also dropped. This is the fail-closed half of the PII guardrail —
see :mod:`openjarvis.analytics.redaction` for the value-level filters.

Keeping the catalog in code (not config) means PR review is the gate
for adding a new event, and ``docs/telemetry.md`` can render from this
module as the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

PropertyValidator = Callable[[Any], bool]


@dataclass(frozen=True, slots=True)
class EventSpec:
    """Declaration for one analytics event."""

    name: str
    description: str
    properties: dict[str, PropertyValidator]


# ---------------------------------------------------------------------------
# Reusable validators
# ---------------------------------------------------------------------------


def _is_bool(v: Any) -> bool:
    return isinstance(v, bool)


def _is_int_nonneg(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _is_number_nonneg(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def _is_short_str(v: Any) -> bool:
    return isinstance(v, str) and 0 < len(v) <= 64


def _is_med_str(v: Any) -> bool:
    return isinstance(v, str) and 0 < len(v) <= 200


def _is_hash16(v: Any) -> bool:
    """sha256 prefix, 16 hex chars — used for hashed model/tool identifiers."""
    if not isinstance(v, str) or len(v) != 16:
        return False
    return all(c in "0123456789abcdef" for c in v)


def _is_one_of(*allowed: str) -> PropertyValidator:
    allowed_set = frozenset(allowed)

    def check(v: Any) -> bool:
        return isinstance(v, str) and v in allowed_set

    return check


# ---------------------------------------------------------------------------
# Closed enums (allowlists for free-form-looking strings)
# ---------------------------------------------------------------------------

_OS_VALUES = ("darwin", "linux", "wsl", "windows", "unknown")
_ARCH_VALUES = ("x86_64", "arm64", "aarch64", "unknown")
_PLATFORM_VALUES = (
    "cli",
    "macos",
    "linux",
    "windows",
    "tauri-macos",
    "tauri-linux",
    "tauri-windows",
    "web",
)
_INSTALL_STAGES = (
    "deps",
    "uv",
    "python",
    "venv",
    "package",
    "ollama",
    "model_download",
    "config",
    "verify",
    "complete",
)
_SETUP_PRESETS = (
    "morning-digest-mac",
    "deep-research",
    "code-assistant",
    "minimal",
    "custom",
    "default",
)
_ERROR_CLASSES = (
    "network_error",
    "engine_unreachable",
    "model_not_found",
    "tool_timeout",
    "tool_error",
    "rate_limit",
    "auth_failure",
    "permission_denied",
    "validation_error",
    "config_error",
    "unknown_error",
)
_FEATURE_NAMES = (
    "chat",
    "voice",
    "agents",
    "skills",
    "memory",
    "tools",
    "connectors",
    "scheduler",
    "workflows",
    "digest",
    "research",
    "evals",
    "feedback",
    "telemetry_dashboard",
    "settings",
)
_TOOL_NAMES = (
    "http_request",
    "file_read",
    "file_write",
    "shell",
    "search_web",
    "calculator",
    "memory_search",
    "memory_store",
    "code_exec",
    "image_view",
    "gmail",
    "calendar",
    "drive",
    "github",
    "hackernews",
    "weather",
    "notion",
    "strava",
    "custom_tool",
)
_CONNECTOR_NAMES = (
    "google",
    "gmail",
    "calendar",
    "drive",
    "github",
    "notion",
    "strava",
    "weather",
    "hackernews",
    "slack",
    "telegram",
    "discord",
    "webhook",
    "sendblue",
    "whatsapp",
    "signal",
    "custom",
)
_ENGINE_NAMES = (
    "ollama",
    "vllm",
    "mlx",
    "llama_cpp",
    "openai",
    "anthropic",
    "google",
    "unknown",
)


# ---------------------------------------------------------------------------
# Event specifications
# ---------------------------------------------------------------------------

_SPECS: tuple[EventSpec, ...] = (
    # -- Install funnel (sent from install.sh) ------------------------------
    EventSpec(
        name="install_started",
        description="Install script began executing (curl | bash entry).",
        properties={
            "os": _is_one_of(*_OS_VALUES),
            "arch": _is_one_of(*_ARCH_VALUES),
            "installer_version": _is_short_str,
        },
    ),
    EventSpec(
        name="install_stage_completed",
        description="One install stage finished successfully.",
        properties={
            "stage": _is_one_of(*_INSTALL_STAGES),
            "elapsed_ms": _is_int_nonneg,
            "os": _is_one_of(*_OS_VALUES),
        },
    ),
    EventSpec(
        name="install_completed",
        description="Full install finished successfully.",
        properties={
            "total_elapsed_ms": _is_int_nonneg,
            "os": _is_one_of(*_OS_VALUES),
            "arch": _is_one_of(*_ARCH_VALUES),
        },
    ),
    EventSpec(
        name="install_failed",
        description="Install script exited non-zero at a known stage.",
        properties={
            "stage": _is_one_of(*_INSTALL_STAGES),
            "exit_code": _is_int_nonneg,
            "os": _is_one_of(*_OS_VALUES),
            "arch": _is_one_of(*_ARCH_VALUES),
        },
    ),
    EventSpec(
        name="uninstall_started",
        description="Uninstall script began executing.",
        properties={
            "days_since_install": _is_int_nonneg,
            "os": _is_one_of(*_OS_VALUES),
        },
    ),
    # -- App lifecycle ------------------------------------------------------
    EventSpec(
        name="app_opened",
        description="App boot — every launch of CLI or desktop UI.",
        properties={
            "version": _is_short_str,
            "platform": _is_one_of(*_PLATFORM_VALUES),
        },
    ),
    EventSpec(
        name="setup_completed",
        description="`jarvis init` finished and config.toml was written.",
        properties={
            "preset": _is_one_of(*_SETUP_PRESETS),
            "model_hash": _is_hash16,
            "engine": _is_one_of(*_ENGINE_NAMES),
        },
    ),
    EventSpec(
        name="first_chat_sent",
        description="First chat message ever sent on this anon_id.",
        properties={
            "platform": _is_one_of(*_PLATFORM_VALUES),
        },
    ),
    # -- Usage (per session, aggregated) -----------------------------------
    EventSpec(
        name="chat_session_ended",
        description=(
            "A chat session closed (explicit close or idle timeout). "
            "Aggregated counts only — no content."
        ),
        properties={
            "turn_count": _is_int_nonneg,
            "tokens_in": _is_int_nonneg,
            "tokens_out": _is_int_nonneg,
            "latency_ms_p50": _is_number_nonneg,
            "latency_ms_p95": _is_number_nonneg,
            "tool_count": _is_int_nonneg,
            "unique_tools": _is_int_nonneg,
            "unique_models": _is_int_nonneg,
            "error_count": _is_int_nonneg,
            "model_hash": _is_hash16,
            "engine": _is_one_of(*_ENGINE_NAMES),
            "duration_ms": _is_int_nonneg,
        },
    ),
    EventSpec(
        name="tool_first_used",
        description="First time this anon_id used a given tool.",
        properties={
            "tool_name": _is_one_of(*_TOOL_NAMES),
        },
    ),
    EventSpec(
        name="model_changed",
        description="User explicitly switched the active model.",
        properties={
            "from_model_hash": _is_hash16,
            "to_model_hash": _is_hash16,
            "engine": _is_one_of(*_ENGINE_NAMES),
        },
    ),
    EventSpec(
        name="connector_auth_completed",
        description="OAuth flow finished successfully for a connector.",
        properties={
            "connector_name": _is_one_of(*_CONNECTOR_NAMES),
        },
    ),
    EventSpec(
        name="feature_used",
        description="A top-level feature was invoked.",
        properties={
            "feature_name": _is_one_of(*_FEATURE_NAMES),
        },
    ),
    EventSpec(
        name="feedback_submitted",
        description="User submitted feedback. No comment content sent.",
        properties={
            "rating": _is_int_nonneg,
            "has_comment": _is_bool,
        },
    ),
    EventSpec(
        name="error_shown_to_user",
        description="A user-visible error was rendered. Error class only.",
        properties={
            "error_class": _is_one_of(*_ERROR_CLASSES),
            "platform": _is_one_of(*_PLATFORM_VALUES),
        },
    ),
    EventSpec(
        name="settings_changed",
        description="User toggled or modified a setting.",
        properties={
            "setting_key": _is_short_str,
        },
    ),
    # -- Daily rollup ------------------------------------------------------
    EventSpec(
        name="usage_daily_summary",
        description=(
            "Once-per-day aggregated counts. Cheaper than per-event "
            "for high-frequency operations."
        ),
        properties={
            "sessions": _is_int_nonneg,
            "total_tokens": _is_int_nonneg,
            "total_inferences": _is_int_nonneg,
            "unique_tools": _is_int_nonneg,
            "unique_models": _is_int_nonneg,
            "total_errors": _is_int_nonneg,
            "total_duration_ms": _is_int_nonneg,
        },
    ),
)


REGISTRY: dict[str, EventSpec] = {spec.name: spec for spec in _SPECS}


def validate_event(name: str, properties: dict[str, Any]) -> dict[str, Any] | None:
    """Return cleaned properties or ``None`` if the event name is unknown.

    Unknown properties are silently dropped. Properties whose values
    fail the spec's validator are silently dropped. Empty result is
    valid (the event itself is still recorded).
    """
    spec = REGISTRY.get(name)
    if spec is None:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in properties.items():
        validator = spec.properties.get(key)
        if validator is None:
            continue
        if not validator(value):
            continue
        cleaned[key] = value
    return cleaned


def known_event_names() -> tuple[str, ...]:
    """All event names declared in the catalog (for docs and tests)."""
    return tuple(REGISTRY.keys())


# Public re-exports of the allowlists for cross-module use (bridge.py).
KNOWN_TOOL_NAMES = frozenset(_TOOL_NAMES)
KNOWN_CONNECTORS = frozenset(_CONNECTOR_NAMES)
KNOWN_FEATURES = frozenset(_FEATURE_NAMES)
KNOWN_ENGINES = frozenset(_ENGINE_NAMES)


__all__ = [
    "EventSpec",
    "REGISTRY",
    "PropertyValidator",
    "validate_event",
    "known_event_names",
    "KNOWN_TOOL_NAMES",
    "KNOWN_CONNECTORS",
    "KNOWN_FEATURES",
    "KNOWN_ENGINES",
]
