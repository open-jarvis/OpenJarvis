# systemd Service (Linux)

OpenJarvis includes a systemd unit file for running the API server as a managed background service on Linux. This provides automatic startup on boot, crash recovery, and integration with standard Linux service management tools.

## Prerequisites

Before installing the service, ensure that:

1. OpenJarvis is installed in a virtual environment at `/opt/openjarvis/.venv` (or adjust paths accordingly).
2. A dedicated `openjarvis` system user exists (recommended for security).
3. An inference engine (such as Ollama) is running and accessible.

Create the user and installation directory:

```bash
sudo useradd --system --create-home --home-dir /opt/openjarvis openjarvis
sudo -u openjarvis python3 -m venv /opt/openjarvis/.venv
sudo -u openjarvis git clone https://github.com/open-jarvis/OpenJarvis.git /opt/openjarvis/OpenJarvis
cd /opt/openjarvis/OpenJarvis && sudo -u openjarvis uv sync --extra server
```

## Installing the Service

The unit binds `0.0.0.0`, so an **API key is required** — and the unit
declares `EnvironmentFile=/etc/openjarvis/env` (no `-` prefix), so it will
**fail to start** until that file exists with a key. Create it first:

```bash
sudo mkdir -p /etc/openjarvis
echo "OPENJARVIS_API_KEY=$(jarvis auth generate-key)" | sudo tee /etc/openjarvis/env
sudo chmod 600 /etc/openjarvis/env
```

Then copy the unit file, reload the daemon, and enable the service:

```bash
sudo cp deploy/systemd/openjarvis.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openjarvis
sudo systemctl start openjarvis
```

Clients must send `Authorization: Bearer <key>` on `/v1/*` and `/api/*`
requests. (If you instead bind to `127.0.0.1`, the key is optional and you
can drop the `EnvironmentFile` line.)

Verify it is running:

```bash
sudo systemctl status openjarvis
```

## Service File Reference

The provided unit file at `deploy/systemd/openjarvis.service`:

```ini
[Unit]
Description=OpenJarvis API Server
After=network.target

[Service]
Type=simple
User=openjarvis
WorkingDirectory=/opt/openjarvis
ExecStart=/opt/openjarvis/.venv/bin/jarvis serve --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5
Environment=HOME=/opt/openjarvis

[Install]
WantedBy=multi-user.target
```

### `[Unit]` Section

| Directive     | Value              | Description                                                                 |
|---------------|--------------------|-----------------------------------------------------------------------------|
| `Description` | `OpenJarvis API Server` | Human-readable name shown in `systemctl status` and logs.              |
| `After`       | `network.target`   | Delays startup until the network stack is available, since the server binds to a network socket and may need to reach a remote engine. |

### `[Service]` Section

| Directive          | Value                                                              | Description                                                                                     |
|--------------------|--------------------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| `Type`             | `simple`                                                           | The process started by `ExecStart` is the main service process. systemd considers the service started immediately. |
| `User`             | `openjarvis`                                                       | Runs the server as the `openjarvis` user rather than root, limiting the blast radius of any security issue. |
| `WorkingDirectory` | `/opt/openjarvis`                                                  | Sets the working directory for the process. This is where OpenJarvis looks for local files and writes data. |
| `ExecStart`        | `/opt/openjarvis/.venv/bin/jarvis serve --host 0.0.0.0 --port 8000` | The command to start the server. Uses the full path to the `jarvis` binary inside the virtual environment. |
| `Restart`          | `on-failure`                                                       | Automatically restarts the service if it exits with a non-zero exit code. Does not restart on clean shutdown (`systemctl stop`). |
| `RestartSec`       | `5`                                                                | Waits 5 seconds before attempting a restart, preventing rapid restart loops if the service crashes immediately on startup. |
| `Environment`      | `HOME=/opt/openjarvis`                                             | Sets the `HOME` environment variable so OpenJarvis finds its configuration at `~/.openjarvis/config.toml` (resolving to `/opt/openjarvis/.openjarvis/config.toml`). |

### `[Install]` Section

| Directive    | Value               | Description                                                                                 |
|--------------|---------------------|---------------------------------------------------------------------------------------------|
| `WantedBy`   | `multi-user.target` | The service starts when the system reaches multi-user mode (standard boot target for servers). `systemctl enable` creates a symlink under this target. |

## Configuration Options

