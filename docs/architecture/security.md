# Security Architecture

The security module is a cross-cutting concern that wraps the inference pipeline rather than replacing it. Scanners run on raw text strings independently of any model or agent, and the `GuardrailsEngine` decorator composes them around any `InferenceEngine` backend without changing the engine's public interface.

---

## Design Principles

- **Composable, not mandatory.** Security scanning is opt-in and composable. You wrap an engine with `GuardrailsEngine`; you do not configure a global interceptor.
- **Scanner-agnostic.** The `BaseScanner` ABC defines a two-method interface (`scan`, `redact`). Any scanner can be plugged in, including user-defined ones.
- **Fail-safe modes.** The three redaction modes (WARN, REDACT, BLOCK) cover a spectrum from visibility to enforcement, allowing gradual tightening without code changes.
- **Audit by default.** The `AuditLogger` records security events to SQLite so that findings are traceable after the fact.

---

## Scanner Pipeline

Each scan pass runs all registered scanners sequentially and merges their findings into a single `ScanResult`. The order of scanner execution does not affect correctness, only which patterns are reported first.

```mermaid
flowchart LR
    A[Raw Text] --> B[SecretScanner.scan]
    A --> C[PIIScanner.scan]
    B --> D{Merge findings}
    C --> D
    D --> E[ScanResult]
    E --> F{result.clean?}
    F -- Yes --> G[Return text unchanged]
    F -- No --> H{RedactionMode}
    H -- WARN --> I[Publish SECURITY_ALERT\nReturn text unchanged]
    H -- REDACT --> J[Run redact on all scanners\nReturn sanitized text]
    H -- BLOCK --> K[Publish SECURITY_BLOCK\nRaise SecurityBlockError]
```

The redaction step in REDACT mode applies each scanner's `redact()` method in sequence. Later scanners see the already-redacted output of earlier ones, so patterns do not interfere.

---

## GuardrailsEngine Wrapper Pattern

`GuardrailsEngine` implements the full `InferenceEngine` ABC and delegates every call to a wrapped engine instance. This means any engine — `OllamaEngine`, `VLLMEngine`, `LlamaCppEngine` — can be made security-aware without modifying the engine itself.

```mermaid
classDiagram
    class InferenceEngine {
        <<abstract>>
        +generate(messages, model) dict
        +stream(messages, model) AsyncIterator
        +list_models() list
        +health() bool
    }
    class OllamaEngine {
        +generate(...)
        +stream(...)
    }
    class GuardrailsEngine {
        -_engine InferenceEngine
        -_scanners list
        -_mode RedactionMode
        +generate(messages, model) dict
        +stream(messages, model) AsyncIterator
        +list_models() list
        +health() bool
    }
    InferenceEngine <|-- OllamaEngine
    InferenceEngine <|-- GuardrailsEngine
    GuardrailsEngine o-- InferenceEngine : wraps
```

Because `GuardrailsEngine` is itself an `InferenceEngine`, it can be nested arbitrarily (for example, wrapped again in an instrumented engine) or passed to any code that accepts an engine.

### generate() Call Sequence

```mermaid
sequenceDiagram
    participant C as Caller
    participant G as GuardrailsEngine
    participant S as Scanners
    participant E as Wrapped Engine

    C->>G: generate(messages, model)
    G->>S: scan(message.content) for each message
    S-->>G: ScanResult
    alt findings detected
        G->>G: _handle_findings(text, result, "input")
        note over G: WARN: publish event, pass through
        note over G: REDACT: run redact(), replace content
        note over G: BLOCK: raise SecurityBlockError
    end
    G->>E: generate(messages, model)
    E-->>G: response dict
    G->>S: scan(response["content"])
    S-->>G: ScanResult
    alt findings detected
        G->>G: _handle_findings(content, result, "output")
    end
    G-->>C: response dict (possibly sanitized)
```

### stream() Behavior

For streaming, the engine yields tokens to the caller in real time. The security layer accumulates the full output and scans it after the stream ends. Because the scan is post-hoc, BLOCK mode cannot prevent delivery of streamed tokens — it only applies to the input side.

