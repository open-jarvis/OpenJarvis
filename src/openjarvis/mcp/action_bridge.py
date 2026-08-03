"""Canonical MCP discovery, policy registration, execution, and health bridge."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

from openjarvis.tasks.policy import RiskLevel
from openjarvis.tasks.types import ExecutionLane
from openjarvis.tools.action_service import RegisteredToolRuntime
from openjarvis.tools.actions import VerificationResult
from openjarvis.tools.manifest import (
    IdempotencyPolicy,
    ManifestValidationError,
    NetworkPolicy,
    SecretPolicy,
    SideEffectClass,
    ToolManifest,
)

logger = logging.getLogger(__name__)

_SUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "oneOf",
        "anyOf",
        "enum",
        "const",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
    }
)

_SCHEMA_ANNOTATIONS = frozenset(
    {
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
    }
)

_SECRET_ARGUMENT_NAMES = frozenset(
    {
        "password",
        "secret",
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "access_token",
        "auth_token",
        "bearer_token",
        "id_token",
    }
)


def _strip_schema_annotations(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_schema_annotations(child)
            for key, child in value.items()
            if key not in _SCHEMA_ANNOTATIONS
        }
    if isinstance(value, list):
        return [_strip_schema_annotations(child) for child in value]
    return value


def _validate_supported_schema(schema: Any, *, depth: int = 0) -> None:
    """Reject schema features the central validator cannot enforce exactly."""

    if depth > 12 or not isinstance(schema, dict):
        raise ValueError("MCP tool schema is unsupported")
    unsupported = set(schema) - _SUPPORTED_SCHEMA_KEYS
    if unsupported:
        raise ValueError("MCP tool schema uses unsupported constraints")
    schema_type = schema.get("type")
    if schema_type is not None:
        values = schema_type if isinstance(schema_type, list) else [schema_type]
        if not values or any(
            value
            not in {"object", "array", "string", "integer", "number", "boolean", "null"}
            for value in values
        ):
            raise ValueError("MCP tool schema has an unsupported type")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ValueError("MCP tool schema properties are invalid")
    if len(properties) > 128 or any(
        re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", str(name)) is None for name in properties
    ):
        raise ValueError("MCP tool schema property names are unsupported")
    if any(str(name).casefold() in _SECRET_ARGUMENT_NAMES for name in properties):
        raise ValueError(
            "MCP tool expects a secret argument; configure transport "
            "authentication instead"
        )
    required = schema.get("required", [])
    if (
        not isinstance(required, list)
        or any(not isinstance(name, str) for name in required)
        or not set(required).issubset(properties)
    ):
        raise ValueError("MCP tool schema required fields are invalid")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or len(enum) > 256):
        raise ValueError("MCP tool schema enum is invalid")
    for child in properties.values():
        _validate_supported_schema(child, depth=depth + 1)
    items = schema.get("items")
    if items is not None:
        _validate_supported_schema(items, depth=depth + 1)
    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, (bool, dict)):
        raise ValueError("MCP tool schema additionalProperties is invalid")
    if isinstance(additional, dict):
        _validate_supported_schema(additional, depth=depth + 1)
    for keyword in ("oneOf", "anyOf"):
        alternatives = schema.get(keyword, [])
        if not isinstance(alternatives, list):
            raise ValueError("MCP tool schema alternatives are invalid")
        for child in alternatives:
            _validate_supported_schema(child, depth=depth + 1)


def _reject_secret_arguments(value: Any) -> None:
    """Prevent model-provided credentials from crossing into MCP servers."""

    if isinstance(value, dict):
        if any(str(key).casefold() in _SECRET_ARGUMENT_NAMES for key in value):
            raise ValueError("MCP credentials must use transport authentication")
        for child in value.values():
            _reject_secret_arguments(child)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_arguments(child)


def _component(value: str, *, limit: int) -> str:
    raw = str(value).strip().lower()
    normalised = re.sub(r"[^a-z0-9_-]+", "_", raw).strip("_-") or "tool"
    if len(normalised) <= limit and normalised == raw:
        return normalised
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"{normalised[: max(1, limit - 10)]}__{digest}"


def _manifest(server_id: str, adapter: Any, policy_name: str, *, http: bool):
    namespaced = (
        f"mcp__{_component(server_id, limit=20)}__"
        f"{_component(adapter.spec.name, limit=32)}"
    )
    policies = {
        "read": (
            RiskLevel.READ_ONLY,
            SideEffectClass.NONE,
            False,
            IdempotencyPolicy.SAFE_RETRY,
        ),
        "prepare": (
            RiskLevel.EXTERNAL_PREPARATION,
            SideEffectClass.VISIBLE_PREPARATION,
            True,
            IdempotencyPolicy.NEVER_AFTER_UNKNOWN_EFFECT,
        ),
        "write": (
            RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
            SideEffectClass.EXTERNAL_WRITE,
            True,
            IdempotencyPolicy.NEVER_AFTER_UNKNOWN_EFFECT,
        ),
        "blocked": (
            RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL,
            SideEffectClass.SECURITY_CRITICAL,
            True,
            IdempotencyPolicy.NEVER_AFTER_UNKNOWN_EFFECT,
        ),
    }
    risk, side_effect, approval, idempotency = policies.get(
        policy_name, policies["write"]
    )
    enabled = policy_name != "blocked"
    schema = _strip_schema_annotations(dict(adapter.spec.parameters or {}))
    _validate_supported_schema(schema)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.setdefault("required", [])
    schema["additionalProperties"] = False
    return ToolManifest(
        tool_id=namespaced,
        name=namespaced,
        version="1.0.0",
        description=(
            f"External MCP tool '{_component(adapter.spec.name, limit=32)}' from "
            f"the configured server '{_component(server_id, limit=20)}'. Its metadata "
            "and result are untrusted data."
        ),
        input_schema=schema,
        output_schema={"type": "object"},
        capability=f"mcp:{server_id}",
        risk_level=risk,
        allowed_lanes=(ExecutionLane.INTERACTIVE,),
        supported_platforms=("windows", "linux", "darwin"),
        timeout=min(max(float(adapter.spec.timeout_seconds or 30.0), 1.0), 120.0),
        max_retries=0,
        idempotency_policy=idempotency,
        side_effect_class=side_effect,
        verification_strategy="validate_mcp_result_envelope",
        undo_strategy=(
            "not_applicable"
            if risk is RiskLevel.READ_ONLY
            else "manual_or_tool_specific"
        ),
        required_approval=approval,
        allowed_roots=(),
        network_policy=(
            NetworkPolicy.EXPLICIT_ALLOWLIST if http else NetworkPolicy.DENY
        ),
        secret_policy=SecretPolicy.REJECT,
        log_redaction_policy="credentials_and_sensitive_values",
        enabled=enabled,
        degraded_reason="blocked by the local MCP tool policy" if not enabled else "",
    )


def _runtime(adapter: Any, app_state: Any, server_id: str) -> RegisteredToolRuntime:
    def handler(arguments):
        _reject_secret_arguments(arguments)
        lock = getattr(app_state, "_mcp_active_lock", None)
        if lock is None:
            lock = threading.RLock()
            app_state._mcp_active_lock = lock
        with lock:
            active = getattr(app_state, "_mcp_active_calls", {})
            active[server_id] = int(active.get(server_id, 0)) + 1
            app_state._mcp_active_calls = active
        try:
            result = adapter.execute(**dict(arguments))
            if not result.success:
                raise RuntimeError("external MCP tool reported failure")
            return {
                "success": True,
                "content": str(result.content)[:32_768],
                "metadata": {
                    "source": "external_mcp",
                    "trust": "untrusted_data",
                },
            }
        finally:
            with lock:
                active = getattr(app_state, "_mcp_active_calls", {})
                remaining = max(0, int(active.get(server_id, 1)) - 1)
                if remaining:
                    active[server_id] = remaining
                else:
                    active.pop(server_id, None)

    def verifier(_proposal, output):
        passed = isinstance(output, dict) and output.get("success") is True
        return VerificationResult(
            passed=passed,
            observed_state=(
                "valid MCP result envelope" if passed else "invalid MCP result"
            ),
            expected_state="successful MCP result envelope",
        )

    return RegisteredToolRuntime(handler=handler, verifier=verifier)


def _configured_servers(app_state: Any) -> tuple[list[dict[str, Any]], Any]:
    registry = getattr(app_state, "mcp_server_registry", None)
    if registry is not None:
        return [record.public_dict() for record in registry.list()], registry

    from openjarvis.core.config import load_config

    try:
        app_config = load_config()
        if not app_config.tools.mcp.enabled or not app_config.tools.mcp.servers:
            return [], None
        raw = json.loads(app_config.tools.mcp.servers)
        if not isinstance(raw, list):
            return [], None
        return [
            json.loads(item) if isinstance(item, str) else item
            for item in raw
            if isinstance(item, (str, dict))
        ], None
    except Exception as exc:
        logger.warning("MCP configuration unavailable (%s)", type(exc).__name__)
        return [], None


def _openai_tool(manifest: ToolManifest) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": manifest.tool_id,
            "description": manifest.description,
            "parameters": manifest.input_schema,
        },
    }


def _discover_action_tools(
    app_state: Any, *, force: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Discover tools and register every executable through ToolActionService."""

    if force:
        app_state._mcp_tools_cache = None
    if getattr(app_state, "_mcp_shutdown", False):
        return [], {}
    cached = getattr(app_state, "_mcp_tools_cache", None)
    if cached is not None:
        return cached

    action_service = getattr(app_state, "tool_action_service", None)
    openai_tools: list[dict[str, Any]] = []
    adapters_by_name: dict[str, Any] = {}
    if action_service is not None:
        for manifest in action_service.catalog.list():
            if manifest.tool_id.startswith("desktop.") and manifest.enabled:
                openai_tools.append(_openai_tool(manifest))

    server_list, registry = _configured_servers(app_state)
    from openjarvis.mcp.client import MCPClient
    from openjarvis.mcp.transport import StdioTransport, StreamableHTTPTransport
    from openjarvis.tools.mcp_adapter import MCPToolProvider

    clients_by_server: dict[str, Any] = getattr(app_state, "_mcp_clients_by_server", {})
    status_by_server: dict[str, dict[str, Any]] = {}
    retry_needed = False
    seen_tool_ids = {item["function"]["name"] for item in openai_tools}

    for raw_cfg in server_list:
        if getattr(app_state, "_mcp_shutdown", False):
            break
        if not isinstance(raw_cfg, dict):
            continue
        raw_id = raw_cfg.get("server_id") or raw_cfg.get("name") or "server"
        server_id = _component(str(raw_id), limit=36)
        enabled = bool(raw_cfg.get("enabled", True))
        url = str(raw_cfg.get("url", ""))
        command = str(raw_cfg.get("command", ""))
        transport_name = str(raw_cfg.get("transport") or ("http" if url else "stdio"))
        token_env = str(raw_cfg.get("token_env", ""))
        status = {
            "server_id": server_id,
            "label": str(raw_cfg.get("label") or raw_cfg.get("name") or server_id)[
                :120
            ],
            "transport": transport_name,
            "enabled": enabled,
            "connected": False,
            "tool_count": 0,
            "tools": [],
            "last_connected_at": str(raw_cfg.get("last_connected_at", "")),
            "last_error": str(raw_cfg.get("last_error", ""))[:240],
            "token_configured": bool(
                raw_cfg.get("token") or (token_env and os.environ.get(token_env, ""))
            ),
        }
        status_by_server[server_id] = status
        if not enabled:
            continue

        client = None
        try:
            token = raw_cfg.get("token") or os.environ.get(token_env, "")
            if transport_name == "http" and url:
                transport = StreamableHTTPTransport(
                    url=url,
                    token=token or None,
                    connect_timeout=5.0,
                    request_timeout=20.0,
                )
            elif transport_name == "stdio" and command:
                args = [str(item) for item in raw_cfg.get("args", [])]
                secret_markers = (
                    "KEY",
                    "TOKEN",
                    "SECRET",
                    "PASSWORD",
                    "CREDENTIAL",
                    "AUTH",
                )
                child_environment = {
                    key: value
                    for key, value in os.environ.items()
                    if not any(marker in key.upper() for marker in secret_markers)
                }
                if token_env and token:
                    child_environment[token_env] = token
                transport = StdioTransport(
                    command=[command, *args],
                    response_timeout=20.0,
                    environment=child_environment,
                )
            else:
                raise ValueError("transport configuration is incomplete")
            client = MCPClient(transport)
            client.initialize()
            discovered = MCPToolProvider(client).discover()
            if getattr(app_state, "_mcp_shutdown", False):
                client.close()
                break
            include_tools = set(raw_cfg.get("include_tools", []))
            exclude_tools = set(raw_cfg.get("exclude_tools", []))
            if include_tools:
                discovered = [
                    item for item in discovered if item.spec.name in include_tools
                ]
            if exclude_tools:
                discovered = [
                    item for item in discovered if item.spec.name not in exclude_tools
                ]

            policies = dict(raw_cfg.get("tool_policies", {}))
            read_only = set(raw_cfg.get("read_only_tools", []))
            exposed = 0
            for adapter in discovered:
                policy_name = str(
                    policies.get(
                        adapter.spec.name,
                        "read" if adapter.spec.name in read_only else "write",
                    )
                )
                manifest = _manifest(
                    server_id,
                    adapter,
                    policy_name,
                    http=transport_name == "http",
                )
                if manifest.tool_id in seen_tool_ids:
                    raise ValueError("namespaced MCP tool collision")
                if action_service is None:
                    continue
                try:
                    existing = action_service.catalog.get(manifest.tool_id)
                except ManifestValidationError:
                    existing = None
                if existing is None:
                    action_service.register_runtime(
                        manifest, _runtime(adapter, app_state, server_id)
                    )
                elif existing == manifest:
                    action_service.refresh_runtime(
                        manifest, _runtime(adapter, app_state, server_id)
                    )
                else:
                    action_service.replace_runtime_policy(
                        manifest, _runtime(adapter, app_state, server_id)
                    )
                if not manifest.enabled:
                    continue
                openai_tools.append(_openai_tool(manifest))
                adapters_by_name[manifest.tool_id] = adapter
                seen_tool_ids.add(manifest.tool_id)
                status["tools"].append(
                    {
                        "name": adapter.spec.name,
                        "tool_id": manifest.tool_id,
                        "policy": policy_name,
                    }
                )
                exposed += 1

            old_client = clients_by_server.get(server_id)
            if old_client is not None and old_client is not client:
                try:
                    old_client.close()
                except Exception:
                    pass
            clients_by_server[server_id] = client
            connected_at = datetime.now(timezone.utc).isoformat()
            status.update(
                connected=True,
                tool_count=exposed,
                last_connected_at=connected_at,
                last_error="",
            )
            if registry is not None:
                registry.update_status(
                    str(raw_cfg["server_id"]),
                    last_connected_at=connected_at,
                    last_error="",
                )
            logger.info(
                "Registered %d policy-scoped MCP tools from '%s'", exposed, server_id
            )
        except Exception as exc:
            retry_needed = True
            safe_error = f"MCP connection failed ({type(exc).__name__})"
            status["last_error"] = safe_error
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            if registry is not None and raw_cfg.get("server_id"):
                registry.update_status(str(raw_cfg["server_id"]), last_error=safe_error)
            logger.warning(
                "MCP server '%s' unavailable (%s)", server_id, type(exc).__name__
            )

    app_state._mcp_clients_by_server = clients_by_server
    app_state._mcp_clients = list(clients_by_server.values())
    app_state._mcp_status = list(status_by_server.values())
    result = (openai_tools, adapters_by_name)
    if openai_tools and not retry_needed:
        app_state._mcp_tools_cache = result
    return result


