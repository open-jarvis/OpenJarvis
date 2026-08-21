# API Server

OpenJarvis includes an OpenAI-compatible API server built on FastAPI and uvicorn. It exposes chat completion, model listing, and health check endpoints, making it a drop-in replacement for the OpenAI API when working with local models.

## Starting the Server

The server requires the `[server]` extra (FastAPI + uvicorn):

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync --extra server
```

Start with default settings:

```bash
jarvis serve
```

For a cloud-hosted example, see [Deploy on Render](render.md). Its free-tier
Blueprint is intended for evaluation only because local OpenJarvis state is
ephemeral.

The server reads defaults from `~/.openjarvis/config.toml` and auto-detects available engines and models. Override any option via CLI flags:

```bash
jarvis serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b --agent orchestrator
```

### CLI Options

| Option               | Description                                                                  | Default           |
|----------------------|------------------------------------------------------------------------------|--------------------|
| `--host`             | Network address to bind to                                                   | From config (`0.0.0.0`) |
| `--port`             | Port number to listen on                                                     | From config (`8000`)    |
| `-e` / `--engine`    | Inference engine backend (`ollama`, `vllm`, `llamacpp`, `sglang`)            | Auto-detected      |
| `-m` / `--model`     | Default model for completions                                                | First available     |
| `-a` / `--agent`     | Agent for non-streaming requests (`simple`, `orchestrator`, `react`, `openhands`) | From config (`orchestrator`) |

On startup, the server prints a summary:

```
Starting OpenJarvis API server
  Engine: ollama
  Model:  qwen3:8b
  Agent:  orchestrator
  URL:    http://0.0.0.0:8000
```

!!! warning "Server dependency check"
    If the `[server]` extra is not installed, `jarvis serve` exits with a clear error message explaining how to install the required dependencies.

## Endpoints

### `POST /v1/chat/completions`

The primary endpoint for generating chat completions. Accepts the same request format as the OpenAI Chat Completions API.

#### Request Body

```json
{
  "model": "qwen3:8b",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the capital of France?"}
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false,
  "tools": null
}
```

| Parameter     | Type              | Default | Description                                                  |
|---------------|-------------------|---------|--------------------------------------------------------------|
| `model`       | `string`          | --      | **Required.** Model identifier to use for generation.        |
| `messages`    | `array`           | --      | **Required.** Array of message objects with `role` and `content`. |
| `temperature` | `float`           | `0.7`   | Sampling temperature (0.0 to 2.0).                           |
| `max_tokens`  | `integer`         | `1024`  | Maximum number of tokens to generate.                        |
| `stream`      | `boolean`         | `false` | Whether to stream the response via SSE.                      |
| `tools`       | `array` or `null` | `null`  | Tool definitions in OpenAI function-calling format.          |

Each message object:

| Field          | Type              | Description                                           |
|----------------|-------------------|-------------------------------------------------------|
| `role`         | `string`          | One of `system`, `user`, `assistant`, or `tool`.      |
| `content`      | `string`          | The message content.                                  |
| `name`         | `string` or `null`| Optional name for the message author.                 |
| `tool_calls`   | `array` or `null` | Tool calls made by the assistant (in assistant messages). |
| `tool_call_id` | `string` or `null`| ID of the tool call this message responds to (in tool messages). |

#### Response (Non-Streaming)

```json
{
  "id": "chatcmpl-abc123def456",
  "object": "chat.completion",
  "created": 1740100800,
  "model": "qwen3:8b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "The capital of France is Paris.",
        "tool_calls": null
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 8,
    "total_tokens": 33
  }
}
```

When an agent is configured on the server, non-streaming requests are routed through the agent, which can perform multi-turn reasoning with tool calls before returning a final response. When no agent is configured, requests go directly to the inference engine.

#### Tool Calls

When `tools` are provided in the request, the engine may return `tool_calls` in the assistant message:

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
          {
            "id": "call_abc123",
            "type": "function",
            "function": {
              "name": "calculator",
              "arguments": "{\"expression\": \"2 + 2\"}"
            }
          }
        ]
      },
      "finish_reason": "tool_calls"
    }
  ]
}
```

### `GET /v1/models`

Lists all models available on the configured inference engine.

#### Response

```json
{
  "object": "list",
  "data": [
    {
      "id": "qwen3:8b",
      "object": "model",
      "created": 1740100800,
      "owned_by": "openjarvis"
    },
    {
      "id": "llama3.1:8b",
      "object": "model",
      "created": 1740100800,
      "owned_by": "openjarvis"
    }
  ]
}
```

