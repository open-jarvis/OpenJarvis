# Security Hardening Design — Layered Boundary Enforcement

**Date**: 2026-03-28
**Status**: Approved
**Scope**: Network exposure, data scanning, webhook validation, file permissions, credential handling, security profiles

## Context

OpenJarvis stores and transmits sensitive data across messaging channels (Slack, WhatsApp, Gmail, Telegram, Discord, Twilio, SendBlue, iMessage, Signal) and cloud LLM providers (OpenAI, Anthropic, Google, OpenRouter, MiniMax). A security audit identified critical gaps:

- Server binds `0.0.0.0` with no auth, no TLS, wildcard CORS
- Security scanners exist but are off/warn-only by default
- Tool calls that send data externally are never scanned
- Webhook validation silently falls back to accepting all requests
- Databases created with default umask (world-readable on shared systems)
- Credentials in plaintext, injected into global `os.environ`
- Logs don't auto-redact secrets

**Primary deployment target**: Single user on personal Mac/laptop. Must also support multi-user shared machines and server deployments.

**Breaking changes**: Allowed, but migration must be straightforward with clear error messages.

## Approach

**Layered boundary enforcement** with security profile sugar.

One `BoundaryGuard` wraps all exit points from the device — cloud engines, external tools, webhooks. Config defaults are fixed directly in existing dataclasses. File permissions go through a shared helper. Security profiles provide a convenience shorthand for common deployment scenarios.

---

## Section 1: Network Exposure Defaults

### 1.1 Server Binding

`ServerConfig.host` default changes from `"0.0.0.0"` to `"127.0.0.1"`.

**File**: `src/openjarvis/core/config.py:763`

Users who need network access explicitly set `host = "0.0.0.0"` in config.toml.

### 1.2 CORS Restriction

`server/app.py:182-188` changes from `allow_origins=["*"]` to a configurable list.

New field: `ServerConfig.cors_origins: list[str]`

Default: `["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173", "tauri://localhost"]`

### 1.3 Non-Loopback Auth Enforcement

If `host != 127.0.0.1` and no `OPENJARVIS_API_KEY` is set, the server refuses to start:

```
ERROR: Binding to 0.0.0.0 requires OPENJARVIS_API_KEY to be set. Run: jarvis auth generate-key
```

Loopback binding works without a key for local dev convenience.

### 1.4 Rate Limiting

`SecurityConfig.rate_limit_enabled` default changes from `False` to `True`. Existing values (60 rpm, 10 burst) stay the same.

### 1.5 TLS

Not adding TLS to the server. Better handled by reverse proxy (nginx, Caddy, Cloudflare Tunnel already supported).

---

## Section 2: Boundary Guard — Scanning at Device Exit Points

### 2.1 New Module: `security/boundary.py`

`BoundaryGuard` class with two methods:

- `scan_outbound(content: str, destination: str) -> str` — scans text before it leaves the device, returns redacted text or raises `SecurityBlockError` in `"block"` mode
- `check_outbound(tool_call: ToolCall) -> ToolCall` — scans tool call arguments before execution, returns redacted tool call

Delegates to existing `SecretScanner` and `PIIScanner`. Publishes `SECURITY_ALERT` events to the audit system. One instance lives on `JarvisSystem`.

### 2.2 Engine Tagging

`InferenceEngine` ABC gets `is_cloud: bool = False`.

Cloud engines set `True`: `cloud.py`, `litellm.py`
Local engines keep `False`: `ollama.py`, `vllm.py`, `sglang.py`, `llamacpp.py`, `mlx.py`, `lmstudio.py`

### 2.3 Tool Tagging

`BaseTool` gets `is_local: bool = True` as default.

External tools override to `False`: `web_search`, `send_email`, `http_request`, and all channel `send()` methods (Slack, Discord, Telegram, WhatsApp, SendBlue, Twilio, Gmail, Signal). Any tool that makes an outbound network request is `is_local = False`.

File/shell/memory tools keep `True`: `file_read`, `file_write`, `shell_exec`, `memory_search`, `memory_index`, `calculator`, `code_interpreter`.

### 2.4 Integration Points

- `GuardrailsEngine` calls `BoundaryGuard.scan_outbound()` on messages before sending to cloud engines
- `ToolUsingAgent._execute_tool()` calls `BoundaryGuard.check_outbound()` on tool calls where `tool.is_local is False`
- Both paths always active by default (conservative)
- Config knobs `local_engine_bypass: bool = False` and `local_tool_bypass: bool = False` allow opt-out

### 2.5 Default Mode

`SecurityConfig.mode` changes from `"warn"` to `"redact"`.

---

## Section 3: Webhook Fail-Closed & Inbound Validation

### 3.1 Fail-Closed Validation

`_validate_twilio_signature()` changes from `return True` to `return False` with `logger.error()` when SDK not installed. Same for all webhook validators.

Outbound sending still works. Only inbound webhook processing is blocked.

