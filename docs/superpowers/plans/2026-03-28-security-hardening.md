# Security Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden OpenJarvis against network exposure, data leakage to cloud providers, local data exposure, and webhook spoofing — using layered boundary enforcement at device exit points.

**Architecture:** A `BoundaryGuard` wraps all exit points (cloud engines, external tools, webhooks). Config defaults change to secure values (`127.0.0.1` binding, `redact` mode, rate limiting on). File permissions enforced via shared helpers. Security profiles provide convenience shorthand. Each section is implemented and tested independently in severity order.

**Tech Stack:** Python 3.10+, FastAPI/Starlette, SQLite, pytest, existing Rust-backed SecretScanner/PIIScanner.

**Spec:** `docs/superpowers/specs/2026-03-28-security-hardening-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `src/openjarvis/security/boundary.py` | BoundaryGuard — scans content at device exit points |
| `src/openjarvis/security/file_utils.py` | `secure_mkdir()` and `secure_create()` helpers |
| `tests/security/test_network_defaults.py` | Tests for Section 1 (binding, CORS, auth enforcement) |
| `tests/security/test_boundary_guard.py` | Tests for Section 2 (scan/redact, engine/tool tagging) |
| `tests/security/test_webhook_validation.py` | Tests for Section 3 (fail-closed, secret enforcement) |
| `tests/security/test_file_permissions.py` | Tests for Section 4 (secure_mkdir, secure_create, DB paths) |
| `tests/security/test_log_sanitization.py` | Tests for Section 5 (SanitizingFormatter, scoped credentials) |
| `tests/security/test_security_profiles.py` | Tests for Section 7 (profile field expansion, overrides) |

### Modified Files
| File | Change |
|------|--------|
| `src/openjarvis/core/config.py` | ServerConfig defaults, SecurityConfig defaults, new fields, profile expansion |
| `src/openjarvis/server/app.py` | CORS from config, startup guards |
| `src/openjarvis/server/auth_middleware.py` | Non-loopback auth enforcement |
| `src/openjarvis/server/webhook_routes.py` | Fail-closed validation |
| `src/openjarvis/server/middleware.py` | CSP header |
| `src/openjarvis/engine/_stubs.py` | `is_cloud` attribute on InferenceEngine |
| `src/openjarvis/engine/cloud.py` | `is_cloud = True` |
| `src/openjarvis/engine/litellm.py` | `is_cloud = True` |
| `src/openjarvis/tools/_stubs.py` | `is_local` attribute on BaseTool, BoundaryGuard in ToolExecutor |
| `src/openjarvis/tools/web_search.py` | `is_local = False` |
| `src/openjarvis/tools/http_request.py` | `is_local = False` |
| `src/openjarvis/tools/browser.py` | `is_local = False` on all browser tools |
| `src/openjarvis/tools/browser_axtree.py` | `is_local = False` |
| `src/openjarvis/tools/channel_tools.py` | `is_local = False` on ChannelSendTool |
| `src/openjarvis/tools/image_tool.py` | `is_local = False` |
| `src/openjarvis/tools/audio_tool.py` | `is_local = False` |
| `src/openjarvis/security/guardrails.py` | Delegate to BoundaryGuard |
| `src/openjarvis/tools/storage/sqlite.py` | secure_create for memory.db |
| `src/openjarvis/server/session_store.py` | secure_create for sessions.db |
| `src/openjarvis/traces/store.py` | secure_create for traces.db |
| `src/openjarvis/security/audit.py` | secure_create for audit.db |
| `src/openjarvis/connectors/store.py` | secure_create for knowledge.db |
| `src/openjarvis/connectors/attachment_store.py` | secure_mkdir/secure_create for blobs |
| `src/openjarvis/core/credentials.py` | `get_tool_credential()`, deprecate `inject_credentials()` |
| `src/openjarvis/cli/log_config.py` | SanitizingFormatter |
| `src/openjarvis/cli/serve.py` | Startup guards, credential audit log |
| `src/openjarvis/cli/doctor_cmd.py` | Security profile check |
| `src/openjarvis/system.py` | BoundaryGuard wiring |

---

## Task 1: Network Exposure — Secure Server Defaults

**Files:**
- Modify: `src/openjarvis/core/config.py:759-767` (ServerConfig)
- Modify: `src/openjarvis/core/config.py:968-986` (SecurityConfig)
- Test: `tests/security/test_network_defaults.py`

- [ ] **Step 1: Write failing tests for secure defaults**

```python
# tests/security/test_network_defaults.py
"""Tests for secure network defaults (Section 1 of security hardening)."""

from __future__ import annotations


class TestServerConfigDefaults:
    """ServerConfig should bind to loopback by default."""

    def test_default_host_is_loopback(self) -> None:
        from openjarvis.core.config import ServerConfig

        cfg = ServerConfig()
        assert cfg.host == "127.0.0.1"

    def test_default_port_unchanged(self) -> None:
        from openjarvis.core.config import ServerConfig

        cfg = ServerConfig()
        assert cfg.port == 8000

    def test_cors_origins_default(self) -> None:
        from openjarvis.core.config import ServerConfig

        cfg = ServerConfig()
        assert isinstance(cfg.cors_origins, list)
        assert "http://localhost:3000" in cfg.cors_origins
        assert "http://localhost:5173" in cfg.cors_origins
        assert "tauri://localhost" in cfg.cors_origins
        assert "*" not in cfg.cors_origins


