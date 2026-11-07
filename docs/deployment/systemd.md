# systemd Service (Linux)

FridayAI includes a systemd unit file for running the API server as a managed background service on Linux. This provides automatic startup on boot, crash recovery, and integration with standard Linux service management tools.

## Prerequisites

Before installing the service, ensure that:

1. FridayAI is installed in a virtual environment at `/opt/friday_ai/.venv` (or adjust paths accordingly).
2. A dedicated `friday_ai` system user exists (recommended for security).
3. An inference engine (such as Ollama) is running and accessible.

Create the user and installation directory:

```bash
sudo useradd --system --create-home --home-dir /opt/friday_ai friday_ai
sudo -u friday_ai python3 -m venv /opt/friday_ai/.venv
sudo -u friday_ai git clone https://github.com/open-jarvis/FridayAI.git /opt/friday_ai/FridayAI
cd /opt/friday_ai/FridayAI && sudo -u friday_ai uv sync --extra server
```

## Installing the Service

The unit binds `0.0.0.0`, so an **API key is required** — and the unit
declares `EnvironmentFile=/etc/friday_ai/env` (no `-` prefix), so it will
**fail to start** until that file exists with a key. Create it first:

```bash
sudo mkdir -p /etc/friday_ai
echo "FRIDAY_AI_API_KEY=$(friday auth generate-key)" | sudo tee /etc/friday_ai/env
sudo chmod 600 /etc/friday_ai/env
```

Then copy the unit file, reload the daemon, and enable the service:

```bash
sudo cp deploy/systemd/friday_ai.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable friday_ai
sudo systemctl start friday_ai
```

Clients must send `Authorization: Bearer <key>` on `/v1/*` and `/api/*`
requests. (If you instead bind to `127.0.0.1`, the key is optional and you
can drop the `EnvironmentFile` line.)

Verify it is running:

```bash
sudo systemctl status friday_ai
```

## Service File Reference

The provided unit file at `deploy/systemd/friday_ai.service`:

```ini
[Unit]
Description=FridayAI API Server
After=network.target

[Service]
Type=simple
User=friday_ai
WorkingDirectory=/opt/friday_ai
ExecStart=/opt/friday_ai/.venv/bin/friday serve --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
Environment=HOME=/opt/friday_ai

[Install]
WantedBy=multi-user.target
```

### `[Unit]` Section

| Directive     | Value              | Description                                                                 |
|---------------|--------------------|-----------------------------------------------------------------------------|
| `Description` | `FridayAI API Server` | Human-readable name shown in `systemctl status` and logs.              |
| `After`       | `network.target`   | Delays startup until the network stack is available, since the server binds to a network socket and may need to reach a remote engine. |

### `[Service]` Section

| Directive          | Value                                                              | Description                                                                                     |
|--------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| `Type`             | `simple`                                                           | The process started by `ExecStart` is the main service process. systemd considers the service started immediately. |
| `User`             | `friday_ai`                                                       | Runs the server as the `friday_ai` user rather than root, limiting the blast radius of any security issue. |
| `WorkingDirectory` | `/opt/friday_ai`                                                  | Sets the working directory for the process. This is where FridayAI looks for local files and writes data. |
| `ExecStart`        | `/opt/friday_ai/.venv/bin/friday serve --host 0.0.0.0 --port 8000` | The command to start the server. Uses the full path to the `friday` binary inside the virtual environment. |
| `Restart`          | `on-failure`                                                       | Automatically restarts the service if it exits with a non-zero exit code. Does not restart on clean shutdown (`systemctl stop`). |
| `RestartSec`       | `5`                                                                | Waits 5 seconds before attempting a restart, preventing rapid restart loops if the service crashes immediately on startup. |
| `Environment`      | `HOME=/opt/friday_ai`                                             | Sets the `HOME` environment variable so FridayAI finds its configuration at `~/.friday_ai/config.toml` (resolving to `/opt/friday_ai/.friday_ai/config.toml`). |

### `[Install]` Section

| Directive    | Value               | Description                                                                                 |
|--------------|---------------------|---------------------------------------------------------------------------------------------|
| `WantedBy`   | `multi-user.target` | The service starts when the system reaches multi-user mode (standard boot target for servers). `systemctl enable` creates a symlink under this target. |

