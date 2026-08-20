# launchd Service (macOS)

OpenJarvis includes a launchd property list (plist) for running the API server as a background service on macOS. This provides automatic startup at login, automatic restart if the process exits, and log capture.

## Prerequisites

Before installing the service, ensure that OpenJarvis is installed and the `jarvis` command is available at `/usr/local/bin/jarvis`. If you installed via `uv` or `pip` with a different prefix, adjust the path in the plist accordingly.

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git && cd OpenJarvis && uv sync --extra server
which jarvis  # Verify the installation path
```

Also ensure that an inference engine (such as Ollama) is running and accessible on the machine.

## Installing the Service

Copy the plist file to `~/Library/LaunchAgents` and load it:

```bash
cp deploy/launchd/com.openjarvis.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.openjarvis.plist
```

The service starts immediately (due to `RunAtLoad`) and will automatically restart at each login.

!!! note "Binds loopback by default"
    The plist binds `127.0.0.1` — reachable from this Mac but not the network,
    the right default for a personal device, and no API key is needed. To
    expose it on your LAN, change the host to `0.0.0.0` **and** uncomment the
    `EnvironmentVariables` block to set `OPENJARVIS_API_KEY`
    (`jarvis auth generate-key`); an unauthenticated `0.0.0.0` server refuses
    to start.

Verify it is running:

```bash
launchctl list | grep openjarvis
```

You should see a line with the PID and the label `com.openjarvis`. A `0` in the status column indicates the service is running normally.

Confirm the server is responding:

```bash
curl http://localhost:8000/health
```

## Plist Reference

The provided plist file at `deploy/launchd/com.openjarvis.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openjarvis</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/jarvis</string>
        <string>serve</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>8000</string>
    </array>
    <!-- To expose on the LAN: set host to 0.0.0.0 and uncomment this block.
    <key>EnvironmentVariables</key>
    <dict>
        <key>OPENJARVIS_API_KEY</key>
        <string>REPLACE_WITH_A_REAL_KEY</string>
    </dict>
    -->
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/openjarvis.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/openjarvis.stderr.log</string>
</dict>
</plist>
```

### Key-by-Key Explanation

| Key                  | Value                          | Description                                                                                          |
|----------------------|--------------------------------|------------------------------------------------------------------------------------------------------|
| `Label`              | `com.openjarvis`               | Unique identifier for the service. Used with `launchctl` commands to manage the service.             |
| `ProgramArguments`   | `["/usr/local/bin/jarvis", "serve", "--host", "127.0.0.1", "--port", "8000"]` | The command and arguments to execute. Binds loopback by default; see the note above to expose on the LAN with an API key. |
| `RunAtLoad`          | `true`                         | Start the service immediately when the plist is loaded (and on each login).                          |
| `KeepAlive`          | `true`                         | Automatically restart the service if it exits for any reason. launchd monitors the process and relaunches it. |
| `StandardOutPath`    | `/tmp/openjarvis.stdout.log`   | File where standard output is written. Contains server startup messages and access logs.             |
| `StandardErrorPath`  | `/tmp/openjarvis.stderr.log`   | File where standard error is written. Contains error messages and stack traces.                      |

## Viewing Logs

Server output is written to the two log files specified in the plist:

```bash
# View standard output (startup messages, access logs)
cat /tmp/openjarvis.stdout.log

# View standard error (errors, warnings)
cat /tmp/openjarvis.stderr.log

# Follow logs in real time
tail -f /tmp/openjarvis.stdout.log /tmp/openjarvis.stderr.log
```

!!! tip "Persistent log location"
    Files in `/tmp` may be cleared on reboot. For persistent logs, change the paths in the plist to a permanent location:

    ```xml
    <key>StandardOutPath</key>
    <string>/Users/yourname/.openjarvis/openjarvis.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/yourname/.openjarvis/openjarvis.stderr.log</string>
    ```

    After changing the plist, unload and reload the service for the changes to take effect.

## Managing the Service

### Loading and Unloading

```bash
# Load the service (starts it due to RunAtLoad)
launchctl load ~/Library/LaunchAgents/com.openjarvis.plist

# Unload the service (stops it and prevents it from starting at login)
launchctl unload ~/Library/LaunchAgents/com.openjarvis.plist
```

### Starting and Stopping

If the service is loaded but you want to manually stop or start it without unloading:

```bash
# Stop the service
launchctl stop com.openjarvis

# Start the service
launchctl start com.openjarvis
```

!!! warning
    Because `KeepAlive` is set to `true`, using `launchctl stop` will cause launchd to restart the service almost immediately. To fully stop the service, use `launchctl unload` instead.

### Checking Status

```bash
# List all loaded services matching "openjarvis"
launchctl list | grep openjarvis
```

The output columns are:

| Column | Description                                                    |
|--------|----------------------------------------------------------------|
| PID    | Process ID (or `-` if not running)                             |
| Status | Last exit status (`0` = normal)                                |
| Label  | The service label (`com.openjarvis`)                           |

## Configuration Changes

### Changing the Port or Host

Edit the `ProgramArguments` array in the plist. Each argument must be a separate `<string>` element:

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/local/bin/jarvis</string>
    <string>serve</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>9000</string>
</array>
```

### Specifying an Engine and Model

Add additional arguments to the array:

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/local/bin/jarvis</string>
    <string>serve</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8000</string>
    <string>--engine</string>
    <string>ollama</string>
    <string>--model</string>
    <string>qwen3:8b</string>
</array>
```

### Setting Environment Variables

Add an `EnvironmentVariables` dictionary to the plist:

```xml
<key>EnvironmentVariables</key>
<dict>
    <key>OPENJARVIS_ENGINE_DEFAULT</key>
    <string>ollama</string>
    <key>OPENJARVIS_OLLAMA_HOST</key>
    <string>http://localhost:11434</string>
</dict>
```

### Using a Different `jarvis` Binary Path

If `jarvis` is installed in a virtual environment or a non-standard location, update the first element of `ProgramArguments`:

```xml
<key>ProgramArguments</key>
<array>
    <string>/Users/yourname/.local/bin/jarvis</string>
    <string>serve</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8000</string>
</array>
```

### Applying Changes

After editing the plist file, unload and reload the service:

```bash
launchctl unload ~/Library/LaunchAgents/com.openjarvis.plist
launchctl load ~/Library/LaunchAgents/com.openjarvis.plist
```

## System-Wide Installation

The instructions above install the service as a **user agent** (runs only when you are logged in). To run OpenJarvis as a system-wide daemon that starts at boot regardless of user login:

1. Copy the plist to `/Library/LaunchDaemons/` (requires `sudo`).
2. Set the file ownership to `root:wheel`.
3. Optionally add a `UserName` key to run as a specific user.

```bash
sudo cp deploy/launchd/com.openjarvis.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.openjarvis.plist
sudo launchctl load /Library/LaunchDaemons/com.openjarvis.plist
```

!!! note
    System daemons in `/Library/LaunchDaemons/` run as root by default. Add a `UserName` key to run as a less-privileged user:

    ```xml
    <key>UserName</key>
    <string>openjarvis</string>
    ```
