# Security

OpenJarvis includes a security layer that scans prompts and model outputs for secrets, personally identifiable information (PII), and sensitive file paths. The system is designed to be composable: scanners run as a pipeline, and the `GuardrailsEngine` wrapper drops in front of any inference backend without changing how the rest of your code works.

## Three layers of security review

OpenJarvis separates host posture, application data boundaries, and runtime prompt guardrails:

| Layer | Command / component | What it checks |
| --- | --- | --- |
| Host scan | `jarvis scan` | Disk encryption, cloud-sync agents, exposed engine ports, remote-access tools |
| Data-boundary scan | `jarvis scan --data-boundaries` | Configured inference, memory, traces, channels, tools, and local stores |
| Runtime guardrails | `GuardrailsEngine` / BoundaryGuard | Secrets, PII, and file-policy violations in live prompts and outputs |

Use the host scan before storing sensitive data on the machine. Use the data-boundary scan to verify whether your `config.toml` is local-only, cloud-capable, or mixed. Use BoundaryGuard during inference when you need live redaction or blocking.

See [Data Boundary Scan](data-boundary-scan.md) for the application config diagnostic and [BoundaryGuard](#guardrailsengine) below for runtime scanning.

---

## Overview

The security module has four independently usable components:

<div class="grid cards" markdown>

- :material-shield-search: **GuardrailsEngine**

    ---

    Wraps any `InferenceEngine` with pre- and post-call scanning. Supports WARN, REDACT, and BLOCK modes.

    [:octicons-arrow-right-24: Jump to GuardrailsEngine](#guardrailsengine)

- :material-key-remove: **SecretScanner**

    ---

    Detects API keys, tokens, passwords, and connection strings in text.

    [:octicons-arrow-right-24: Jump to SecretScanner](#secretscanner)

- :material-account-lock: **PIIScanner**

    ---

    Detects email addresses, SSNs, credit card numbers, phone numbers, and public IPs.

    [:octicons-arrow-right-24: Jump to PIIScanner](#piiscanner)

- :material-file-lock: **File Policy**

    ---

    Blocks access to `.env`, `*.pem`, `id_rsa`, and other credential files.

    [:octicons-arrow-right-24: Jump to File Policy](#file-policy)

</div>

---

## GuardrailsEngine

`GuardrailsEngine` wraps any `InferenceEngine` and scans both the input messages and the output content. It is not registered in `EngineRegistry` — you create it directly by wrapping an existing engine instance.

### Modes

| Mode | Constant | Behavior |
|------|----------|----------|
| Warn | `RedactionMode.WARN` | Publish a `SECURITY_ALERT` event but pass the text through unchanged. Default. |
| Redact | `RedactionMode.REDACT` | Replace matches with `[REDACTED:pattern_name]` before passing to/from the engine. |
| Block | `RedactionMode.BLOCK` | Raise `SecurityBlockError` immediately when findings are detected. |

### Basic Usage

=== "Warn mode (default)"

    ```python title="warn_mode.py"
    from openjarvis.engine.ollama import OllamaEngine
    from openjarvis.security.guardrails import GuardrailsEngine
    from openjarvis.security.types import RedactionMode
    from openjarvis.core.types import Message, Role

    engine = OllamaEngine()
    guarded = GuardrailsEngine(engine)  # (1)!

    messages = [Message(role=Role.USER, content="My API key is sk-abc123xyz")]
    response = guarded.generate(messages, model="qwen3:8b")
    # The key is logged as a warning but the text is passed unchanged
    print(response["content"])
    ```

    1. Defaults to `mode=RedactionMode.WARN`, `scan_input=True`, `scan_output=True`.

=== "Redact mode"

    ```python title="redact_mode.py"
    from openjarvis.engine.ollama import OllamaEngine
    from openjarvis.security.guardrails import GuardrailsEngine
    from openjarvis.security.types import RedactionMode
    from openjarvis.core.types import Message, Role

    engine = OllamaEngine()
    guarded = GuardrailsEngine(engine, mode=RedactionMode.REDACT)  # (1)!

    messages = [Message(role=Role.USER, content="My key is sk-abc123xyz, help me debug")]
    response = guarded.generate(messages, model="qwen3:8b")
    # Input sent to engine: "My key is [REDACTED:openai_key], help me debug"
    ```

    1. Sensitive patterns in input messages are replaced before reaching the model.

=== "Block mode"

    ```python title="block_mode.py"
    from openjarvis.engine.ollama import OllamaEngine
    from openjarvis.security.guardrails import GuardrailsEngine, SecurityBlockError
    from openjarvis.security.types import RedactionMode
    from openjarvis.core.types import Message, Role

    engine = OllamaEngine()
    guarded = GuardrailsEngine(engine, mode=RedactionMode.BLOCK)

    try:
        messages = [Message(role=Role.USER, content="AKIA1234567890ABCDEF")]
        guarded.generate(messages, model="qwen3:8b")
    except SecurityBlockError as exc:
        print(f"Blocked: {exc}")
        # Blocked: Security scan blocked input: 1 finding(s) detected
    ```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `engine` | `InferenceEngine` | — | The wrapped inference engine |
| `scanners` | `list[BaseScanner]` | `[SecretScanner(), PIIScanner()]` | Scanners to run |
| `mode` | `RedactionMode` | `WARN` | Action on findings |
| `scan_input` | `bool` | `True` | Scan input messages |
| `scan_output` | `bool` | `True` | Scan output content |
| `bus` | `EventBus` | `None` | Event bus for security events |

### Event Bus Integration

When a `bus` is provided, `GuardrailsEngine` publishes events on every scan result:

| Event | When |
|-------|------|
| `SECURITY_ALERT` | Findings detected in WARN or REDACT mode |
| `SECURITY_BLOCK` | Findings detected in BLOCK mode |

You can subscribe to these events with an `AuditLogger` to build a persistent security event log. See [Audit Logger](#audit-logger) below.

### Custom Scanners

You can pass any set of `BaseScanner` subclasses to restrict or extend scanning:

```python title="custom_scanners.py"
from openjarvis.security.guardrails import GuardrailsEngine
from openjarvis.security.scanner import SecretScanner
from openjarvis.security.types import RedactionMode

# Only scan for secrets, skip PII
guarded = GuardrailsEngine(
    engine,
    scanners=[SecretScanner()],
    mode=RedactionMode.REDACT,
)
```

### Streaming

For streaming calls, `GuardrailsEngine.stream()` yields tokens in real time and then performs a post-hoc scan on the accumulated output for logging. Because tokens are already delivered to the caller before scanning completes, BLOCK mode only applies to the input side during streaming.

!!! warning "Streaming and BLOCK mode"
    `SecurityBlockError` can only be raised before the stream starts (for input scanning). Output blocking during streaming is not possible — use REDACT mode if you need to sanitize model outputs in streaming scenarios.

---

## SecretScanner

`SecretScanner` detects API keys, tokens, passwords, and other credentials using regex patterns. Each pattern has an associated `ThreatLevel`.

### Pattern Reference

| Pattern Name | Threat Level | Matches |
|---|---|---|
| `openai_key` | CRITICAL | `sk-` followed by 20+ alphanumeric chars |
| `anthropic_key` | CRITICAL | `sk-ant-` followed by 20+ chars |
| `aws_access_key` | CRITICAL | `AKIA` followed by 16 uppercase alphanumeric chars |
| `github_token` | CRITICAL | `ghp_`, `gho_`, `ghs_`, `ghr_`, `github_pat_` followed by 36+ chars |
| `stripe_key` | CRITICAL | `sk_live_`, `sk_test_`, `pk_live_`, `pk_test_` followed by 20+ chars |
| `private_key` | CRITICAL | PEM private key header `-----BEGIN PRIVATE KEY-----` |
| `password_assignment` | HIGH | `password = "..."`, `passwd: "..."`, etc. |
| `db_connection_string` | HIGH | `postgres://`, `mysql://`, `mongodb://`, `redis://` URLs |
| `slack_token` | HIGH | `xoxb-`, `xoxp-`, `xoxo-`, `xoxr-`, `xoxs-` followed by token |
| `generic_api_key` | HIGH | `api_key = "..."`, `secret_key = "..."`, `auth_token = "..."` |

### Direct Usage

```python title="secret_scanner.py"
from openjarvis.security.scanner import SecretScanner

scanner = SecretScanner()

# Scan text
result = scanner.scan("My key is sk-abc123xyz789 and it is secret")
print(result.clean)           # False
print(result.highest_threat)  # ThreatLevel.CRITICAL
for finding in result.findings:
    print(f"  {finding.pattern_name}: {finding.description} at [{finding.start}:{finding.end}]")

# Redact text
clean = scanner.redact("Token: sk-abc123xyz789")
print(clean)  # Token: [REDACTED:openai_key]
```

---

## PIIScanner

`PIIScanner` detects personally identifiable information using regex patterns calibrated for common US formats.

### Pattern Reference

| Pattern Name | Threat Level | Matches |
|---|---|---|
| `us_ssn` | CRITICAL | `XXX-XX-XXXX` format Social Security Numbers |
| `credit_card_visa` | CRITICAL | Visa card numbers (16 digits starting with 4) |
| `credit_card_mastercard` | CRITICAL | Mastercard numbers (16 digits starting with 51–55) |
| `credit_card_amex` | CRITICAL | Amex numbers (15 digits starting with 34 or 37) |
| `email` | MEDIUM | Standard email addresses |
| `us_phone` | MEDIUM | US phone numbers in common formats |
| `ipv4_public` | LOW | Public IPv4 addresses (excludes RFC1918 ranges) |

!!! note "Private IP addresses"
    The `ipv4_public` pattern intentionally excludes private ranges (10.x.x.x, 172.16–31.x.x, 192.168.x.x, 127.x.x.x). Internal IP addresses are not considered sensitive by default.

### Direct Usage

```python title="pii_scanner.py"
from openjarvis.security.scanner import PIIScanner

scanner = PIIScanner()

text = "Contact john@example.com or call 555-867-5309"
result = scanner.scan(text)

for finding in result.findings:
    print(f"{finding.pattern_name}: threat={finding.threat_level.value}")
# email: threat=medium
# us_phone: threat=medium

clean = scanner.redact(text)
print(clean)
# Contact [REDACTED:email] or call [REDACTED:us_phone]
```

---

## File Policy

The file policy module prevents access to credential and key files. It is used internally by `FileReadTool` and the memory ingest path, but you can use it directly.

### Sensitive File Patterns

The `DEFAULT_SENSITIVE_PATTERNS` frozenset contains the following glob patterns:

| Pattern | Description |
|---------|-------------|
| `.env`, `.env.*`, `*.env` | Environment variable files |
| `.secret`, `*.secrets` | Generic secret files |
| `credentials.*` | Credential files |
| `*.pem`, `*.key` | TLS/SSL certificates and private keys |
| `*.p12`, `*.pfx`, `*.jks` | PKCS and Java keystore files |
| `id_rsa`, `id_ed25519` | SSH private key files |
| `.htpasswd` | Apache password files |
| `.pgpass` | PostgreSQL password files |
| `.netrc` | FTP/SSH credential files |

### Usage

```python title="file_policy.py"
from pathlib import Path
from openjarvis.security.file_policy import is_sensitive_file, filter_sensitive_paths

# Check a single file
print(is_sensitive_file(".env"))           # True
print(is_sensitive_file("server.key"))     # True
print(is_sensitive_file("README.md"))      # False

# Filter a list of paths
paths = [
    Path("README.md"),
    Path(".env"),
    Path("src/main.py"),
    Path("server.pem"),
]
safe = filter_sensitive_paths(paths)
print(safe)  # [PosixPath('README.md'), PosixPath('src/main.py')]
```

### Integration with FileReadTool

The built-in `FileReadTool` automatically calls `is_sensitive_file()` before reading any path. Attempts to read sensitive files raise an error rather than returning the file content. This behavior cannot be disabled at the tool level — configure the agent not to have `FileReadTool` if you need unrestricted file access.

---

## Audit Logger

The `AuditLogger` persists security events to an append-only SQLite database. It can subscribe to the event bus to capture events automatically, or you can call `log()` manually.

### Event Bus Integration (Automatic)

```python title="audit_bus.py"
from openjarvis.core.events import EventBus
from openjarvis.security.audit import AuditLogger
from openjarvis.security.guardrails import GuardrailsEngine
from openjarvis.security.types import RedactionMode
from openjarvis.engine.ollama import OllamaEngine

bus = EventBus()

# AuditLogger subscribes to SECURITY_SCAN, SECURITY_ALERT, SECURITY_BLOCK
audit = AuditLogger(db_path="~/.openjarvis/audit.db", bus=bus)

engine = OllamaEngine()
guarded = GuardrailsEngine(
    engine,
    mode=RedactionMode.WARN,
    bus=bus,
)

# Security events are now persisted automatically
```

### Manual Logging

```python title="audit_manual.py"
import time
from openjarvis.security.audit import AuditLogger
from openjarvis.security.types import SecurityEvent, SecurityEventType

audit = AuditLogger(db_path="./audit.db")

event = SecurityEvent(
    event_type=SecurityEventType.SECRET_DETECTED,
    timestamp=time.time(),
    findings=[],
    content_preview="sk-...",
    action_taken="redacted",
)
audit.log(event)
```

### Querying the Audit Log

```python title="audit_query.py"
from openjarvis.security.audit import AuditLogger

audit = AuditLogger(db_path="~/.openjarvis/audit.db")

# Recent events
events = audit.query(limit=20)

# Filter by event type
secret_events = audit.query(event_type="secret_detected")

# Filter by time range
import time
recent = audit.query(since=time.time() - 3600)  # last hour

# Count total events
print(f"Total events: {audit.count()}")

audit.close()
```

---

## Configuration

Security settings live in the `[security]` section of `~/.openjarvis/config.toml`.

```toml title="~/.openjarvis/config.toml"
[security]
enabled = true
scan_input = true
scan_output = true
mode = "warn"               # "warn" | "redact" | "block"
secret_scanner = true
pii_scanner = true
audit_log_path = "~/.openjarvis/audit.db"
enforce_tool_confirmation = true
```

### Configuration Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enabled` | `bool` | `true` | Enable the security subsystem |
| `scan_input` | `bool` | `true` | Scan user input messages |
| `scan_output` | `bool` | `true` | Scan model output content |
| `mode` | `str` | `"warn"` | Action on findings: `warn`, `redact`, or `block` |
| `secret_scanner` | `bool` | `true` | Run `SecretScanner` on all text |
| `pii_scanner` | `bool` | `true` | Run `PIIScanner` on all text |
| `audit_log_path` | `str` | `~/.openjarvis/audit.db` | Path to the SQLite audit log |
| `enforce_tool_confirmation` | `bool` | `true` | Require explicit confirmation before tool execution |

!!! tip "Start with warn, tighten later"
    `mode = "warn"` is a good starting point. It lets you observe what patterns are being triggered without disrupting normal usage. Switch to `"redact"` once you are satisfied that the scanner isn't producing too many false positives for your workload.

---

## Writing a Custom Scanner

Implement `BaseScanner` and pass an instance to `GuardrailsEngine`:

```python title="custom_scanner.py"
import re
from openjarvis.security._stubs import BaseScanner
from openjarvis.security.types import ScanFinding, ScanResult, ThreatLevel


class InternalUrlScanner(BaseScanner):
    """Detect internal service URLs that should not be shared externally."""

    scanner_id = "internal_urls"

    PATTERN = re.compile(r"https?://internal\.[a-z0-9.-]+\.[a-z]{2,}")

    def scan(self, text: str) -> ScanResult:
        findings = []
        for match in self.PATTERN.finditer(text):
            findings.append(ScanFinding(
                pattern_name="internal_url",
                matched_text=match.group(0),
                threat_level=ThreatLevel.MEDIUM,
                start=match.start(),
                end=match.end(),
                description="Internal service URL",
            ))
        return ScanResult(findings=findings)

    def redact(self, text: str) -> str:
        return self.PATTERN.sub("[REDACTED:internal_url]", text)


# Use with GuardrailsEngine
from openjarvis.security.guardrails import GuardrailsEngine
from openjarvis.security.types import RedactionMode

guarded = GuardrailsEngine(
    engine,
    scanners=[InternalUrlScanner()],
    mode=RedactionMode.REDACT,
)
```

---

## Privacy and data-boundary diagnostics

OpenJarvis provides three complementary security layers:

1. **Host scan** — `jarvis scan` (without flags) checks OS posture: disk encryption,
   cloud-sync agents, remote-access tools, and exposed engine ports.
2. **Config scan** — `jarvis scan --data-boundaries` audits application configuration,
   environment-variable presence, and known local runtime stores without reading
   private file contents. Use `--strict` in CI to fail on warn/fail findings.
3. **BoundaryGuard** — runtime guardrails (`GuardrailsEngine`, scanners, file policy)
   that redact or block secrets, PII, and sensitive paths during inference.

The host and config scans are offline diagnostics. BoundaryGuard enforces policy
during live agent runs. See [Data Boundary Scan](data-boundary-scan.md) for the
full config-scan reference.

---

## See Also

- [Data Boundary Scan](data-boundary-scan.md) — application config and local-store diagnostic (`jarvis scan --data-boundaries`)
- [Architecture: Security](../architecture/security.md) — pipeline design, event flow, and file policy integration
- [API Reference: Security](../api-reference/openjarvis/security/index.md) — full class and function signatures
- [Tools](tools.md) — how `FileReadTool` uses file policy
- [Configuration](../getting-started/configuration.md) — full config reference
