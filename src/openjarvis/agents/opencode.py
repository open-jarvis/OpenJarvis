"""OpenCodeAgent -- wraps the `opencode` coding agent via its headless HTTP server.

Spawns ``opencode serve`` (https://opencode.ai) and drives a session over its
HTTP API, configured to use OpenJarvis's local engine through an
OpenAI-compatible provider. This keeps coding-agent work local-first: opencode
handles the agentic loop / tools, OpenJarvis supplies the model.

opencode is an external binary (install: ``npm i -g opencode-ai`` or
``brew install anomalyco/tap/opencode``). It is not bundled; :meth:`run`
raises a clear error if it is not on ``PATH``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

_LISTENING_RE = re.compile(r"listening on\s+(https?://\S+)", re.IGNORECASE)


def is_opencode_available() -> bool:
    """Return True if the ``opencode`` binary is on PATH."""
    return shutil.which("opencode") is not None


def _derive_openai_base_url(engine: Any) -> str:
    """Best-effort OpenAI-compatible base URL for an OpenJarvis engine.

    HTTP engines (Ollama, vLLM, llama.cpp, SGLang, LM Studio, …) expose a
    ``_host`` and serve an OpenAI-compatible API at ``<host>/v1``. Engines are
    often wrapped (e.g. ``InstrumentedEngine`` for telemetry stores the real
    engine at ``_inner``), so we unwrap a few layers to find the host. Returns
    "" when it cannot be derived (caller then needs an explicit base URL or a
    ``provider/model`` that opencode already knows).
    """
    seen: set[int] = set()
    cur = engine
    for _ in range(6):
        if cur is None or id(cur) in seen:
            break
        seen.add(id(cur))
        for attr in ("openai_base_url", "base_url"):
            val = getattr(cur, attr, "")
            if val:
                return str(val).rstrip("/")
        host = getattr(cur, "_host", "") or getattr(cur, "host", "")
        if host:
            host = str(host).rstrip("/")
            return host if host.endswith("/v1") else f"{host}/v1"
        # Unwrap common wrapper attributes (InstrumentedEngine -> _inner, etc.)
        cur = (
            getattr(cur, "_inner", None)
            or getattr(cur, "_engine", None)
            or getattr(cur, "_wrapped", None)
        )
    return ""


def _extract_text(parts: List[dict]) -> str:
    """Join the assistant's text parts from an opencode message response."""
    return "".join(
        p.get("text", "")
        for p in parts
        if isinstance(p, dict) and p.get("type") == "text"
    ).strip()


def _extract_tool_results(parts: List[dict]) -> List[ToolResult]:
    """Map opencode ``tool`` parts to OpenJarvis ToolResults (supports V1 and V2)."""
    results: List[ToolResult] = []
    for p in parts:
        if not isinstance(p, dict) or p.get("type") != "tool":
            continue
        state = p.get("state", {}) if isinstance(p.get("state"), dict) else {}
        status = state.get("status", "")
        output = state.get("output")
        if output is None and "content" in state:
            c = state["content"]
            if isinstance(c, list):
                output = "".join(
                    item.get("text", "") if isinstance(item, dict) else str(item)
                    for item in c
                ).strip()
            elif isinstance(c, dict):
                output = c.get("text", "") or str(c)
            else:
                output = str(c)
        if output is None:
            output = state.get("title", "") or (json.dumps(state) if state else "")
        results.append(
            ToolResult(
                tool_name=p.get("name") or p.get("tool") or "unknown",
                content=str(output),
                # opencode tool state: completed | error | running | pending
                success=status == "completed",
            )
        )
    return results


def _fetch_v2_messages(client: Any, session_id: str) -> List[dict]:
    """Read the entire V2 transcript in chronological order.

    V2 defaults to the newest 50 messages. Its cursor carries the ordering,
    so only the first request may specify ``order``. A cursor can point past
    the last message; an empty page terminates that traversal.
    """
    messages: List[dict] = []
    params: dict = {"order": "asc", "limit": 200}
    seen_cursors: set[str] = set()
    while True:
        response = client.get(f"/api/session/{session_id}/message", params=params)
        response.raise_for_status()
        body = response.json()
        page = body.get("data") if isinstance(body, dict) else None
        if not isinstance(page, list) or any(not isinstance(m, dict) for m in page):
            raise RuntimeError("OpenCode V2 returned an invalid transcript")
        messages.extend(page)
        if not page:
            return messages
        cursor = body.get("cursor", {})
        if not isinstance(cursor, dict):
            raise RuntimeError("OpenCode V2 returned an invalid transcript cursor")
        next_cursor = cursor.get("next")
        if next_cursor is None:
            return messages
        if not isinstance(next_cursor, str) or not next_cursor:
            raise RuntimeError("OpenCode V2 returned an invalid transcript cursor")
        if next_cursor in seen_cursors:
            raise RuntimeError("OpenCode V2 repeated a transcript cursor")
        seen_cursors.add(next_cursor)
        params = {"cursor": next_cursor, "limit": 200}