## Configuration Options

### Changing the Bind Address and Port

Edit the `ExecStart` line to change the host or port:

```ini
ExecStart=/opt/friday_ai/.venv/bin/friday serve --host 127.0.0.1 --port 9000
```

!!! tip
    Binding to `127.0.0.1` restricts access to localhost only. Use this when running behind a reverse proxy like Nginx or Caddy.

### Setting the Engine and Model

Pass additional flags to `friday serve`:

```ini
ExecStart=/opt/friday_ai/.venv/bin/friday serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b
```

### Adding Environment Variables

Add multiple `Environment` directives or use `EnvironmentFile` for complex configurations:

```ini
[Service]
Environment=HOME=/opt/friday_ai
Environment=FRIDAY_AI_ENGINE_DEFAULT=vllm
Environment=FRIDAY_AI_OLLAMA_HOST=http://localhost:11434
```

Or load from a file:

```ini
[Service]
EnvironmentFile=/opt/friday_ai/.env
```

### Changing the User

If you prefer a different service user, update both the `User` directive and the paths:

```ini
[Service]
User=myuser
WorkingDirectory=/home/myuser/friday_ai
ExecStart=/home/myuser/friday_ai/.venv/bin/friday serve --host 0.0.0.0 --port 8000
Environment=HOME=/home/myuser/friday_ai
```

### Using a Configuration File

Ensure the configuration file exists at the path where `HOME` points:

```bash
sudo -u friday_ai mkdir -p /opt/friday_ai/.friday_ai
sudo -u friday_ai cp config.toml /opt/friday_ai/.friday_ai/config.toml
```

The server reads `~/.friday_ai/config.toml` on startup, where `~` resolves from the `HOME` environment variable.

## Viewing Logs

FridayAI logs are captured by journald. View them with `journalctl`:

```bash
# View all logs for the service
sudo journalctl -u friday_ai

# Follow logs in real time
sudo journalctl -u friday_ai -f

# View logs since the last boot
sudo journalctl -u friday_ai -b

# View logs from the last hour
sudo journalctl -u friday_ai --since "1 hour ago"

# View only error-level messages
sudo journalctl -u friday_ai -p err
```

## Managing the Service

### Start, Stop, and Restart

```bash
# Start the service
sudo systemctl start friday_ai

# Stop the service
sudo systemctl stop friday_ai

# Restart the service (stop + start)
sudo systemctl restart friday_ai

# Reload configuration without full restart (sends SIGHUP)
sudo systemctl reload-or-restart friday_ai
```

### Check Status

```bash
sudo systemctl status friday_ai
```

Example output:

```
● friday_ai.service - FridayAI API Server
     Loaded: loaded (/etc/systemd/system/friday_ai.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-02-21 10:00:00 UTC; 2h ago
   Main PID: 12345 (friday)
      Tasks: 4 (limit: 4915)
     Memory: 256.0M
        CPU: 1min 23s
     CGroup: /system.slice/friday_ai.service
             └─12345 /opt/friday_ai/.venv/bin/python /opt/friday_ai/.venv/bin/friday serve --host 0.0.0.0 --port 8000
```

### Enable and Disable on Boot

```bash
# Enable automatic start on boot
sudo systemctl enable friday_ai

# Disable automatic start on boot
sudo systemctl disable friday_ai
```

### Apply Changes After Editing the Unit File

After modifying `/etc/systemd/system/friday_ai.service`, reload the systemd daemon and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart friday_ai
```

## Running Alongside Ollama

If Ollama is also managed via systemd, you can add an ordering dependency so the FridayAI service waits for Ollama to start:

```ini
[Unit]
Description=FridayAI API Server
After=network.target ollama.service
Requires=ollama.service
```

| Directive  | Description                                                              |
|------------|--------------------------------------------------------------------------|
| `After`    | Ensures FridayAI starts after Ollama.                                  |
| `Requires` | If Ollama fails to start, FridayAI will not start either.              |

!!! note
    Use `Wants` instead of `Requires` if you want FridayAI to start even when Ollama is unavailable (for example, if you plan to start Ollama manually later).