```mermaid
sequenceDiagram
    participant C as Caller
    participant G as GuardrailsEngine
    participant E as Wrapped Engine
    participant S as Scanners

    C->>G: stream(messages, model)
    G->>S: scan inputs (before streaming)
    G->>E: stream(messages, model)
    loop each token
        E-->>G: token
        G-->>C: yield token
    end
    G->>S: scan(accumulated output)
    alt findings detected
        G->>G: publish SECURITY_ALERT (stream_post_hoc)
    end
```

---

## Event Flow

Security events flow through the `EventBus` using three event types:

| Event | When Published | Payload Keys |
|-------|----------------|--------------|
| `SECURITY_SCAN` | (Reserved for future use) | — |
| `SECURITY_ALERT` | Findings detected in WARN or REDACT mode | `direction`, `findings`, `mode` |
| `SECURITY_BLOCK` | Findings detected in BLOCK mode | `direction`, `findings`, `mode` |

The `direction` field is either `"input"` or `"output"`. The `findings` value is a list of dicts with keys `pattern`, `threat`, and `description`.

The `AuditLogger` subscribes to all three event types and writes them to SQLite. This subscription is established at construction time:

```mermaid
flowchart TB
    A[GuardrailsEngine] -->|SECURITY_ALERT| B[EventBus]
    A -->|SECURITY_BLOCK| B
    B --> C[AuditLogger._on_event]
    C --> D[SQLite audit.db]
    B --> E[Other subscribers\ne.g. logging, alerting]
```

---

## File Policy Integration

The file policy (`file_policy.py`) operates independently of the scanner pipeline. It answers a single yes/no question: is this file path considered sensitive?

### Integration Points

**FileReadTool** calls `is_sensitive_file()` before reading any path. If the path matches a sensitive pattern, the tool returns an error rather than the file contents. This cannot be bypassed at the tool level.

**Memory ingest path** (`memory/ingest.py`) uses `filter_sensitive_paths()` to remove sensitive files from a directory listing before indexing. Files matching sensitive patterns are silently skipped.

```mermaid
flowchart LR
    A[FileReadTool.execute] --> B{is_sensitive_file?}
    B -- Yes --> C[Return error: sensitive file blocked]
    B -- No --> D[Read and return file contents]

    E[memory ingest_path] --> F[glob directory]
    F --> G[filter_sensitive_paths]
    G --> H[Index remaining files]
```

The file policy does not publish events or use the event bus. It is a pure function — deterministic, stateless, and side-effect-free.

---

## Audit Logging Architecture

`AuditLogger` maintains a single SQLite table (`security_events`) with the following schema:

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER PRIMARY KEY` | Auto-increment row ID |
| `timestamp` | `REAL` | Unix timestamp of the event |
| `event_type` | `TEXT` | `SecurityEventType` value string |
| `findings_json` | `TEXT` | JSON-encoded list of `ScanFinding` dicts |
| `content_preview` | `TEXT` | Short preview of the scanned content |
| `action_taken` | `TEXT` | Mode string (`warn`, `redact`, `block`) |

The database is written in append-only mode. There is no built-in rotation or truncation — manage retention externally by deleting old entries with SQLite tooling or by using a path-per-session audit log.

The default path is `~/.friday_ai/audit.db`, configurable via `security.audit_log_path` in `config.toml`.

---

## Relationship to Other Modules

| Module | How Security Integrates |
|--------|------------------------|
| Engine | `GuardrailsEngine` wraps any `InferenceEngine` |
| Tools | `FileReadTool` calls `is_sensitive_file()` |
| Memory | Ingest path calls `filter_sensitive_paths()` |
| EventBus | Security events published to `SECURITY_ALERT`, `SECURITY_BLOCK` |
| Config | `SecurityConfig` dataclass loaded from `[security]` in `config.toml` |

---

## See Also

- [User Guide: Security](../user-guide/security.md) — how to configure and use the security system
- [API Reference: Security](../api-reference/friday_ai/security/index.md) — complete class and function signatures
- [Architecture: Query Flow](query-flow.md) — where security sits in the overall request lifecycle