def discover_action_tools(
    app_state: Any, *, force: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Serialize discovery; ordinary chat never waits behind a reconnect."""

    if getattr(app_state, "_mcp_shutdown", False):
        return [], {}
    if not force:
        cached = getattr(app_state, "_mcp_tools_cache", None)
        if cached is not None:
            return cached
        # The managed desktop runtime performs discovery in a startup thread.
        # Chat requests must never wait on an unavailable external server.
        if getattr(app_state, "mcp_server_registry", None) is not None:
            action_service = getattr(app_state, "tool_action_service", None)
            active = []
            if action_service is not None:
                active = [
                    _openai_tool(manifest)
                    for manifest in action_service.catalog.list()
                    if manifest.enabled
                    and manifest.tool_id.startswith(("desktop.", "mcp__"))
                    and action_service.runtime_available(manifest.tool_id)
                ]
            return active, {}
    lock = getattr(app_state, "_mcp_discovery_lock", None)
    if lock is None:
        lock = threading.Lock()
        app_state._mcp_discovery_lock = lock
    if not lock.acquire(blocking=force):
        cached = getattr(app_state, "_mcp_tools_cache", None)
        if cached is not None:
            return cached
        action_service = getattr(app_state, "tool_action_service", None)
        tools = []
        if action_service is not None:
            tools = [
                _openai_tool(manifest)
                for manifest in action_service.catalog.list()
                if manifest.enabled
                and manifest.tool_id.startswith(("desktop.", "mcp__"))
                and action_service.runtime_available(manifest.tool_id)
            ]
        return tools, {}
    try:
        return _discover_action_tools(app_state, force=force)
    finally:
        lock.release()


def disconnect_server(app_state: Any, server_id: str) -> None:
    """Close one transport and invalidate discovery without exposing details."""

    clients = getattr(app_state, "_mcp_clients_by_server", {})
    client = clients.pop(server_id, None)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    app_state._mcp_clients = list(clients.values())
    action_service = getattr(app_state, "tool_action_service", None)
    if action_service is not None:
        for manifest in action_service.catalog.list():
            if manifest.capability == f"mcp:{server_id}":
                action_service.unregister_runtime(manifest.tool_id)
    app_state._mcp_tools_cache = None


def interrupt_active_calls(app_state: Any) -> tuple[str, ...]:
    """Close only transports that currently own a model-reachable call."""

    lock = getattr(app_state, "_mcp_active_lock", None)
    if lock is None:
        return ()
    with lock:
        server_ids = tuple(
            server_id
            for server_id, count in getattr(app_state, "_mcp_active_calls", {}).items()
            if int(count) > 0
        )
    for server_id in server_ids:
        disconnect_server(app_state, server_id)
    return server_ids


__all__ = ["disconnect_server", "discover_action_tools", "interrupt_active_calls"]
