# External MCP Server Integration

OpenJarvis can extend agent capabilities by connecting to external [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers. This allows agents to use tools provided by services like Home Assistant, databases, custom APIs, or any MCP-compatible server -- without writing custom tool code.

## How It Works

When OpenJarvis starts, it reads the servers you added in **Settings → MCP servers** and the `[tools.mcp]` section in `config.toml`. For each configured server, it:

1. Opens a connection using the appropriate transport (Streamable HTTP or stdio).
2. Performs the MCP initialize handshake (protocol version negotiation and `initialized` notification).
3. Discovers available tools via `tools/list`.
4. Wraps each discovered tool as a standard `BaseTool` so agents can call them like any built-in tool.

If a server is unreachable or returns an error, OpenJarvis logs a warning and continues loading the remaining servers. One broken server does not prevent other tools from being available.

## Managing servers from Settings

Open **Settings → MCP servers** in the web UI or desktop app to add, edit,
enable/disable, delete and test servers without editing `config.toml`:

- **Streamable HTTP**: a URL plus optional authentication — a bearer token
  (`Authorization: Bearer <token>`) or a token sent in a custom header such as
  `X-API-Key`.
- **stdio**: a command and its arguments (one per line). Arguments are stored in
  plain text, so do not put secrets in them.
- **Only these tools / Hide these tools**: the same `include_tools` /
  `exclude_tools` filters described below.

**Test connection** runs the MCP handshake and lists the server's tools
(filtered tools are shown struck through). Errors never include the token.

Servers added this way are stored under `~/.openjarvis/mcp/`:

| File           | Contents                                                  |
|----------------|-----------------------------------------------------------|
| `servers.json` | Server records (no secrets).                              |
| `secrets.json` | Tokens, keyed by server id. Owner-only (`0600`).          |

Tokens are write-only: the API and UI only report whether one is saved. When
editing, leave the token blank to keep it, or tick **Remove saved token**.

Servers from `config.toml` still load as before. They appear in the list as
read-only (you can test them, but edit them in `config.toml`). Setting
`[tools.mcp] enabled = false` turns off every MCP server, including the ones
added in Settings.

MCP tools are discovered when the server starts, so **restart OpenJarvis**
after changing servers. The Settings page shows a notice until you do.

The same operations are available over HTTP at `/v1/mcp/servers`
(`GET`, `POST`), `/v1/mcp/servers/{id}` (`PUT`, `DELETE`),
`/v1/mcp/servers/{id}/test` and `/v1/mcp/servers/test` (test an unsaved
draft). Request bodies must be `application/json`.

## Configuration in config.toml

External MCP servers can also be configured in `config.toml` under `[tools.mcp]`. The
`servers` field accepts either inline JSON or a path to a JSON file:

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "homeassistant", "url": "http://172.16.3.1:9583/private_abc123"}]'
```

For larger configurations, keep the server objects in a separate file next to
`config.toml`:

```toml
[tools.mcp]
enabled = true
servers = "mcp-servers.json"
```

```json
[
  {
    "name": "homeassistant",
    "url": "http://172.16.3.1:9583/private_abc123"
  },
  {
    "name": "database",
    "command": "db-mcp-server",
    "args": ["--db", "postgres://localhost/mydb"]
  }
]
```

Relative paths are resolved from the directory containing `config.toml` and
must remain inside that directory. Absolute paths (including paths expanded
from `~`) are also supported. A file may contain either an array of server
objects or one server object, which OpenJarvis wraps in an array.

Inline `servers` values are **JSON-encoded strings** containing an array of
server objects. Each object defines one external MCP server.

!!! note
    An inline value must be a JSON string (with single-quote TOML delimiters
    around it), not a native TOML array. A file path is a normal TOML string.

## Server Config Schema

Each server object supports the following fields:

| Field            | Type           | Required | Description                                              |
|------------------|----------------|----------|----------------------------------------------------------|
| `name`           | string         | No       | Human-readable name used in log messages. Defaults to `<unnamed>`. |
| `url`            | string         | No*      | URL for Streamable HTTP transport.                       |
| `token`          | string         | No       | Token for HTTP servers, sent as `Authorization: Bearer <token>`. |
| `auth_header`    | string         | No       | Send `token` in this header instead (e.g. `X-API-Key`).  |
| `command`         | string         | No*      | Command to launch a stdio-based MCP server.              |
| `args`           | list of strings| No       | Arguments passed to the stdio command.                   |
| `include_tools`  | list of strings| No       | Whitelist of tool names to import. Only these tools are loaded. |
| `exclude_tools`  | list of strings| No       | Blacklist of tool names to skip. All other tools are loaded. |

*Either `url` or `command` must be provided. If neither is set, the server is skipped with a warning.

When both `include_tools` and `exclude_tools` are specified, the whitelist is applied first, then the blacklist filters the result.

## Examples

### Home Assistant via Streamable HTTP

Connect to the [ha-mcp](https://github.com/tevonsb/ha-mcp) Home Assistant add-on:

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "homeassistant", "url": "http://172.16.3.1:9583/private_abc123"}]'
```

