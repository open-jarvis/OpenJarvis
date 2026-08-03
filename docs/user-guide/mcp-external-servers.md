# External MCP servers

OpenJarvis can expose tools from explicitly configured Model Context Protocol
(MCP) servers. Discovery and execution are separate: discovering a tool never
authorizes the model to call it directly.

## Canonical execution path

Every model-reachable call uses the existing OpenJarvis path:

`ToolProposal → ToolActionService → CentralRiskPolicy → optional allow-once → MCP call → verification → TaskEvent/Trace`

Tool IDs are namespaced as `mcp__<server>__<tool>`. The server cannot choose
its capability, risk or approval boundary. Unknown tools default to **write**
(Level 3 and allow-once); the local user may classify a discovered tool as:

- **read**: Level 0;
- **prepare**: Level 2 with allow-once;
- **write**: Level 3 with allow-once;
- **blocked**: Level 4 and disabled.

MCP metadata and results are untrusted data. Remote descriptions are not copied
into the developer prompt, unsupported schemas are rejected, arguments are
validated against the retained schema, and result text cannot become a system
instruction. A successful protocol envelope is recorded separately from the
assistant's natural-language answer.

## Desktop Settings

Settings can add, enable, disable, remove and reconnect servers. They also show
connection state, discovered tools, last connection/error, Include/Exclude
filters and the local policy per tool. Configuration is stored in
`%OPENJARVIS_HOME%\state\mcp-servers.json`; it contains no token values.

Streamable HTTP configuration uses:

- a `http` or `https` URL without user info, query credentials or fragments;
- an optional `MCP_*_API_KEY` keyring reference;
- bounded connection/request timeouts.

Stdio configuration uses:

- an absolute executable path;
- at most 32 non-secret arguments;
- an optional `MCP_*_API_KEY` environment reference;
- a bounded response timeout and an interruptible owned process.

Do not put bearer tokens, passwords, API keys or database credentials in URLs
or stdio arguments. The stdio child does not inherit unrelated secret-looking
environment variables. Global Stop closes active MCP transports.

## Compatibility configuration

CLI/non-desktop deployments may retain the existing JSON-encoded TOML field:

```toml
[tools.mcp]
enabled = true
servers = '[{"server_id":"local-notes","transport":"stdio","command":"C:\\\\Tools\\\\notes-mcp.exe","args":[],"include_tools":["search_notes"]}]'
```

For HTTP, provide a normal endpoint and a token environment reference rather
than embedding a credential:

```toml
[tools.mcp]
enabled = true
servers = '[{"server_id":"internal-service","transport":"http","url":"https://mcp.example.invalid/mcp","token_env":"MCP_INTERNAL_SERVICE_API_KEY"}]'
```

The desktop registry is preferred because it validates and persists the
non-secret grant separately from the keyring value.

## Failure and recovery

Discovery isolates each server. One unavailable or invalid server is marked
disconnected without removing already healthy servers. Ordinary chat never
waits for a background reconnect. Reconnect explicitly performs discovery;
Include/Exclude filters are then applied before manifests are registered.

HTTP errors, stdio exits, invalid schemas and timeouts are reduced to safe
categories in normal UI. Raw tokens, headers, stderr and stack traces are not
returned. A runtime call failure becomes a failed ToolAction and must not be
presented as success.

## Recommended categories

The internal Windows desktop adapter is integrated and does not require an
external MCP server. GitHub, Google Drive, Gmail, Calendar, Outlook, Teams,
Slack and Notion are useful optional categories only when the user supplies a
compatible server and credentials. They are **not installed, connected or
verified** by this implementation. Existing Playwright, safe-shell and local
filesystem capabilities should be preferred over redundant external servers.

Use [the manual verification runbook](../jarvis-manual-verification.md) before
calling any configured MCP integration verified.