class TestSecurityConfigDefaults:
    """SecurityConfig should default to redact mode with rate limiting."""

    def test_default_mode_is_redact(self) -> None:
        from openjarvis.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.mode == "redact"

    def test_rate_limiting_enabled_by_default(self) -> None:
        from openjarvis.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.rate_limit_enabled is True

    def test_bypass_defaults_conservative(self) -> None:
        from openjarvis.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.local_engine_bypass is False
        assert cfg.local_tool_bypass is False

    def test_profile_default_empty(self) -> None:
        from openjarvis.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.profile == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_network_defaults.py -v`
Expected: FAIL — `ServerConfig` has `host="0.0.0.0"`, no `cors_origins` field, `SecurityConfig` has `mode="warn"`, `rate_limit_enabled=False`, no `local_engine_bypass`/`local_tool_bypass`/`profile` fields.

- [ ] **Step 3: Update ServerConfig defaults**

In `src/openjarvis/core/config.py`, replace the `ServerConfig` dataclass (lines 759-767):

```python
@dataclass(slots=True)
class ServerConfig:
    """API server settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    agent: str = "orchestrator"
    model: str = ""
    workers: int = 1
    cors_origins: list = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "tauri://localhost",
        ]
    )
```

- [ ] **Step 4: Update SecurityConfig defaults**

In `src/openjarvis/core/config.py`, replace the `SecurityConfig` dataclass (lines 968-986):

```python
@dataclass(slots=True)
class SecurityConfig:
    """Security guardrails settings."""

    enabled: bool = True
    scan_input: bool = True
    scan_output: bool = True
    mode: str = "redact"  # "redact" | "warn" | "block"
    secret_scanner: bool = True
    pii_scanner: bool = True
    audit_log_path: str = str(DEFAULT_CONFIG_DIR / "audit.db")
    enforce_tool_confirmation: bool = True
    merkle_audit: bool = True
    signing_key_path: str = ""
    ssrf_protection: bool = True
    rate_limit_enabled: bool = True
    rate_limit_rpm: int = 60
    rate_limit_burst: int = 10
    local_engine_bypass: bool = False
    local_tool_bypass: bool = False
    profile: str = ""
    vault_key_path: str = str(DEFAULT_CONFIG_DIR / ".vault_key")
    capabilities: CapabilitiesConfig = field(default_factory=CapabilitiesConfig)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_network_defaults.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/security/test_network_defaults.py src/openjarvis/core/config.py
git commit -m "feat: secure server defaults — loopback binding, redact mode, rate limiting"
```

---

## Task 2: Network Exposure — Non-Loopback Auth Enforcement & CORS

**Files:**
- Modify: `src/openjarvis/cli/serve.py:68-69` (bind resolution) and `337-352` (API key loading)
- Modify: `src/openjarvis/server/app.py:182-188` (CORS)
- Test: `tests/security/test_network_defaults.py` (add more tests)

- [ ] **Step 1: Write failing tests for non-loopback auth and CORS**

Append to `tests/security/test_network_defaults.py`:

```python
import ipaddress


def _is_loopback(host: str) -> bool:
    """Check if a host string is a loopback address."""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "")


class TestNonLoopbackAuthEnforcement:
    """Server must require API key when binding non-loopback."""

    def test_loopback_allows_no_key(self) -> None:
        """127.0.0.1 should not require an API key."""
        assert _is_loopback("127.0.0.1")

    def test_wildcard_is_not_loopback(self) -> None:
        """0.0.0.0 should be treated as non-loopback."""
        assert not _is_loopback("0.0.0.0")

    def test_non_loopback_requires_key(self) -> None:
        """Binding to 0.0.0.0 without API key should raise."""
        from openjarvis.server.auth_middleware import check_bind_safety

        try:
            check_bind_safety("0.0.0.0", api_key="")
            assert False, "Should have raised"
        except SystemExit:
            pass

    def test_non_loopback_with_key_ok(self) -> None:
        """Binding to 0.0.0.0 with API key should succeed."""
        from openjarvis.server.auth_middleware import check_bind_safety

        # Should not raise
        check_bind_safety("0.0.0.0", api_key="oj_sk_test123")


class TestCORSConfiguration:
    """CORS should use configured origins, not wildcard."""

    def test_create_app_uses_configured_origins(self) -> None:
        """create_app should pass cors_origins from config, not '*'."""
        # This test verifies the integration — we check that the app
        # responds with the correct Access-Control-Allow-Origin.
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from openjarvis.server.app import create_app

        mock_engine = MagicMock()
        mock_engine.health.return_value = True
        mock_engine.list_models.return_value = ["test-model"]

        app = create_app(
            mock_engine,
            "test-model",
            cors_origins=["http://localhost:3000"],
        )
        client = TestClient(app)

        # Request from allowed origin
        resp = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

        # Request from disallowed origin should not get CORS header
        resp2 = client.options(
            "/health",
            headers={
                "Origin": "http://evil.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp2.headers.get("access-control-allow-origin") != "http://evil.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_network_defaults.py::TestNonLoopbackAuthEnforcement -v`
Expected: FAIL — `check_bind_safety` does not exist yet.

Run: `uv run pytest tests/security/test_network_defaults.py::TestCORSConfiguration -v`
Expected: FAIL — `create_app` does not accept `cors_origins` parameter.

- [ ] **Step 3: Add `check_bind_safety` to auth_middleware.py**

In `src/openjarvis/server/auth_middleware.py`, add after the `generate_api_key()` function (after line 58):

```python
def check_bind_safety(host: str, *, api_key: str) -> None:
    """Refuse to bind non-loopback without an API key.

    Raises ``SystemExit`` if *host* is not a loopback address and
    *api_key* is empty.
    """
    import ipaddress
    import sys

    try:
        is_loop = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loop = host in ("localhost", "")

    if not is_loop and not api_key:
        logger.error(
            "Binding to %s requires OPENJARVIS_API_KEY to be set. "
            "Run: jarvis auth generate-key",
            host,
        )
        sys.exit(1)
```

- [ ] **Step 4: Update `create_app` to accept and use `cors_origins`**

In `src/openjarvis/server/app.py`, add `cors_origins: list[str] | None = None` to the `create_app()` signature (line 140).

Replace the CORS middleware block (lines 182-188):

```python
    from fastapi.middleware.cors import CORSMiddleware

    _origins = cors_origins if cors_origins is not None else ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

- [ ] **Step 5: Wire `check_bind_safety` and `cors_origins` in `serve.py`**

In `src/openjarvis/cli/serve.py`, after API key resolution (around line 352), add:

```python
    from openjarvis.server.auth_middleware import check_bind_safety

    check_bind_safety(bind_host, api_key=api_key)
```

In the `create_app()` call (around line 383), add the `cors_origins` kwarg:

```python
    app = create_app(
        engine,
        model_name,
        # ... existing kwargs ...
        cors_origins=config.server.cors_origins,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_network_defaults.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/server/auth_middleware.py src/openjarvis/server/app.py src/openjarvis/cli/serve.py tests/security/test_network_defaults.py
git commit -m "feat: enforce API key for non-loopback binding, restrict CORS origins"
```

---

## Task 3: Boundary Guard — Core Module

**Files:**
- Create: `src/openjarvis/security/boundary.py`
- Test: `tests/security/test_boundary_guard.py`

- [ ] **Step 1: Write failing tests for BoundaryGuard**

```python
# tests/security/test_boundary_guard.py
"""Tests for BoundaryGuard — scanning at device exit points."""

from __future__ import annotations

import pytest

from openjarvis.core.types import ToolCall


class TestBoundaryGuardScanOutbound:
    """scan_outbound should detect and redact secrets/PII."""

    def test_redacts_openai_key(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard

        guard = BoundaryGuard(mode="redact")
        text = "Use this key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        result = guard.scan_outbound(text, destination="openai")
        assert "sk-proj-" not in result
        assert "[REDACTED" in result

    def test_redacts_aws_key(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard

        guard = BoundaryGuard(mode="redact")
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = guard.scan_outbound(text, destination="openai")
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_warn_mode_does_not_alter_text(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard

        guard = BoundaryGuard(mode="warn")
        text = "Use this key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        result = guard.scan_outbound(text, destination="openai")
        assert result == text

    def test_block_mode_raises(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard, SecurityBlockError

        guard = BoundaryGuard(mode="block")
        text = "Use this key: sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        with pytest.raises(SecurityBlockError):
            guard.scan_outbound(text, destination="openai")

    def test_clean_text_passes_through(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard

        guard = BoundaryGuard(mode="redact")
        text = "Hello, how are you?"
        result = guard.scan_outbound(text, destination="openai")
        assert result == text


class TestBoundaryGuardCheckOutbound:
    """check_outbound should redact secrets in tool call arguments."""

    def test_redacts_tool_call_arguments(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard

        guard = BoundaryGuard(mode="redact")
        tc = ToolCall(
            id="test_1",
            name="web_search",
            arguments='{"query": "my key is sk-proj-abc123def456ghi789jkl012mno345pqr678stu"}',
        )
        result = guard.check_outbound(tc)
        assert "sk-proj-" not in result.arguments
        assert result.id == "test_1"
        assert result.name == "web_search"

    def test_clean_args_pass_through(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard

        guard = BoundaryGuard(mode="redact")
        tc = ToolCall(id="test_2", name="web_search", arguments='{"query": "weather"}')
        result = guard.check_outbound(tc)
        assert result.arguments == tc.arguments

    def test_block_mode_raises_on_tool_call(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard, SecurityBlockError

        guard = BoundaryGuard(mode="block")
        tc = ToolCall(
            id="test_3",
            name="web_search",
            arguments='{"query": "AKIAIOSFODNN7EXAMPLE"}',
        )
        with pytest.raises(SecurityBlockError):
            guard.check_outbound(tc)


class TestBoundaryGuardDisabled:
    """When disabled, BoundaryGuard should pass everything through."""

    def test_disabled_passes_secrets_through(self) -> None:
        from openjarvis.security.boundary import BoundaryGuard

        guard = BoundaryGuard(mode="redact", enabled=False)
        text = "sk-proj-abc123def456ghi789jkl012mno345pqr678stu"
        result = guard.scan_outbound(text, destination="openai")
        assert result == text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_boundary_guard.py -v`
Expected: FAIL — `openjarvis.security.boundary` does not exist.

- [ ] **Step 3: Implement BoundaryGuard**

```python
# src/openjarvis/security/boundary.py
"""BoundaryGuard — scans content at device exit points.