### `GET /health`

Health check endpoint that verifies the inference engine is responsive.

#### Response (Healthy)

HTTP 200:

```json
{"status": "ok"}
```

#### Response (Unhealthy)

HTTP 503:

```json
{"detail": "Engine unhealthy"}
```

### `GET /dashboard`

Serves the built-in Savings Dashboard, an HTML page that displays real-time statistics on inference calls served locally and estimated cost savings compared to cloud API providers. The dashboard auto-refreshes every 5 seconds by polling the `/v1/savings` endpoint.

### `GET /v1/channels`

List registered channel backends and their connection status.

#### Response

```json
{
  "channels": ["slack", "discord", "telegram"]
}
```

### `POST /v1/channels/send`

Send a message to a specific channel.

#### Request Body

```json
{
  "target": "slack",
  "message": "Hello from Jarvis!"
}
```

#### Response

```json
{
  "status": "sent",
  "target": "slack"
}
```

### `GET /v1/channels/status`

Show connection status for all configured channels.

#### Response

```json
{
  "channels": {
    "slack": "connected",
    "discord": "connected",
    "telegram": "disconnected"
  }
}
```

!!! note "Channel endpoints"
    Channel endpoints require `[channel] enabled = true` in your config and platform-specific credentials configured in `[channel.<platform>]` sub-sections. When not configured, `GET /v1/channels` returns an empty list and other channel endpoints return 503.

### WebSocket endpoints

- `WS /v1/chat/stream` streams interactive chat messages.
- `WS /v1/agents/events` streams agent lifecycle events and accepts an optional
  `agent_id` query parameter as a filter.

When `OPENJARVIS_API_KEY` or `[server.auth].api_key` is configured,
programmatic WebSocket clients should send the same
`Authorization: Bearer <key>` header used by HTTP requests. Browsers cannot set
that header on a WebSocket handshake, so browser clients must offer exactly
these two subprotocol values:

1. `openjarvis.auth.v1`
2. `openjarvis.key.b64url.<encoded-key>`, where `<encoded-key>` is the unpadded
   base64url encoding of the API key's UTF-8 bytes

The server selects `openjarvis.auth.v1` in its handshake response. The built-in
frontend handles this encoding automatically. Base64url is only a transport
encoding, not encryption; use `wss://` for remote connections and treat the
`Sec-WebSocket-Protocol` request header as credential-bearing.

!!! warning "WebSocket authentication migration"
    The former `?token=<key>` query parameter is not accepted because request
    URLs commonly appear in access logs and browser history. Existing custom
    WebSocket clients must migrate to `Authorization` or the browser
    subprotocol format above.

## Streaming via SSE

When `"stream": true` is set in the request, the server returns a `text/event-stream` response using Server-Sent Events (SSE). The response follows the same format as the OpenAI streaming API.

Each event is a `data:` line containing a JSON chunk, followed by a blank line:

