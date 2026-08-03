"""Persistent, non-secret configuration and health state for external MCP servers."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_TOKEN_ENV_RE = re.compile(r"^MCP_[A-Z0-9_]{1,80}_API_KEY$")
_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")
_TOOL_POLICY_VALUES = frozenset({"read", "prepare", "write", "blocked"})


@dataclass(frozen=True, slots=True)
class MCPServerRecord:
    server_id: str
    label: str
    transport: str
    enabled: bool = True
    url: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    token_env: str = ""
    include_tools: tuple[str, ...] = ()
    exclude_tools: tuple[str, ...] = ()
    tool_policies: Mapping[str, str] = field(default_factory=dict)
    last_connected_at: str = ""
    last_error: str = ""

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["args"] = list(self.args)
        value["include_tools"] = list(self.include_tools)
        value["exclude_tools"] = list(self.exclude_tools)
        value["tool_policies"] = dict(self.tool_policies)
        value["token_configured"] = bool(
            self.token_env and os.environ.get(self.token_env, "")
        )
        return value


class MCPServerRegistry:
    """Store server grants and safe health summaries without storing tokens."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve(strict=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        if not self.path.exists():
            self._write({"schema_version": 1, "servers": []})

    def list(self) -> tuple[MCPServerRecord, ...]:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("MCP server configuration is invalid") from exc
            records: list[MCPServerRecord] = []
            for value in payload.get("servers", []):
                if not isinstance(value, dict):
                    continue
                try:
                    records.append(self._normalise(value))
                except (KeyError, TypeError, ValueError):
                    continue
            return tuple(records)

    def get(self, server_id: str) -> MCPServerRecord | None:
        return next((item for item in self.list() if item.server_id == server_id), None)

    def put(self, value: Mapping[str, Any]) -> MCPServerRecord:
        record = self._normalise(value)
        with self._lock:
            records = {item.server_id: item for item in self.list()}
            records[record.server_id] = record
            self._save_records(records.values())
        return record

    def remove(self, server_id: str) -> bool:
        with self._lock:
            records = {item.server_id: item for item in self.list()}
            removed = records.pop(server_id, None) is not None
            if removed:
                self._save_records(records.values())
            return removed

    def update_status(
        self,
        server_id: str,
        *,
        last_connected_at: str | None = None,
        last_error: str | None = None,
    ) -> None:
        with self._lock:
            records = {item.server_id: item for item in self.list()}
            current = records.get(server_id)
            if current is None:
                return
            value = current.public_dict()
            value.pop("token_configured", None)
            if last_connected_at is not None:
                value["last_connected_at"] = last_connected_at
            if last_error is not None:
                value["last_error"] = last_error[:240]
            records[server_id] = self._normalise(value)
            self._save_records(records.values())

    @staticmethod
    def _normalise(value: Mapping[str, Any]) -> MCPServerRecord:
        server_id = str(value["server_id"]).strip().lower()
        if _ID_RE.fullmatch(server_id) is None:
            raise ValueError(
                "MCP server ID must use lowercase letters, numbers, _ or -"
            )
        transport = str(value.get("transport", "http")).strip().lower()
        if transport not in {"http", "stdio"}:
            raise ValueError("MCP transport must be http or stdio")
        url = str(value.get("url", "")).strip()
        command = str(value.get("command", "")).strip()
        if transport == "http":
            from urllib.parse import urlsplit

            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("MCP HTTP URL must use http or https")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError(
                    "MCP URL must not contain credentials, query tokens or fragments"
                )
            if re.search(
                r"(?i)/(token|secret|private_|api[-_]?key)[^/]*",
                parsed.path,
            ):
                raise ValueError("MCP URL path appears to contain a credential")
            command = ""
        elif not command or not Path(command).is_absolute():
            raise ValueError("MCP stdio command must be an absolute executable path")
        else:
            url = ""
        args = tuple(str(item)[:512] for item in value.get("args", []))
        if len(args) > 32:
            raise ValueError("MCP stdio argument limit exceeded")
        if any(
            re.search(
                r"(?i)(authorization|bearer\s|api[-_]?key|access[-_]?token|password|secret)",
                argument,
            )
            for argument in args
        ):
            raise ValueError("MCP secrets must use token_env, not stdio arguments")
        token_env = str(value.get("token_env", "")).strip().upper()
        if token_env and _TOKEN_ENV_RE.fullmatch(token_env) is None:
            raise ValueError("MCP token reference must be MCP_*_API_KEY")
        policies = {
            str(name): str(policy)
            for name, policy in dict(value.get("tool_policies", {})).items()
        }
        include_tools = tuple(
            sorted({str(item) for item in value.get("include_tools", [])})
        )
        exclude_tools = tuple(
            sorted({str(item) for item in value.get("exclude_tools", [])})
        )
        if len(include_tools) > 512 or len(exclude_tools) > 512 or len(policies) > 512:
            raise ValueError("MCP tool policy limit exceeded")
        if any(
            _TOOL_NAME_RE.fullmatch(name) is None
            for name in (*include_tools, *exclude_tools, *policies)
        ):
            raise ValueError("MCP tool names contain unsupported characters")
        if any(policy not in _TOOL_POLICY_VALUES for policy in policies.values()):
            raise ValueError("unsupported MCP tool policy")
        return MCPServerRecord(
            server_id=server_id,
            label=str(value.get("label", server_id)).strip()[:120] or server_id,
            transport=transport,
            enabled=bool(value.get("enabled", True)),
            url=url,
            command=command,
            args=args,
            token_env=token_env,
            include_tools=include_tools,
            exclude_tools=exclude_tools,
            tool_policies=policies,
            last_connected_at=str(value.get("last_connected_at", ""))[:64],
            last_error=str(value.get("last_error", ""))[:240],
        )

    def _save_records(self, records) -> None:
        self._write(
            {
                "schema_version": 1,
                "servers": [
                    {
                        **item.public_dict(),
                        "token_configured": None,
                    }
                    for item in sorted(records, key=lambda record: record.server_id)
                ],
            }
        )

    def _write(self, payload: dict[str, Any]) -> None:
        for item in payload.get("servers", []):
            item.pop("token_configured", None)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["MCPServerRecord", "MCPServerRegistry"]