Wraps SecretScanner and PIIScanner to redact, warn, or block
secrets and PII before data leaves the device via cloud engines
or external tool calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, List, Optional

from openjarvis.core.types import ToolCall

if TYPE_CHECKING:
    from openjarvis.core.events import EventBus
    from openjarvis.security.scanner import BaseScanner

logger = logging.getLogger(__name__)


class SecurityBlockError(Exception):
    """Raised when mode='block' and secrets/PII are detected."""


@dataclass(slots=True)
class ScanFinding:
    """A single finding from a boundary scan."""

    pattern_name: str
    destination: str


class BoundaryGuard:
    """Scans outbound content for secrets and PII at device boundaries.

    Parameters
    ----------
    mode:
        Action on findings: ``"redact"`` replaces matches,
        ``"warn"`` logs but passes through, ``"block"`` raises.
    enabled:
        Master switch. When ``False``, all content passes through.
    bus:
        Optional event bus for publishing SECURITY_ALERT events.
    scanners:
        Custom scanners. Defaults to SecretScanner + PIIScanner.
    """

    def __init__(
        self,
        mode: str = "redact",
        *,
        enabled: bool = True,
        bus: Optional["EventBus"] = None,
        scanners: Optional[List["BaseScanner"]] = None,
    ) -> None:
        self._mode = mode
        self._enabled = enabled
        self._bus = bus
        if scanners is not None:
            self._scanners = scanners
        else:
            self._scanners = self._default_scanners()

    @staticmethod
    def _default_scanners() -> List["BaseScanner"]:
        from openjarvis.security.scanner import PIIScanner, SecretScanner

        return [SecretScanner(), PIIScanner()]

    def scan_outbound(self, content: str, destination: str) -> str:
        """Scan text before it leaves the device.

        Returns redacted text in ``"redact"`` mode, original text in
        ``"warn"`` mode, or raises ``SecurityBlockError`` in ``"block"``
        mode when findings are detected.
        """
        if not self._enabled or not content:
            return content

        has_findings = False
        redacted = content
        for scanner in self._scanners:
            result = scanner.scan(content)
            if result.findings:
                has_findings = True
                if self._mode == "redact":
                    redacted = scanner.redact(redacted)

        if has_findings:
            self._emit_alert(destination, content)
            if self._mode == "block":
                raise SecurityBlockError(
                    f"Secrets/PII detected in outbound content to {destination}"
                )
            if self._mode == "warn":
                logger.warning(
                    "Secrets/PII detected in outbound content to %s", destination
                )
                return content
            return redacted

        return content

    def check_outbound(self, tool_call: ToolCall) -> ToolCall:
        """Scan tool call arguments before execution.

        Returns a new ToolCall with redacted arguments if needed.
        """
        if not self._enabled or not tool_call.arguments:
            return tool_call

        redacted_args = self.scan_outbound(
            tool_call.arguments, destination=f"tool:{tool_call.name}"
        )
        if redacted_args != tool_call.arguments:
            return replace(tool_call, arguments=redacted_args)
        return tool_call

    def _emit_alert(self, destination: str, content: str) -> None:
        if self._bus is None:
            return
        try:
            from openjarvis.core.events import EventType

            self._bus.publish(
                EventType.SECURITY_ALERT,
                {
                    "source": "boundary_guard",
                    "destination": destination,
                    "mode": self._mode,
                    "content_preview": content[:80],
                },
            )
        except Exception:
            logger.debug("Failed to emit security alert event", exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_boundary_guard.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/security/boundary.py tests/security/test_boundary_guard.py
git commit -m "feat: BoundaryGuard module — scan/redact/block at device exit points"
```

---

## Task 4: Boundary Guard — Engine & Tool Tagging

**Files:**
- Modify: `src/openjarvis/engine/_stubs.py:48-120` (InferenceEngine ABC)
- Modify: `src/openjarvis/engine/cloud.py:211` (CloudEngine)
- Modify: `src/openjarvis/engine/litellm.py:16` (LiteLLMEngine)
- Modify: `src/openjarvis/tools/_stubs.py:46-74` (BaseTool ABC)
- Modify: `src/openjarvis/tools/web_search.py` (WebSearchTool)
- Modify: `src/openjarvis/tools/http_request.py` (HttpRequestTool)
- Modify: `src/openjarvis/tools/browser.py` (BrowserNavigateTool and others)
- Modify: `src/openjarvis/tools/browser_axtree.py` (BrowserAXTreeTool)
- Modify: `src/openjarvis/tools/channel_tools.py` (ChannelSendTool)
- Modify: `src/openjarvis/tools/image_tool.py` (ImageGenerateTool)
- Modify: `src/openjarvis/tools/audio_tool.py` (AudioTranscribeTool)
- Test: `tests/security/test_boundary_guard.py` (extend)

- [ ] **Step 1: Write failing tests for engine and tool tagging**

Append to `tests/security/test_boundary_guard.py`:

```python
class TestEngineTagging:
    """Cloud engines must have is_cloud=True, local engines is_cloud=False."""

    def test_inference_engine_default_is_local(self) -> None:
        from openjarvis.engine._stubs import InferenceEngine

        assert InferenceEngine.is_cloud is False

    def test_cloud_engine_is_cloud(self) -> None:
        from openjarvis.engine.cloud import CloudEngine

        assert CloudEngine.is_cloud is True

    def test_litellm_engine_is_cloud(self) -> None:
        from openjarvis.engine.litellm import LiteLLMEngine

        assert LiteLLMEngine.is_cloud is True

    def test_ollama_engine_is_local(self) -> None:
        from openjarvis.engine.ollama import OllamaEngine

        assert OllamaEngine.is_cloud is False


class TestToolTagging:
    """External tools must have is_local=False, local tools is_local=True."""

    def test_base_tool_default_is_local(self) -> None:
        from openjarvis.tools._stubs import BaseTool

        assert BaseTool.is_local is True

    def test_web_search_is_external(self) -> None:
        from openjarvis.tools.web_search import WebSearchTool

        assert WebSearchTool.is_local is False

    def test_http_request_is_external(self) -> None:
        from openjarvis.tools.http_request import HttpRequestTool

        assert HttpRequestTool.is_local is False

    def test_channel_send_is_external(self) -> None:
        from openjarvis.tools.channel_tools import ChannelSendTool

        assert ChannelSendTool.is_local is False

    def test_think_tool_is_local(self) -> None:
        from openjarvis.tools.think import ThinkTool

        assert ThinkTool.is_local is True

    def test_calculator_is_local(self) -> None:
        from openjarvis.tools.calculator import CalculatorTool

        assert CalculatorTool.is_local is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_boundary_guard.py::TestEngineTagging -v`
Expected: FAIL — `InferenceEngine` has no `is_cloud` attribute.

Run: `uv run pytest tests/security/test_boundary_guard.py::TestToolTagging -v`
Expected: FAIL — `BaseTool` has no `is_local` attribute.

- [ ] **Step 3: Add `is_cloud` to InferenceEngine ABC**

In `src/openjarvis/engine/_stubs.py`, add to the `InferenceEngine` class body (after `engine_id: str`, around line 55):

```python
    is_cloud: bool = False
```

- [ ] **Step 4: Set `is_cloud = True` on cloud engines**

In `src/openjarvis/engine/cloud.py`, add to the `CloudEngine` class body (after `engine_id = "cloud"`, around line 216):

```python
    is_cloud = True
```

In `src/openjarvis/engine/litellm.py`, add to the `LiteLLMEngine` class body (after `engine_id = "litellm"`, around line 30):

```python
    is_cloud = True
```

- [ ] **Step 5: Add `is_local` to BaseTool ABC**

In `src/openjarvis/tools/_stubs.py`, add to the `BaseTool` class body (after `tool_id: str`, around line 53):

```python
    is_local: bool = True
```

- [ ] **Step 6: Set `is_local = False` on external tools**

In each of these files, add `is_local = False` to the class body (after `tool_id = "..."`):

- `src/openjarvis/tools/web_search.py` — `WebSearchTool`
- `src/openjarvis/tools/http_request.py` — `HttpRequestTool`
- `src/openjarvis/tools/browser.py` — `BrowserNavigateTool`, `BrowserClickTool`, `BrowserTypeTool`, `BrowserScreenshotTool`, `BrowserExtractTool`
- `src/openjarvis/tools/browser_axtree.py` — `BrowserAXTreeTool`
- `src/openjarvis/tools/channel_tools.py` — `ChannelSendTool`
- `src/openjarvis/tools/image_tool.py` — `ImageGenerateTool`
- `src/openjarvis/tools/audio_tool.py` — `AudioTranscribeTool`

Example for `WebSearchTool`:
```python
@ToolRegistry.register("web_search")
class WebSearchTool(BaseTool):
    tool_id = "web_search"
    is_local = False
    # ... rest unchanged
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_boundary_guard.py -v`
Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add src/openjarvis/engine/_stubs.py src/openjarvis/engine/cloud.py src/openjarvis/engine/litellm.py src/openjarvis/tools/_stubs.py src/openjarvis/tools/web_search.py src/openjarvis/tools/http_request.py src/openjarvis/tools/browser.py src/openjarvis/tools/browser_axtree.py src/openjarvis/tools/channel_tools.py src/openjarvis/tools/image_tool.py src/openjarvis/tools/audio_tool.py tests/security/test_boundary_guard.py
git commit -m "feat: tag engines with is_cloud and tools with is_local for boundary scanning"
```

---

## Task 5: Boundary Guard — Wire into ToolExecutor and GuardrailsEngine

**Files:**
- Modify: `src/openjarvis/tools/_stubs.py:112-266` (ToolExecutor.execute)
- Modify: `src/openjarvis/security/guardrails.py:20-70` (GuardrailsEngine)
- Modify: `src/openjarvis/system.py:18-52` (JarvisSystem)
- Test: `tests/security/test_boundary_guard.py` (extend)

- [ ] **Step 1: Write failing tests for ToolExecutor integration**

Append to `tests/security/test_boundary_guard.py`:

```python
from unittest.mock import MagicMock


class TestToolExecutorBoundaryIntegration:
    """ToolExecutor should use BoundaryGuard for external tool calls."""

    def _make_executor(self, boundary_guard=None):
        from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec

        class FakeExternalTool(BaseTool):
            tool_id = "fake_external"
            is_local = False

            @property
            def spec(self):
                return ToolSpec(
                    name="fake_external",
                    description="test",
                    parameters={"type": "object", "properties": {"q": {"type": "string"}}},
                )

            def execute(self, **params):
                from openjarvis.core.types import ToolResult

                return ToolResult(
                    tool_name="fake_external",
                    content=f"result for {params.get('q', '')}",
                    success=True,
                )

        return ToolExecutor(
            tools=[FakeExternalTool()],
            boundary_guard=boundary_guard,
        )

    def test_external_tool_args_scanned(self) -> None:
        from openjarvis.core.types import ToolCall
        from openjarvis.security.boundary import BoundaryGuard

        guard = BoundaryGuard(mode="redact")
        executor = self._make_executor(boundary_guard=guard)

        tc = ToolCall(
            id="t1",
            name="fake_external",
            arguments='{"q": "my key is sk-proj-abc123def456ghi789jkl012mno345pqr678stu"}',
        )
        result = executor.execute(tc)
        # The tool should have received redacted args
        assert "sk-proj-" not in result.content

    def test_no_guard_passes_through(self) -> None:
        from openjarvis.core.types import ToolCall

        executor = self._make_executor(boundary_guard=None)
        tc = ToolCall(
            id="t2",
            name="fake_external",
            arguments='{"q": "sk-proj-abc123def456ghi789jkl012mno345pqr678stu"}',
        )
        result = executor.execute(tc)
        assert "sk-proj-" in result.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_boundary_guard.py::TestToolExecutorBoundaryIntegration -v`
Expected: FAIL — `ToolExecutor.__init__` does not accept `boundary_guard`.

- [ ] **Step 3: Add BoundaryGuard to ToolExecutor**

In `src/openjarvis/tools/_stubs.py`, modify the `ToolExecutor.__init__` method to accept a `boundary_guard` parameter. Add it as `self._boundary_guard = boundary_guard`.

In the `execute()` method, after argument parsing succeeds (around where params are parsed from JSON, before the tool.execute call), add boundary checking for non-local tools:

```python
        # Boundary guard: scan external tool arguments
        if (
            self._boundary_guard is not None
            and not getattr(tool, "is_local", True)
        ):
            try:
                tool_call = self._boundary_guard.check_outbound(tool_call)
                # Re-parse arguments after potential redaction
                params = json.loads(tool_call.arguments) if tool_call.arguments else {}
            except Exception as exc:
                return ToolResult(
                    tool_name=tool_call.name,
                    content=f"Security block: {exc}",
                    success=False,
                )
```

- [ ] **Step 4: Add BoundaryGuard to JarvisSystem**

In `src/openjarvis/system.py`, add to the `JarvisSystem` dataclass (after `audit_logger`):

```python
    boundary_guard: Optional[Any] = None  # BoundaryGuard
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_boundary_guard.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/tools/_stubs.py src/openjarvis/system.py tests/security/test_boundary_guard.py
git commit -m "feat: wire BoundaryGuard into ToolExecutor for external tool scanning"
```

---

## Task 6: Webhook Fail-Closed Validation

**Files:**
- Modify: `src/openjarvis/server/webhook_routes.py:31-45` (_validate_twilio_signature)
- Test: `tests/security/test_webhook_validation.py`

- [ ] **Step 1: Write failing tests for fail-closed webhooks**

```python
# tests/security/test_webhook_validation.py
"""Tests for webhook fail-closed validation (Section 3)."""

from __future__ import annotations

from unittest.mock import patch


class TestTwilioValidationFailClosed:
    """Twilio validation must reject when SDK is unavailable."""

    def test_missing_sdk_returns_false(self) -> None:
        """When twilio is not installed, validation returns False."""
        from openjarvis.server.webhook_routes import _validate_twilio_signature

        with patch.dict("sys.modules", {"twilio": None, "twilio.request_validator": None}):
            # Force re-import to hit the ImportError path
            result = _validate_twilio_signature(
                auth_token="test_token",
                url="https://example.com/webhooks/twilio",
                params={"Body": "hello"},
                signature="invalid",
            )
            assert result is False

    def test_empty_auth_token_returns_false(self) -> None:
        """When no auth token is configured, validation returns False."""
        from openjarvis.server.webhook_routes import _validate_twilio_signature

        result = _validate_twilio_signature(
            auth_token="",
            url="https://example.com/webhooks/twilio",
            params={},
            signature="",
        )
        assert result is False


class TestWebhookSecretEnforcement:
    """Webhooks must return 503 when secrets are not configured."""

    def test_twilio_webhook_503_without_token(self) -> None:
        """POST /webhooks/twilio should return 503 if no auth_token configured."""
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        from openjarvis.server.app import create_app

        mock_engine = MagicMock()
        mock_engine.health.return_value = True
        mock_engine.list_models.return_value = ["test"]

        app = create_app(
            mock_engine,
            "test",
            webhook_config={"twilio_auth_token": ""},
        )
        client = TestClient(app)
        resp = client.post(
            "/webhooks/twilio",
            data={"From": "+1234567890", "Body": "hello"},
        )
        assert resp.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_webhook_validation.py -v`
Expected: FAIL — `_validate_twilio_signature` returns `True` when SDK missing (not `False`). The 503 test may also fail since the current code doesn't enforce secret presence.

- [ ] **Step 3: Fix `_validate_twilio_signature` to fail-closed**

In `src/openjarvis/server/webhook_routes.py`, replace lines 31-45:

```python
def _validate_twilio_signature(
    auth_token: str,
    url: str,
    params: dict,
    signature: str,
) -> bool:
    """Validate Twilio webhook signature using the SDK.

    Fails closed: returns ``False`` if the SDK is not installed or
    if no auth_token is configured.
    """
    if not auth_token:
        logger.error("Twilio auth token not configured — rejecting webhook")
        return False
    try:
        from twilio.request_validator import RequestValidator

        validator = RequestValidator(auth_token)
        return validator.validate(url, params, signature)
    except ImportError:
        logger.error(
            "twilio SDK not installed — rejecting webhook. "
            "Install it: pip install twilio"
        )
        return False
```

- [ ] **Step 4: Add 503 response for unconfigured webhook secrets**

In `src/openjarvis/server/webhook_routes.py`, in the Twilio webhook route handler, add an early check at the top of the handler (before signature validation):

```python
        if not twilio_auth_token:
            return Response(
                '{"detail": "Webhook not configured — set TWILIO_AUTH_TOKEN"}',
                status_code=503,
                media_type="application/json",
            )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_webhook_validation.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Apply SendBlue HMAC enforcement**

In `src/openjarvis/server/webhook_routes.py`, in the SendBlue webhook handler, update the secret validation block. The current code (around lines 234-238) only checks if `sb and sb.webhook_secret` — if no secret is configured, it accepts everything silently. Add a warning log when no secret is configured:

```python
        if sb and sb.webhook_secret:
            header_secret = request.headers.get("x-sendblue-secret", "")
            if header_secret != sb.webhook_secret:
                return Response("Invalid secret", status_code=403)
        elif sb:
            logger.warning(
                "SendBlue webhook received without secret verification. "
                "Set webhook_secret for HMAC validation."
            )
```

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/server/webhook_routes.py tests/security/test_webhook_validation.py
git commit -m "fix: fail-closed webhook validation — reject when SDK missing or secret unconfigured"
```

---

## Task 7: File Permissions — Secure Helpers

**Files:**
- Create: `src/openjarvis/security/file_utils.py`
- Test: `tests/security/test_file_permissions.py`

- [ ] **Step 1: Write failing tests for secure file helpers**

```python
# tests/security/test_file_permissions.py
"""Tests for secure file creation helpers (Section 4)."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


class TestSecureMkdir:
    """secure_mkdir should create directories with 0o700."""

    def test_creates_directory_with_700(self) -> None:
        from openjarvis.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "secure_dir"
            result = secure_mkdir(target)
            assert result.is_dir()
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o700

    def test_creates_parent_directories(self) -> None:
        from openjarvis.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a" / "b" / "c"
            result = secure_mkdir(target)
            assert result.is_dir()

    def test_existing_directory_gets_permission_fix(self) -> None:
        from openjarvis.security.file_utils import secure_mkdir

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir(mode=0o755)
            secure_mkdir(target)
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o700


class TestSecureCreate:
    """secure_create should create files with 0o600."""

    def test_creates_file_with_600(self) -> None:
        from openjarvis.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "secure_file.db"
            result = secure_create(target)
            assert result.exists()
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o600

    def test_existing_file_gets_permission_fix(self) -> None:
        from openjarvis.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing.db"
            target.write_text("data")
            os.chmod(target, 0o644)
            secure_create(target)
            mode = stat.S_IMODE(os.stat(target).st_mode)
            assert mode == 0o600

    def test_creates_parent_directory_with_700(self) -> None:
        from openjarvis.security.file_utils import secure_create

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "file.db"
            secure_create(target)
            parent_mode = stat.S_IMODE(os.stat(target.parent).st_mode)
            assert parent_mode == 0o700
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_file_permissions.py -v`
Expected: FAIL — `openjarvis.security.file_utils` does not exist.

- [ ] **Step 3: Implement file_utils.py**

```python
# src/openjarvis/security/file_utils.py
"""Secure file and directory creation helpers.

All OpenJarvis data files under ``~/.openjarvis/`` should be created
through these helpers to ensure consistent, restrictive permissions.
"""

from __future__ import annotations

import os
from pathlib import Path


def secure_mkdir(path: Path, mode: int = 0o700) -> Path:
    """Create a directory with restrictive permissions.

    Creates parent directories as needed, then sets *mode* on the
    target directory (even if it already exists).
    """
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, mode)
    return path


def secure_create(path: Path, mode: int = 0o600) -> Path:
    """Ensure a file exists with restrictive permissions.

    Creates the parent directory with ``0o700`` if needed, touches the
    file if it doesn't exist, and sets *mode* on it.
    """
    secure_mkdir(path.parent, mode=0o700)
    if not path.exists():
        path.touch()
    os.chmod(path, mode)
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_file_permissions.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/security/file_utils.py tests/security/test_file_permissions.py
git commit -m "feat: secure_mkdir and secure_create helpers for restrictive file permissions"
```

---

## Task 8: File Permissions — Apply to All Database Paths

**Files:**
- Modify: `src/openjarvis/tools/storage/sqlite.py:33-45`
- Modify: `src/openjarvis/server/session_store.py:23-29`
- Modify: `src/openjarvis/traces/store.py:82-94`
- Modify: `src/openjarvis/security/audit.py:33-56`
- Modify: `src/openjarvis/connectors/store.py:118-131`
- Modify: `src/openjarvis/connectors/attachment_store.py:50-72`
- Modify: `src/openjarvis/cli/log_config.py:57-59`

- [ ] **Step 1: Protect ~/.openjarvis/ parent directory in config.py**

In `src/openjarvis/core/config.py`, after the `DEFAULT_CONFIG_DIR` definition (line 28), add:

```python
# Ensure the config directory exists with restrictive permissions on first access.
# This is the single biggest protection — even if individual files miss chmod,
# the 0o700 parent blocks other users.
def _ensure_config_dir() -> Path:
    from openjarvis.security.file_utils import secure_mkdir
    return secure_mkdir(DEFAULT_CONFIG_DIR)
```

Then call `_ensure_config_dir()` at the start of `load_config()` (around line 1310):

```python
    _ensure_config_dir()
    hw = detect_hardware()
```

- [ ] **Step 2: Update tools/storage/sqlite.py**

In `src/openjarvis/tools/storage/sqlite.py`, in the `__init__` method (around line 33), after resolving `db_path`, add:

```python
        if self._db_path != ":memory:":
            from openjarvis.security.file_utils import secure_create
            secure_create(Path(self._db_path))
```

- [ ] **Step 3: Update session_store.py**

In `src/openjarvis/server/session_store.py`, replace the directory creation (line 26):

```python
    # Before:
    # Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    # After:
    from openjarvis.security.file_utils import secure_create
    secure_create(Path(db_path))
```

- [ ] **Step 4: Update traces/store.py**

In `src/openjarvis/traces/store.py`, add before the `sqlite3.connect` call (around line 88):

```python
        from openjarvis.security.file_utils import secure_create
        if self._db_path != ":memory:":
            secure_create(Path(self._db_path))
```

- [ ] **Step 5: Update security/audit.py**

In `src/openjarvis/security/audit.py`, replace the directory creation (line 39):

```python
        # Before:
        # self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # After:
        from openjarvis.security.file_utils import secure_create
        secure_create(self._db_path)
```

- [ ] **Step 6: Update connectors/store.py**

In `src/openjarvis/connectors/store.py`, replace the directory creation (lines 127-128):

```python
        # Before:
        # if self._db_path != ":memory:":
        #     Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        # After:
        if self._db_path != ":memory:":
            from openjarvis.security.file_utils import secure_create
            secure_create(Path(self._db_path))
```

- [ ] **Step 7: Update connectors/attachment_store.py**

In `src/openjarvis/connectors/attachment_store.py`, replace directory creation (line 57-58):

```python
        # Before:
        # self._base_dir.mkdir(parents=True, exist_ok=True)

        # After:
        from openjarvis.security.file_utils import secure_mkdir
        secure_mkdir(self._base_dir)
```

And in the `store()` method, after writing blob files (around line 97):

```python
        blob_path.write_bytes(content)
        os.chmod(blob_path, 0o600)
```

- [ ] **Step 8: Update cli/log_config.py**

In `src/openjarvis/cli/log_config.py`, replace directory creation (lines 57-58):

```python
        # Before:
        # log_dir = Path.home() / ".openjarvis"
        # log_dir.mkdir(parents=True, exist_ok=True)

        # After:
        from openjarvis.security.file_utils import secure_mkdir
        log_dir = Path.home() / ".openjarvis"
        secure_mkdir(log_dir)
```

- [ ] **Step 9: Run existing tests to check for regressions**

Run: `uv run pytest tests/ -v -m "not live and not cloud" --timeout=30 -x`
Expected: No regressions. File creation still works, just with tighter permissions.

- [ ] **Step 10: Commit**

```bash
git add src/openjarvis/core/config.py src/openjarvis/tools/storage/sqlite.py src/openjarvis/server/session_store.py src/openjarvis/traces/store.py src/openjarvis/security/audit.py src/openjarvis/connectors/store.py src/openjarvis/connectors/attachment_store.py src/openjarvis/cli/log_config.py
git commit -m "fix: enforce 0o600/0o700 permissions on all database and data files"
```

---

> **Deferred to follow-up:** Section 4.4 (Optional SQLCipher encryption) and Section 5.4 (vault promotion tip in auth setup wizard) are lower-priority items that can be implemented in a subsequent PR without blocking the core hardening.

---

## Task 9: Log Sanitization — SanitizingFormatter

**Files:**
- Modify: `src/openjarvis/cli/log_config.py`
- Test: `tests/security/test_log_sanitization.py`

- [ ] **Step 1: Write failing tests for SanitizingFormatter**

```python
# tests/security/test_log_sanitization.py
"""Tests for log sanitization (Section 5)."""

from __future__ import annotations

import logging


class TestSanitizingFormatter:
    """SanitizingFormatter should redact secrets in log messages."""

    def test_redacts_openai_key(self) -> None:
        from openjarvis.cli.log_config import SanitizingFormatter

        fmt = SanitizingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Key is sk-proj-abc123def456ghi789jkl012mno345pqr678stu",
            args=(),
            exc_info=None,
        )
        result = fmt.format(record)
        assert "sk-proj-" not in result
        assert "[REDACTED" in result

    def test_redacts_aws_key(self) -> None:
        from openjarvis.cli.log_config import SanitizingFormatter

        fmt = SanitizingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="AWS: AKIAIOSFODNN7EXAMPLE",
            args=(),
            exc_info=None,
        )
        result = fmt.format(record)
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_clean_message_unchanged(self) -> None:
        from openjarvis.cli.log_config import SanitizingFormatter

        fmt = SanitizingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Server started on port 8000",
            args=(),
            exc_info=None,
        )
        result = fmt.format(record)
        assert result == "Server started on port 8000"

    def test_redacts_slack_token(self) -> None:
        from openjarvis.cli.log_config import SanitizingFormatter

        fmt = SanitizingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Token: xoxb-1234-5678-abcdefghij",
            args=(),
            exc_info=None,
        )
        result = fmt.format(record)
        assert "xoxb-" not in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_log_sanitization.py -v`
Expected: FAIL — `SanitizingFormatter` does not exist in `log_config.py`.

- [ ] **Step 3: Implement SanitizingFormatter**

In `src/openjarvis/cli/log_config.py`, add at the top of the file (after imports):

```python
from openjarvis.security.credential_stripper import CredentialStripper

_stripper = CredentialStripper()


class SanitizingFormatter(logging.Formatter):
    """Formatter that redacts credentials from log messages."""

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        return _stripper.strip(msg)
```

Then update `setup_logging()` to use `SanitizingFormatter` instead of `logging.Formatter` for both the console handler and file handler.

Replace the console formatter line:
```python
    # Before:
    # fmt = logging.Formatter("%(levelname)s %(name)s: %(message)s")

    # After:
    fmt = SanitizingFormatter("%(levelname)s %(name)s: %(message)s")
```

Replace the file formatter line:
```python
    # Before:
    # file_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # After:
    file_fmt = SanitizingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_log_sanitization.py -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/cli/log_config.py tests/security/test_log_sanitization.py
git commit -m "feat: SanitizingFormatter — auto-redact credentials in all log output"
```

---

## Task 10: Scoped Credential Access

**Files:**
- Modify: `src/openjarvis/core/credentials.py`
- Test: `tests/security/test_log_sanitization.py` (extend)

- [ ] **Step 1: Write failing tests for scoped credential access**

Append to `tests/security/test_log_sanitization.py`:

```python
import os
import tempfile
from pathlib import Path


class TestScopedCredentialAccess:
    """get_tool_credential should return values without polluting os.environ."""

    def test_returns_credential_value(self) -> None:
        from openjarvis.core.credentials import get_tool_credential

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write('[slack]\nSLACK_BOT_TOKEN = "xoxb-test-token"\n')
            f.flush()
            result = get_tool_credential(
                "slack", "SLACK_BOT_TOKEN", path=Path(f.name)
            )
            assert result == "xoxb-test-token"
            # Must NOT have polluted os.environ
            assert os.environ.get("SLACK_BOT_TOKEN") != "xoxb-test-token"
        os.unlink(f.name)

    def test_returns_none_for_missing(self) -> None:
        from openjarvis.core.credentials import get_tool_credential

        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write("[slack]\n")
            f.flush()
            result = get_tool_credential(
                "slack", "SLACK_BOT_TOKEN", path=Path(f.name)
            )
            assert result is None
        os.unlink(f.name)

    def test_returns_none_for_missing_file(self) -> None:
        from openjarvis.core.credentials import get_tool_credential

        result = get_tool_credential(
            "slack", "SLACK_BOT_TOKEN", path=Path("/nonexistent/file.toml")
        )
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_log_sanitization.py::TestScopedCredentialAccess -v`
Expected: FAIL — `get_tool_credential` does not exist.

- [ ] **Step 3: Implement `get_tool_credential`**

In `src/openjarvis/core/credentials.py`, add after `inject_credentials()`:

```python
def get_tool_credential(
    tool_name: str,
    key: str,
    *,
    path: Path | None = None,
) -> str | None:
    """Read a single credential without polluting ``os.environ``.

    Falls back to ``os.environ`` if the key is not in credentials.toml,
    for backward compatibility with Docker env var workflows.
    """
    creds = load_credentials(path=path)
    tool_creds = creds.get(tool_name, {})
    value = tool_creds.get(key)
    if value is not None:
        return value
    # Fallback to env var for backward compat
    return os.environ.get(key) or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_log_sanitization.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/core/credentials.py tests/security/test_log_sanitization.py
git commit -m "feat: get_tool_credential — scoped credential access without env pollution"
```

---

## Task 11: Startup Credential Audit & Non-Loopback CORS Warning

**Files:**
- Modify: `src/openjarvis/cli/serve.py`

- [ ] **Step 1: Add startup credential audit log**

In `src/openjarvis/cli/serve.py`, after credential injection (after the `inject_credentials()` call if present, or after API key resolution around line 352), add:

```python
    # Log credential status at startup
    from openjarvis.core.credentials import get_credential_status, TOOL_CREDENTIALS

    _cred_parts = []
    for _tool_name in sorted(TOOL_CREDENTIALS):
        _status = get_credential_status(_tool_name)
        _set = sum(1 for v in _status.values() if v)
        _total = len(_status)
        if _set > 0:
            _cred_parts.append(f"{_tool_name}: {_set}/{_total} keys")
    if _cred_parts:
        logger.info("Credentials loaded — %s", ", ".join(_cred_parts))
```

- [ ] **Step 2: Add non-loopback CORS wildcard warning**

In `src/openjarvis/cli/serve.py`, before the `uvicorn.run()` call (around line 408), add:

```python
    # Warn about wildcard CORS on non-loopback
    import ipaddress as _ipa

    try:
        _is_loop = _ipa.ip_address(bind_host).is_loopback
    except ValueError:
        _is_loop = bind_host in ("localhost", "")

    if not _is_loop and "*" in config.server.cors_origins:
        console.print(
            "[yellow bold]WARNING:[/yellow bold] Wildcard CORS with credentials "
            "enabled on non-loopback interface. This allows any website to make "
            "authenticated requests to your instance."
        )
```

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `uv run pytest tests/ -v -m "not live and not cloud" --timeout=30 -x`
Expected: No regressions.

- [ ] **Step 4: Commit**

```bash
git add src/openjarvis/cli/serve.py
git commit -m "feat: startup credential audit log and CORS wildcard warning"
```

---

## Task 12: Security Headers — CSP for Docs

**Files:**
- Modify: `src/openjarvis/server/middleware.py:33-51`

- [ ] **Step 1: Add CSP header to SecurityHeadersMiddleware**

In `src/openjarvis/server/middleware.py`, add the CSP header inside the `dispatch` method, after the existing headers (around line 50):

```python
            response.headers["Content-Security-Policy"] = "default-src 'self'"
```

Also add it to the `SECURITY_HEADERS` dict:

```python
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'",
}
```

- [ ] **Step 2: Run existing middleware tests**

Run: `uv run pytest tests/server/test_middleware.py -v`
Expected: May need to update `test_headers_dict` to include the new CSP header. If it fails, update the test's `expected_keys` set to include `"Content-Security-Policy"`.

- [ ] **Step 3: Commit**

```bash
git add src/openjarvis/server/middleware.py
git commit -m "feat: add Content-Security-Policy header to API responses"
```

---

## Task 13: Security Profiles

**Files:**
- Modify: `src/openjarvis/core/config.py:1308-1368` (load_config)
- Test: `tests/security/test_security_profiles.py`

- [ ] **Step 1: Write failing tests for security profiles**

```python
# tests/security/test_security_profiles.py
"""Tests for security profile expansion (Section 7)."""

from __future__ import annotations


# Profile definitions — must match the implementation
_PROFILES = {
    "personal": {
        "host": "127.0.0.1",
        "mode": "redact",
        "rate_limit_enabled": True,
        "local_engine_bypass": False,
        "local_tool_bypass": False,
    },
    "shared": {
        "host": "127.0.0.1",
        "mode": "redact",
        "rate_limit_enabled": True,
        "local_engine_bypass": False,
        "local_tool_bypass": False,
    },
    "server": {
        "host": "0.0.0.0",
        "mode": "block",
        "rate_limit_enabled": True,
        "rate_limit_rpm": 30,
        "rate_limit_burst": 5,
        "local_engine_bypass": False,
        "local_tool_bypass": False,
    },
}


class TestProfileExpansion:
    """Profiles should pre-fill security and server config fields."""

    def test_personal_profile_sets_redact(self) -> None:
        from openjarvis.core.config import SecurityConfig, apply_security_profile

        cfg = SecurityConfig(profile="personal")
        server_cfg = None
        apply_security_profile(cfg, server_cfg)
        assert cfg.mode == "redact"
        assert cfg.rate_limit_enabled is True

    def test_server_profile_sets_block(self) -> None:
        from openjarvis.core.config import SecurityConfig, ServerConfig, apply_security_profile

        cfg = SecurityConfig(profile="server")
        server_cfg = ServerConfig()
        apply_security_profile(cfg, server_cfg)
        assert cfg.mode == "block"
        assert cfg.rate_limit_rpm == 30
        assert cfg.rate_limit_burst == 5
        assert server_cfg.host == "0.0.0.0"

    def test_explicit_override_beats_profile(self) -> None:
        """User-set values in config.toml should override profile defaults."""
        from openjarvis.core.config import SecurityConfig, apply_security_profile

        # Simulate: user set profile=server but also mode=warn
        cfg = SecurityConfig(profile="server", mode="warn")
        apply_security_profile(cfg, None, overrides={"mode"})
        # mode should stay "warn" because user explicitly set it
        assert cfg.mode == "warn"

    def test_empty_profile_is_noop(self) -> None:
        from openjarvis.core.config import SecurityConfig, apply_security_profile

        cfg = SecurityConfig()
        original_mode = cfg.mode
        apply_security_profile(cfg, None)
        assert cfg.mode == original_mode

    def test_unknown_profile_raises(self) -> None:
        import pytest

        from openjarvis.core.config import SecurityConfig, apply_security_profile

        cfg = SecurityConfig(profile="nonexistent")
        with pytest.raises(ValueError, match="Unknown security profile"):
            apply_security_profile(cfg, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/security/test_security_profiles.py -v`
Expected: FAIL — `apply_security_profile` does not exist.

- [ ] **Step 3: Implement profile expansion**

In `src/openjarvis/core/config.py`, add the profile expansion function (after the `SecurityConfig` dataclass):

```python
_SECURITY_PROFILES: dict[str, dict[str, Any]] = {
    "personal": {
        "security": {
            "mode": "redact",
            "rate_limit_enabled": True,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "127.0.0.1",
        },
    },
    "shared": {
        "security": {
            "mode": "redact",
            "rate_limit_enabled": True,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "127.0.0.1",
        },
    },
    "server": {
        "security": {
            "mode": "block",
            "rate_limit_enabled": True,
            "rate_limit_rpm": 30,
            "rate_limit_burst": 5,
            "local_engine_bypass": False,
            "local_tool_bypass": False,
        },
        "server": {
            "host": "0.0.0.0",
        },
    },
}


def apply_security_profile(
    security_cfg: SecurityConfig,
    server_cfg: ServerConfig | None,
    *,
    overrides: set[str] | None = None,
) -> None:
    """Expand a named security profile into config fields.

    Fields in *overrides* (explicitly set by the user in TOML) are
    not overwritten by the profile.
    """
    profile = security_cfg.profile
    if not profile:
        return

    if profile not in _SECURITY_PROFILES:
        raise ValueError(
            f"Unknown security profile '{profile}'. "
            f"Valid profiles: {', '.join(_SECURITY_PROFILES)}"
        )

    _overrides = overrides or set()
    pdef = _SECURITY_PROFILES[profile]

    for key, value in pdef.get("security", {}).items():
        if key not in _overrides and hasattr(security_cfg, key):
            setattr(security_cfg, key, value)

    if server_cfg is not None:
        for key, value in pdef.get("server", {}).items():
            if key not in _overrides and hasattr(server_cfg, key):
                setattr(server_cfg, key, value)
```

- [ ] **Step 4: Hook profile expansion into load_config()**

In `src/openjarvis/core/config.py`, in the `load_config()` function, after all TOML sections have been applied (after the `for section_name in top_sections` loop, around line 1362), add:

```python
        # Expand security profile (user TOML overrides take precedence)
        _user_security_keys = set(data.get("security", {}).keys())
        apply_security_profile(cfg.security, cfg.server, overrides=_user_security_keys)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/security/test_security_profiles.py -v`
Expected: All 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/core/config.py tests/security/test_security_profiles.py
git commit -m "feat: security profiles — personal, shared, server presets with user overrides"
```

---

## Task 14: Doctor Security Check

**Files:**
- Modify: `src/openjarvis/cli/doctor_cmd.py:267-278` (_run_all_checks)

- [ ] **Step 1: Add security profile check to doctor**

In `src/openjarvis/cli/doctor_cmd.py`, add a new check function:

```python
def _check_security_profile() -> CheckResult:
    """Check if a security profile is configured."""
    try:
        from openjarvis.core.config import load_config

        config = load_config()
        if config.security.profile:
            return CheckResult(
                name="Security profile",
                status="ok",
                message=f"Profile '{config.security.profile}' active",
            )
        return CheckResult(
            name="Security profile",
            status="warn",
            message="No security profile set",
            details="Recommended: add security.profile = 'personal' to config.toml",
        )
    except Exception as exc:
        return CheckResult(
            name="Security profile",
            status="fail",
            message=f"Could not check: {exc}",
        )
```

Add `checks.append(_check_security_profile())` to `_run_all_checks()`.

- [ ] **Step 2: Run doctor to verify**

Run: `uv run jarvis doctor`
Expected: Shows a "Security profile" row with a warning suggesting `security.profile = 'personal'`.

- [ ] **Step 3: Commit**

```bash
git add src/openjarvis/cli/doctor_cmd.py
git commit -m "feat: jarvis doctor checks for security profile configuration"
```

---

## Task 15: Integration Verification

**Files:**
- All modified files from Tasks 1-14

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v -m "not live and not cloud" --timeout=60`
Expected: All tests pass. No regressions.

- [ ] **Step 2: Run linting**

Run: `uv run ruff check src/ tests/`
Run: `uv run ruff format --check src/ tests/`
Expected: No lint errors, no format issues.

- [ ] **Step 3: Manual smoke test — server binding**

Run: `uv run jarvis serve --host 127.0.0.1 --port 8000`
Expected: Server starts on `127.0.0.1:8000`. Not accessible from other machines on the network.

- [ ] **Step 4: Manual smoke test — non-loopback rejection**

Run: `uv run jarvis serve --host 0.0.0.0`
Expected: Server refuses to start with error: `Binding to 0.0.0.0 requires OPENJARVIS_API_KEY to be set.`

- [ ] **Step 5: Manual smoke test — doctor**

Run: `uv run jarvis doctor`
Expected: Security profile check appears with a warning or OK status.

- [ ] **Step 6: Final commit (if any lint fixes needed)**

```bash
git add -u
git commit -m "fix: lint and format fixes for security hardening"
```