Response: HTTP 403 `{"detail": "Webhook signature validation unavailable — install the twilio package"}`

### 3.2 Webhook Secret Enforcement

If a channel's webhook route is registered but no secret/token is configured, return HTTP 503:

```json
{"detail": "Webhook not configured — set TWILIO_AUTH_TOKEN"}
```

### 3.3 SendBlue Exception

SendBlue doesn't always provide a signing secret. If `webhook_secret` is configured, HMAC is mandatory. If not configured, log a warning per webhook but still accept.

### 3.4 Webhook Auth Exemption

`_EXEMPT_PREFIXES` for `/webhooks/` stays — webhooks use per-platform signature verification (now actually enforced) instead of API key auth.

---

## Section 4: File Permissions & Encryption at Rest

### 4.1 Shared Helper: `security/file_utils.py`

Two functions:

- `secure_mkdir(path: Path, mode: int = 0o700) -> Path`
- `secure_create(path: Path, mode: int = 0o600) -> Path`

Replaces scattered `p.parent.mkdir(parents=True, exist_ok=True)` calls.

### 4.2 Database Paths That Get `secure_create()`

- `tools/storage/sqlite.py` — `memory.db`
- `server/session_store.py` — `sessions.db`
- `traces/store.py` — `traces.db`
- `security/audit.py` — `audit.db`
- `connectors/store.py` — `knowledge.db`
- `connectors/attachment_store.py` — blob dir gets `secure_mkdir(0o700)`, blobs get `0o600`

### 4.3 Parent Directory Protection

`~/.openjarvis/` itself gets `secure_mkdir(0o700)` at first creation in `config.py`. This is the single biggest fix — even if individual files miss a chmod, the parent blocks access.

### 4.4 Optional SQLCipher

New `StorageConfig.encryption: bool = False`.

When `True`:
- SQLite connections use `sqlcipher` via `pysqlcipher3`
- Key derived from `~/.openjarvis/.vault_key`
- If `pysqlcipher3` not installed: `"storage.encryption requires pysqlcipher3 — run: pip install pysqlcipher3"`
- Migration: `jarvis db encrypt` CLI command copies plaintext DBs to encrypted ones

### 4.5 Vault Key Separation

New `SecurityConfig.vault_key_path` field (default: `~/.openjarvis/.vault_key`). Users in scenario B/C can point to a different location (mounted secrets volume, macOS Keychain wrapper). Default is fine for scenario A since `0o700` on parent protects it.

---

## Section 5: Credential Handling & Log Sanitization

### 5.1 Log Sanitization

`cli/log_config.py` gets a `SanitizingFormatter` that runs `CredentialStripper.redact()` on every log message:

```python
class SanitizingFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        return _stripper.redact(msg)
```

Applied to `cli.log` and the gateway log.

### 5.2 Scoped Credential Access

New function: `get_tool_credential(tool_name: str, key: str) -> str | None`

- Reads from `credentials.toml` (cached, thread-safe)
- Returns value without polluting global `os.environ`
- Channel/tool constructors updated to try `get_tool_credential()` first, fall back to `os.environ`
- `inject_credentials()` deprecated but still works for backward compat (Docker env var users)

### 5.3 Startup Credential Audit

Server startup logs which tools have credentials configured:

```
INFO: Credentials loaded — slack: 2/2 keys, telegram: 1/1 keys, whatsapp: 0/2 keys (not configured)
```

### 5.4 Vault Promotion

`jarvis auth setup` wizard gets a tip line: `"Tip: Use 'jarvis vault store' for encrypted credential storage"`

---

## Section 6: CORS, Security Headers & Telegram Token

### 6.1 CORS

Covered in Section 1.2. Configurable origins, localhost defaults, `allow_credentials=True` safe with restricted origins.

### 6.2 Telegram Token in URL

Telegram API requires token in URL path — this is their design, not ours. Mitigations:
- `SanitizingFormatter` catches `bot[0-9]+:AA[a-zA-Z0-9_-]{33}` patterns in logs
- HTTPS required by Telegram (encrypted in transit)
- Code comment documenting the limitation

### 6.3 Non-Loopback CORS Warning

If server binds non-loopback and CORS origins contain `"*"` (user override), emit startup warning:

```
WARNING: Wildcard CORS with credentials enabled on non-loopback interface. This allows any website to make authenticated requests to your instance.
```

### 6.4 CSP Header

Add `Content-Security-Policy: default-src 'self'` for the `/docs` OpenAPI page.

---

## Section 7: Security Profiles

### 7.1 Profile Field

New `SecurityConfig.profile: str = ""`. When set, pre-fills all security fields before user overrides.

### 7.2 Profile Definitions

**`personal`** (scenario A — single user, local hardware):
- `host = "127.0.0.1"`, `mode = "redact"`, `scan_input = True`, `scan_output = True`
- `rate_limit_enabled = True`, `storage.encryption = False`
- CORS: localhost origins only
- `local_engine_bypass = False`, `local_tool_bypass = False`