@AgentRegistry.register("opencode")
class OpenCodeAgent(BaseAgent):
    """Agent that delegates coding tasks to a local ``opencode`` server.

    The ``engine`` is used to wire opencode at an OpenAI-compatible provider so
    inference runs on OpenJarvis's selected local model. ``agent`` selects
    opencode's built-in agent: ``build`` (full access) or ``plan`` (read-only).
    Supports both OpenCode V1 and V2 (2.x) server APIs.
    """

    agent_id = "opencode"
    accepts_tools = False
    required_capabilities = ("code:execute", "file:read", "file:write")
    _default_temperature = 0.7
    _default_max_tokens = 1024

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        api_version: str = "auto",
        bus: Optional[EventBus] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        workspace: str = "",
        agent: str = "build",
        provider_id: str = "openjarvis",
        provider_base_url: str = "",
        model_id: str = "",
        api_key: str = "",
        permission: Optional[Any] = None,
        hostname: str = "127.0.0.1",
        port: int = 0,
        server_password: str = "",
        timeout: int = 600,
        opencode_bin: str = "",
        capability_policy: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        agent_id: Optional[str] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
            capability_policy=capability_policy,
            rate_limiter=rate_limiter,
            agent_id=agent_id,
        )
        if api_version not in ("auto", "v1", "v2"):
            raise ValueError(
                f"Invalid api_version {api_version!r}; expected 'auto', 'v1', or 'v2'"
            )
        self._api_version = api_version
        self._resolved_api_version: Optional[str] = (
            None if api_version == "auto" else api_version
        )
        self._current_session_id: Optional[str] = None
        self._workspace = workspace or os.getcwd()
        self._agent = agent
        self._provider_id = provider_id
        self._provider_base_url = provider_base_url or _derive_openai_base_url(engine)
        self._model_id = model_id or model
        self._api_key = api_key
        self._permission = permission
        self._hostname = hostname
        self._port = port
        # V2 always authenticates, generating a password when none is supplied.
        # Choose it here so the spawned server and our client share a credential
        # without reading or logging the server's generated password.
        self._server_password = (
            server_password
            or os.environ.get("OPENCODE_PASSWORD", "")
            or os.environ.get("OPENCODE_SERVER_PASSWORD", "")
            or secrets.token_urlsafe(32)
        )
        self._timeout = timeout
        self._opencode_bin = opencode_bin or shutil.which("opencode") or "opencode"
        self._proc: Optional[subprocess.Popen] = None
        self._base: str = ""
        self._config_dir: Optional[str] = None

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    def _default_permission(self) -> dict:
        """Deterministic, hang-proof permission policy for headless use.

        opencode's interactive default *asks* before some actions (and ``plan``
        asks before bash) — that would block forever with no TTY. We set
        explicit ``allow``/``deny`` so the server never waits on a prompt:

        - ``build``: allow edits + bash (a coding agent the user invoked).
        - ``plan``: deny edits + bash (read-only), matching opencode's intent.
        """
        if self._agent == "plan":
            return {"edit": "deny", "bash": "deny", "webfetch": "allow"}
        return {"edit": "allow", "bash": "allow", "webfetch": "allow"}

    def _build_config(self) -> dict:
        """Build the opencode config (provider wiring + permission policy)."""
        cfg: dict = {
            "$schema": "https://opencode.ai/config.json",
            "permission": self._permission or self._default_permission(),
        }
        if self._provider_base_url:
            options: dict = {"baseURL": self._provider_base_url}
            if self._api_key:
                options["apiKey"] = self._api_key
            cfg["provider"] = {
                self._provider_id: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": "OpenJarvis Local",
                    "options": options,
                    "models": {self._model_id: {"name": self._model_id}},
                }
            }
        return cfg

    def _ensure_server(self) -> str:
        """Spawn ``opencode serve`` (once) and return its base URL."""
        if self._base and self._proc and self._proc.poll() is None:
            return self._base
        if not is_opencode_available() and not Path(self._opencode_bin).exists():
            raise RuntimeError(
                "OpenCodeAgent requires the 'opencode' binary. Install it with "
                "`npm i -g opencode-ai` or `brew install anomalyco/tap/opencode` "
                "(see https://opencode.ai)."
            )
        # Write our config to a private file referenced via OPENCODE_CONFIG, so
        # the engine provider + permission policy apply WITHOUT writing an
        # opencode.json into the user's workspace.
        import tempfile

        self._config_dir = tempfile.mkdtemp(prefix="openjarvis-opencode-")
        config_path = Path(self._config_dir) / "opencode.json"
        config_path.write_text(json.dumps(self._build_config(), indent=2), "utf-8")
        env = dict(os.environ)
        env["OPENCODE_CONFIG"] = str(config_path)
        # V1 uses the legacy name; V2 prefers OPENCODE_PASSWORD. Set both so an
        # inherited value cannot override an explicitly supplied password.
        env["OPENCODE_PASSWORD"] = self._server_password
        env["OPENCODE_SERVER_PASSWORD"] = self._server_password
        self._proc = subprocess.Popen(
            [
                self._opencode_bin,
                "serve",
                "--port",
                str(self._port),
                "--hostname",
                self._hostname,
            ],
            cwd=self._workspace,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # Parse the "listening on <url>" line from startup output.
        deadline = time.monotonic() + 60
        base = ""
        assert self._proc.stdout is not None
        while time.monotonic() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                if self._proc.poll() is not None:
                    raise RuntimeError("opencode server exited during startup")
                continue
            m = _LISTENING_RE.search(line)
            if m:
                base = m.group(1).rstrip("/")
                break
        if not base:
            self.close()
            raise RuntimeError("opencode server did not report a listening URL")
        self._base = base
        return base

    def _client(self):
        import httpx

        headers = {}
        if self._server_password:
            import base64

            token = base64.b64encode(
                f"opencode:{self._server_password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"
        return httpx.Client(base_url=self._base, headers=headers, timeout=self._timeout)

    def close(self) -> None:
        """Dispose the opencode session/server and terminate the process."""
        if self._base:
            try:
                with self._client() as c:
                    if self._resolved_api_version == "v2" and self._current_session_id:
                        c.delete(f"/api/session/{self._current_session_id}")
                    c.post("/global/dispose")
            except Exception:
                pass
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        self._base = ""
        self._current_session_id = None
        if self._api_version == "auto":
            self._resolved_api_version = None
        if self._config_dir:
            shutil.rmtree(self._config_dir, ignore_errors=True)
            self._config_dir = None

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Run a coding task through opencode and return the assistant result."""
        denied = self._execution_denied_result()
        if denied is not None:
            return denied
        self._emit_turn_start(input)

        # Resolve which opencode provider/model to address. Fail clearly rather
        # than letting opencode 500 on an unregistered provider.
        if self._provider_base_url:
            prov, mid = self._provider_id, self._model_id
        elif "/" in self._model_id:
            prov, _, mid = self._model_id.partition("/")
        else:
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=(
                    f"OpenCodeAgent could not determine an opencode provider for "
                    f"model {self._model_id!r}: no OpenAI-compatible base URL could "
                    f"be derived from the engine. Pass provider_base_url=..., or use "
                    f"a 'provider/model' that opencode already knows."
                ),
                turns=1,
                metadata={"error": True},
            )

        model_spec_v1 = {"providerID": prov, "modelID": mid}
        model_spec_v2 = {"providerID": prov, "id": mid}

        try:
            self._ensure_server()
        except RuntimeError as exc:
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(content=str(exc), turns=1, metadata={"error": True})

        data: dict = {}
        turn_parts: List[dict] = []
        active_version = self._resolved_api_version or "v1"
        session_id = ""

        try:
            with self._client() as c:
                version = self._resolved_api_version

                # Session creation with auto-fallback
                if version == "v2":
                    ses = c.post(
                        "/api/session",
                        json={
                            "title": input[:80],
                            "agent": self._agent,
                            "model": model_spec_v2,
                        },
                    )
                    ses.raise_for_status()
                    ses_data = ses.json()
                    session_id = ses_data.get("id") or (ses_data.get("data") or {}).get(
                        "id"
                    )
                elif version == "v1":
                    ses = c.post("/session", json={"title": input[:80]})
                    ses.raise_for_status()
                    session_id = ses.json().get("id")
                else:
                    # auto-detection: try V1 first, fallback to V2 on 404
                    try:
                        ses = c.post("/session", json={"title": input[:80]})
                        ses.raise_for_status()
                        session_id = ses.json().get("id")
                        self._resolved_api_version = "v1"
                    except Exception as ses_exc:
                        status = getattr(
                            getattr(ses_exc, "response", None), "status_code", None
                        )
                        if status == 404:
                            logger.info(
                                "OpenCode /session returned 404; "
                                "falling back to /api/session (v2)"
                            )
                            ses = c.post(
                                "/api/session",
                                json={
                                    "title": input[:80],
                                    "agent": self._agent,
                                    "model": model_spec_v2,
                                },
                            )
                            ses.raise_for_status()
                            ses_data = ses.json()
                            session_id = ses_data.get("id") or (
                                ses_data.get("data") or {}
                            ).get("id")
                            self._resolved_api_version = "v2"
                        else:
                            raise

                if not session_id:
                    raise RuntimeError(
                        "Could not obtain session ID from opencode server"
                    )
                self._current_session_id = session_id
                active_version = self._resolved_api_version or "v1"

                # Prompt / message dispatch
                if active_version == "v2":
                    resp = c.post(
                        f"/api/session/{session_id}/prompt",
                        json={"text": input},
                    )
                    resp.raise_for_status()

                    # V2 admits a queued user input, not a completed assistant
                    # reply. Both synchronization and transcript retrieval must
                    # succeed before we can report a completed turn.
                    wait = c.post(f"/api/experimental/session/{session_id}/wait")
                    wait.raise_for_status()
                    terminal: Optional[dict] = None
                    for message in _fetch_v2_messages(c, session_id):
                        if message.get("type") == "idle":
                            terminal = message
                            continue
                        if message.get("type") != "assistant":
                            continue
                        terminal = None
                        parts = message.get("content")
                        if not isinstance(parts, list):
                            raise RuntimeError(
                                "OpenCode V2 returned invalid assistant content"
                            )
                        turn_parts.extend(parts)
                        data = message
                    if not data:
                        raise RuntimeError(
                            "OpenCode V2 completed without an assistant reply"
                        )
                    # The wait route reports idle even when execution failed.
                    # The terminal transcript marker records the actual outcome;
                    # a provider finish reason alone does not describe the turn.
                    if terminal is None:
                        raise RuntimeError(
                            "OpenCode V2 returned an incomplete turn transcript"
                        )
                    if terminal.get("outcome") != "succeeded" or terminal.get("error"):
                        error = terminal.get("error")
                        detail = (
                            error.get("message", "Turn failed")
                            if isinstance(error, dict)
                            else f"Turn {terminal.get('outcome', 'did not complete')}"
                        )
                        raise RuntimeError(f"OpenCode V2 failed: {detail}")
                    if data.get("error") or data.get("finish") in (
                        "error",
                        "content-filter",
                    ):
                        error = data.get("error")
                        detail = (
                            error.get("message", "Assistant generation failed")
                            if isinstance(error, dict)
                            else "Assistant generation failed"
                        )
                        raise RuntimeError(f"OpenCode V2 assistant failed: {detail}")
                    if data.get("finish") not in ("stop", "length", "tool-calls"):
                        raise RuntimeError(
                            "OpenCode V2 returned an unfinished assistant reply"
                        )
                else:
                    body: dict = {
                        "agent": self._agent,
                        "model": model_spec_v1,
                        "parts": [{"type": "text", "text": input}],
                    }
                    resp = c.post(f"/session/{session_id}/message", json=body)
                    resp.raise_for_status()
                    data = resp.json()

                    turn_parts = list(data.get("parts", []))
                    try:
                        msgs = c.get(f"/session/{session_id}/message").json()
                        if isinstance(msgs, list):
                            turn_parts = [
                                part
                                for mm in msgs
                                if isinstance(mm, dict)
                                for part in (mm.get("parts") or mm.get("content") or [])
                            ]
                    except Exception as get_exc:
                        logger.debug("opencode message fetch failed: %s", get_exc)
        except Exception as exc:
            logger.error("opencode run failed: %s", exc, exc_info=True)
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=f"opencode agent failed: {exc}",
                turns=1,
                metadata={"error": True},
            )

        info = data.get("info", {}) if isinstance(data, dict) else {}
        model_obj = data.get("model", {}) if isinstance(data.get("model"), dict) else {}
        final_parts = data.get("content") or data.get("parts") or []
        content = (
            _extract_text(final_parts)
            if isinstance(final_parts, list)
            else (data.get("text", "") if isinstance(data, dict) else "")
        )
        tool_results = _extract_tool_results(turn_parts)

        self._emit_turn_end(turns=1)
        return AgentResult(
            content=content,
            tool_results=tool_results,
            turns=1,
            metadata={
                "finish": data.get("finish") or info.get("finish"),
                "tokens": data.get("tokens") or info.get("tokens"),
                "provider_id": (
                    model_obj.get("providerID") or info.get("providerID", prov)
                ),
                "model_id": (
                    model_obj.get("id")
                    or model_obj.get("modelID")
                    or info.get("modelID", mid)
                ),
                "session_id": (
                    data.get("sessionID") or info.get("sessionID", session_id or "")
                ),
                "agent": data.get("agent") or self._agent,
                "api_version": active_version,
            },
        )


__all__ = ["OpenCodeAgent", "is_opencode_available"]