### Changing the Bind Address and Port

Edit the `ExecStart` line to change the host or port:

```ini
ExecStart=/opt/openjarvis/.venv/bin/jarvis serve --host 127.0.0.1 --port 9000
```

!!! tip
    Binding to `127.0.0.1` restricts access to localhost only. Use this when running behind a reverse proxy like Nginx or Caddy.

### Setting the Engine and Model

Pass additional flags to `jarvis serve`:

```ini
ExecStart=/opt/openjarvis/.venv/bin/jarvis serve --host 0.0.0.0 --port 8000 --engine ollama --model qwen3:8b
```

### Adding Environment Variables

Add multiple `Environment` directives or use `EnvironmentFile` for complex configurations:

```ini
[Service]
Environment=HOME=/opt/openjarvis
Environment=OPENJARVIS_ENGINE_DEFAULT=vllm
Environment=OPENJARVIS_OLLAMA_HOST=http://localhost:11434
```

Or load from a file:

```ini
[Service]
EnvironmentFile=/opt/openjarvis/.env
```

### Changing the User

If you prefer a different service user, update both the `User` directive and the paths:

```ini
[Service]
User=myuser
WorkingDirectory=/home/myuser/openjarvis
ExecStart=/home/myuser/openjarvis/.venv/bin/jarvis serve --host 0.0.0.0 --port 8000
Environment=HOME=/home/myuser/openjarvis
```

### Using a Configuration File

Ensure the configuration file exists at the path where `HOME` points:

```bash
sudo -u openjarvis mkdir -p /opt/openjarvis/.openjarvis
sudo -u openjarvis cp config.toml /opt/openjarvis/.openjarvis/config.toml
```

The server reads `~/.openjarvis/config.toml` on startup, where `~` resolves from the `HOME` environment variable.

## Viewing Logs

OpenJarvis logs are captured by journald. View them with `journalctl`:

```bash
# View all logs for the service
sudo journalctl -u openjarvis

# Follow logs in real time
sudo journalctl -u openjarvis -f

# View logs since the last boot
sudo journalctl -u openjarvis -b

# View logs from the last hour
sudo journalctl -u openjarvis --since "1 hour ago"

# View only error-level messages
sudo journalctl -u openjarvis -p err
```

## Managing the Service

### Start, Stop, and Restart

```bash
# Start the service
sudo systemctl start openjarvis

# Stop the service
sudo systemctl stop openjarvis

# Restart the service (stop + start)
sudo systemctl restart openjarvis

# Reload configuration without full restart (sends SIGHUP)
sudo systemctl reload-or-restart openjarvis
```

### Check Status

```bash
sudo systemctl status openjarvis
```

Example output:

```
● openjarvis.service - OpenJarvis API Server
     Loaded: loaded (/etc/systemd/system/openjarvis.service; enabled; preset: enabled)
     Active: active (running) since Fri 2026-02-21 10:00:00 UTC; 2h ago
   Main PID: 12345 (jarvis)
      Tasks: 4 (limit: 4915)
     Memory: 256.0M
        CPU: 1min 23s
     CGroup: /system.slice/openjarvis.service
             └─12345 /opt/openjarvis/.venv/bin/python /opt/openjarvis/.venv/bin/jarvis serve --host 0.0.0.0 --port 8000
```

### Enable and Disable on Boot

```bash
# Enable automatic start on boot
sudo systemctl enable openjarvis

# Disable automatic start on boot
sudo systemctl disable openjarvis
```

### Apply Changes After Editing the Unit File

After modifying `/etc/systemd/system/openjarvis.service`, reload the systemd daemon and restart the service:

```bash
sudo systemctl daemon-reload
sudo systemctl restart openjarvis
```

## Running Alongside Ollama

If Ollama is also managed via systemd, you can add an ordering dependency so the OpenJarvis service waits for Ollama to start:

```ini
[Unit]
Description=OpenJarvis API Server
After=network.target ollama.service
Requires=ollama.service
```

| Directive  | Description                                                              |
|------------|--------------------------------------------------------------------------|
| `After`    | Ensures OpenJarvis starts after Ollama.                                  |
| `Requires` | If Ollama fails to start, OpenJarvis will not start either.              |

!!! note
    Use `Wants` instead of `Requires` if you want OpenJarvis to start even when Ollama is unavailable (for example, if you plan to start Ollama manually later).