**`shared`** (scenario B — multi-user machine):
- Everything in `personal`, plus:
- `storage.encryption = True` (SQLCipher)
- API key required even on loopback
- `vault_key_path` recommended outside `~/.openjarvis/`

**`server`** (scenario C — network-facing):
- Everything in `shared`, plus:
- `host = "0.0.0.0"` (API key enforced by non-loopback guard)
- `rate_limit_rpm = 30`, `rate_limit_burst = 5`
- `mode = "block"` (reject rather than redact)
- CORS: must be explicitly configured

### 7.3 No Profile = Safe Defaults

If `profile` is empty, individual field defaults from Sections 1-6 apply. Profiles are convenience shorthand, not a separate system.

### 7.4 Startup Log

```
INFO: Security profile 'personal' active. Override individual settings in [security] section.
```

### 7.5 Config Migration via `jarvis doctor`

Health check CLI reports: `"Your config doesn't set a security profile. Recommended: security.profile = 'personal'"` with a diff of what would change.

---

## Section 8: Verification & Testing

### 8.1 Unit Tests

One test file per section in `tests/security/`:

| File | Covers |
|------|--------|
| `test_network_defaults.py` | ServerConfig defaults, non-loopback auth enforcement, CORS origins |
| `test_boundary_guard.py` | `scan_outbound()` redaction, `check_outbound()` tool args, `is_cloud`/`is_local` tags, audit events |
| `test_webhook_validation.py` | Fail-closed when SDK missing, 503 when secret missing, outbound unaffected |
| `test_file_permissions.py` | `secure_mkdir` 0o700, `secure_create` 0o600, all DB paths use helper |
| `test_log_sanitization.py` | `SanitizingFormatter` redacts secrets, `get_tool_credential()` doesn't pollute env |
| `test_security_profiles.py` | Profile field values, individual overrides take precedence |

### 8.2 Integration Test

`test_boundary_integration.py` (marked `cloud`):
- Mock cloud engine receives redacted content
- Mock external tool receives redacted args
- Local tool receives unredacted args (when bypass enabled)

### 8.3 Implementation Order (by severity)

1. Network exposure defaults (Section 1)
2. Boundary guard (Section 2)
3. Webhook fail-closed (Section 3)
4. File permissions (Section 4)
5. Credential handling & logs (Section 5)
6. CORS & headers (Section 6)
7. Security profiles (Section 7)

Each section implemented and tests passing before moving to the next.

### 8.4 Manual Smoke Test

After all sections:
- `jarvis serve` binds `127.0.0.1` only
- `/health` accessible, `/v1/chat/completions` requires auth when non-loopback
- Message with `"my key is sk-abc123..."` through cloud engine shows `[REDACTED]` outbound

---

## Files Modified (Summary)

**New files**:
- `src/openjarvis/security/boundary.py`
- `src/openjarvis/security/file_utils.py`
- `tests/security/test_network_defaults.py`
- `tests/security/test_boundary_guard.py`
- `tests/security/test_webhook_validation.py`
- `tests/security/test_file_permissions.py`
- `tests/security/test_log_sanitization.py`
- `tests/security/test_security_profiles.py`
- `tests/security/test_boundary_integration.py`

**Modified files**:
- `src/openjarvis/core/config.py` — ServerConfig, SecurityConfig, StorageConfig defaults
- `src/openjarvis/server/app.py` — CORS configuration
- `src/openjarvis/server/auth_middleware.py` — non-loopback enforcement
- `src/openjarvis/server/webhook_routes.py` — fail-closed validation
- `src/openjarvis/server/middleware.py` — CSP header
- `src/openjarvis/engine/base.py` — `is_cloud` attribute
- `src/openjarvis/engine/cloud.py`, `litellm.py` — `is_cloud = True`
- `src/openjarvis/tools/base.py` — `is_local` attribute
- External tool classes — `is_local = False`
- `src/openjarvis/agents/tool_using.py` — boundary guard integration
- `src/openjarvis/security/guardrails.py` — boundary guard integration
- `src/openjarvis/tools/storage/sqlite.py` — secure file creation
- `src/openjarvis/server/session_store.py` — secure file creation
- `src/openjarvis/traces/store.py` — secure file creation
- `src/openjarvis/security/audit.py` — secure file creation
- `src/openjarvis/connectors/store.py` — secure file creation
- `src/openjarvis/connectors/attachment_store.py` — secure file/dir creation
- `src/openjarvis/core/credentials.py` — scoped access, deprecate inject
- `src/openjarvis/cli/log_config.py` — SanitizingFormatter
- `src/openjarvis/cli/serve.py` — startup checks, profile logging
- `src/openjarvis/channels/sendblue.py` — webhook HMAC enforcement
- `src/openjarvis/system.py` — BoundaryGuard wiring