```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1740100800,"model":"qwen3:8b","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1740100800,"model":"qwen3:8b","choices":[{"index":0,"delta":{"content":"The"},"finish_reason":null}]}

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1740100800,"model":"qwen3:8b","choices":[{"index":0,"delta":{"content":" capital"},"finish_reason":null}]}

...

data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1740100800,"model":"qwen3:8b","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

The stream follows this sequence:

1. **Role chunk** -- first chunk contains `"delta": {"role": "assistant"}` with no content.
2. **Content chunks** -- subsequent chunks each contain a `"delta": {"content": "..."}` with one or more tokens.
3. **Finish chunk** -- a chunk with an empty `delta` and `"finish_reason": "stop"`.
4. **Done signal** -- the literal string `data: [DONE]` indicates the stream is complete.

Response headers include `Cache-Control: no-cache` and `Connection: keep-alive` for proper SSE behavior.

## Client Examples

=== "curl"

    **Non-streaming request:**

    ```bash
    curl http://localhost:8000/v1/chat/completions \
      -H "Content-Type: application/json" \
      -d '{
        "model": "qwen3:8b",
        "messages": [
          {"role": "user", "content": "Explain quantum computing in one paragraph."}
        ],
        "temperature": 0.7,
        "max_tokens": 256
      }'
    ```

    **Streaming request:**

    ```bash
    curl http://localhost:8000/v1/chat/completions \
      -H "Content-Type: application/json" \
      -N \
      -d '{
        "model": "qwen3:8b",
        "messages": [
          {"role": "user", "content": "Write a haiku about programming."}
        ],
        "stream": true
      }'
    ```

    **List models:**

    ```bash
    curl http://localhost:8000/v1/models
    ```

    **Health check:**

    ```bash
    curl http://localhost:8000/health
    ```

=== "Python (openai)"

    The OpenAI Python library works as a drop-in client by pointing `base_url` at the local server:

    ```python
    from openai import OpenAI

    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed",  # Required by the library but not validated
    )

    # Non-streaming
    response = client.chat.completions.create(
        model="qwen3:8b",
        messages=[
            {"role": "user", "content": "What is the capital of France?"}
        ],
        temperature=0.7,
        max_tokens=256,
    )
    print(response.choices[0].message.content)

    # Streaming
    stream = client.chat.completions.create(
        model="qwen3:8b",
        messages=[
            {"role": "user", "content": "Write a short poem about AI."}
        ],
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()

    # List models
    models = client.models.list()
    for model in models.data:
        print(model.id)
    ```

=== "Python (httpx)"

    Using `httpx` for direct HTTP requests:

    ```python
    import httpx
    import json

    BASE_URL = "http://localhost:8000"

    # Non-streaming request
    response = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": "qwen3:8b",
            "messages": [
                {"role": "user", "content": "What is the capital of France?"}
            ],
            "temperature": 0.7,
            "max_tokens": 256,
        },
    )
    data = response.json()
    print(data["choices"][0]["message"]["content"])

    # Streaming request
    with httpx.stream(
        "POST",
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": "qwen3:8b",
            "messages": [
                {"role": "user", "content": "Write a haiku about code."}
            ],
            "stream": True,
        },
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data: ") and line != "data: [DONE]":
                chunk = json.loads(line[6:])
                content = chunk["choices"][0]["delta"].get("content", "")
                if content:
                    print(content, end="", flush=True)
    print()

    # List models
    response = httpx.get(f"{BASE_URL}/v1/models")
    for model in response.json()["data"]:
        print(model["id"])

    # Health check
    response = httpx.get(f"{BASE_URL}/health")
    print(response.json())
    ```

## Configuration via `config.toml`

The `[server]` section of `~/.openjarvis/config.toml` controls default server behavior:

```toml
[server]
host = "0.0.0.0"
port = 8000
agent = "orchestrator"
model = ""
workers = 1
```

| Key       | Type      | Default         | Description                                                                |
|-----------|-----------|-----------------|----------------------------------------------------------------------------|
| `host`    | `string`  | `"0.0.0.0"`    | Network address to bind to. Use `"127.0.0.1"` for localhost-only access.   |
| `port`    | `integer` | `8000`          | Port number.                                                               |
| `agent`   | `string`  | `"orchestrator"`| Default agent for non-streaming requests. Set to `""` for direct engine mode. |
| `model`   | `string`  | `""`            | Default model name. When empty, falls back to `[intelligence] default_model` or the first model discovered on the engine. |
| `workers` | `integer` | `1`             | Number of uvicorn workers (for future use).                                |

CLI flags override config file values. For example, `jarvis serve --port 9000` overrides the `port` setting in the config file.

The server also reads from other config sections at startup:

- **`[engine]`** -- determines which inference backend to connect to and its host URL.
- **`[intelligence]`** -- provides the fallback `default_model` when no model is specified.
- **`[agent]`** -- supplies `max_turns` for multi-turn agents like `orchestrator`.

## Running Behind a Reverse Proxy

For production deployments, run OpenJarvis behind a reverse proxy like Nginx or Caddy for TLS termination, rate limiting, and authentication.

### Nginx

```nginx
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 443 ssl;
    server_name jarvis.example.com;

    ssl_certificate /etc/ssl/certs/jarvis.pem;
    ssl_certificate_key /etc/ssl/private/jarvis.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket upgrade support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        # SSE streaming support
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}
```

!!! important "Disable buffering for SSE"
    The `proxy_buffering off` directive is critical for streaming responses. Without it, Nginx buffers the SSE chunks and delivers them in batches, defeating the purpose of streaming.

### Caddy

```
jarvis.example.com {
    reverse_proxy 127.0.0.1:8000 {
        flush_interval -1
    }
}
```

The `flush_interval -1` setting disables response buffering, which is required for SSE streaming.

### Bind to Localhost

When running behind a reverse proxy, bind the server to `127.0.0.1` so it only accepts connections from the proxy:

```bash
jarvis serve --host 127.0.0.1 --port 8000
```

Or in `config.toml`:

```toml
[server]
host = "127.0.0.1"
port = 8000
```