This discovers all HA tools (entity control, automations, history, etc.) and makes them available to agents.

### Stdio Server

Launch a local MCP server as a subprocess:

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "myserver", "command": "python", "args": ["-m", "my_mcp_server"]}]'
```

OpenJarvis starts the process automatically, communicates via JSON-RPC over stdin/stdout, and terminates it on shutdown.

### Multiple Servers

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "homeassistant", "url": "http://172.16.3.1:9583/private_abc123"}, {"name": "database", "command": "db-mcp-server", "args": ["--db", "postgres://localhost/mydb"]}]'
```

### Tool Filtering

When a server exposes many tools but you only need a few, use `include_tools` to whitelist:

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "ha", "url": "http://172.16.3.1:9583/private_abc123", "include_tools": ["hassTurnOn", "hassTurnOff", "hassGetState"]}]'
```

To load everything except specific tools, use `exclude_tools`:

```toml
[tools.mcp]
enabled = true
servers = '[{"name": "ha", "url": "http://172.16.3.1:9583/private_abc123", "exclude_tools": ["hassCreateBackup", "hassDeleteBackup"]}]'
```

## Transport Types

### Streamable HTTP

Used when the `url` field is set. The transport sends JSON-RPC requests as HTTP POST to the given URL using `httpx`. It tracks the `Mcp-Session-Id` header across requests as required by the MCP Streamable HTTP specification.

**When to use:** Remote MCP servers, services running as HTTP endpoints (e.g., Home Assistant MCP add-on, cloud-hosted MCP servers).

**Connection parameters:**

- Connect timeout: 10 seconds
- Request timeout: 60 seconds

### Stdio

Used when the `command` field is set. OpenJarvis spawns the command as a subprocess and communicates via JSON-RPC lines on stdin/stdout.

**When to use:** Local MCP servers distributed as CLI tools, development/testing, servers that require filesystem access on the same machine.

!!! info "SSETransport alias"
    `SSETransport` is provided as a backward-compatible alias for `StreamableHTTPTransport`. Both refer to the same implementation.

## Error Handling

OpenJarvis handles MCP server failures gracefully:

- **Server unreachable:** A warning is logged and the server is skipped. All other servers and built-in tools continue to load normally.
- **Timeout:** HTTP requests time out after 60 seconds. The server is skipped with a warning.
- **Invalid config:** If the `servers` JSON is malformed or a server entry has neither `url` nor `command`, a warning is logged and that entry is skipped.
- **Tool discovery failure:** If `tools/list` fails on a server, the error is caught and the server is skipped.
- **Runtime tool call failure:** If a tool call to an external MCP server fails at runtime, it returns a `ToolResult` with `success=False` and the error message.

No single server failure causes OpenJarvis to crash or prevents other tools from working.

## Troubleshooting

### Server not discovered

1. Check that `[tools.mcp]` has `enabled = true`.
2. Verify the inline `servers` JSON is valid, or that the configured JSON file
   exists and is readable. A common mistake is using TOML arrays instead of a
   JSON string.
3. Check the OpenJarvis logs for warnings like `Failed to discover external MCP tools`.

### Connection refused / timeout

1. Verify the server is running and reachable from the OpenJarvis host: `curl -v http://host:port/`.
2. Check firewall rules between the OpenJarvis container and the MCP server.
3. For Docker deployments, ensure both containers are on the same network or use host IPs.

### Tools not appearing

1. Run with debug logging to see which tools were discovered.
2. Check if `include_tools` or `exclude_tools` filters are too restrictive.
3. Verify the MCP server actually exposes tools via `tools/list` (some servers only expose resources or prompts).

### Stdio server crashes immediately

1. Test the command manually: `python -m my_mcp_server` should start and wait for input on stdin.
2. Check stderr output in the OpenJarvis logs for error messages from the subprocess.
3. Ensure all dependencies for the MCP server are installed in the same environment.
