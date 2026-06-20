# OpenJarvis on native Windows

Phase-1 of the native-Windows-support RFC (#298). Mirrors the Linux
(`deploy/systemd/`) and macOS (`deploy/launchd/`) deployments — but for
PowerShell, without WSL2 or Docker.

## One-liner install

In an elevated-or-regular PowerShell:

```powershell
irm https://open-jarvis.github.io/OpenJarvis/install.ps1 | iex
```

What it does:

1. Refuses non-Windows hosts and Windows < 10 1809.
2. Checks Python 3.10 – 3.13 (3.14 has no numpy wheels yet — see #432).
3. Checks `git` on PATH.
4. Installs `uv` (https://astral.sh/uv) if absent.
5. Clones the OpenJarvis repository to `%LOCALAPPDATA%\OpenJarvis`
   (override with `$env:OPENJARVIS_HOME`).
6. Runs `uv sync --extra desktop` so the FastAPI server and speech backend are
   importable.
7. Optionally prompts to register a scheduled task that auto-starts the
   server at logon.

Flags (when invoked directly rather than via `irm | iex`):

| Flag | Effect |
|------|--------|
| `-Service` | Register the scheduled task without prompting |
| `-SkipService` | Don't prompt; don't register |
| `-Force` | Re-run all steps even if already done |

`irm | iex` can't pass `param()` args into a piped script string, so
the same knobs are honored via env vars when the corresponding flag is
absent:

```powershell
$env:OPENJARVIS_SKIP_SERVICE = '1'
irm https://open-jarvis.github.io/OpenJarvis/install.ps1 | iex
```

The available env vars: `OPENJARVIS_SKIP_SERVICE`, `OPENJARVIS_SERVICE`,
`OPENJARVIS_FORCE`. If you need richer control, save the script first
(`irm ... -OutFile install.ps1; .\install.ps1 -Force`).

## Manual scheduled-task setup

If you skipped the prompt during install, you can register / inspect /
remove the task with `jarvis-service.ps1`:

```powershell
$srv = "$env:LOCALAPPDATA\OpenJarvis\src\deploy\windows\jarvis-service.ps1"

# install (idempotent — replaces existing)
powershell -ExecutionPolicy Bypass -File $srv install

# status
powershell -ExecutionPolicy Bypass -File $srv status

# remove
powershell -ExecutionPolicy Bypass -File $srv uninstall
```

The task runs as the current user with `LogonType=Interactive` and
`RunLevel=Limited`. It restarts up to 3 times on failure (1-minute
gap), has no execution-time limit, and starts when available (catches
up if missed).

## Loopback vs LAN-exposed

By default the scheduled task binds `127.0.0.1` — reachable only from
this machine, no API key required. This matches launchd parity (see
`deploy/launchd/com.openjarvis.plist`).

To expose on your LAN:

```powershell
# 1. Generate an API key. The server REFUSES to bind 0.0.0.0 without one.
$env:OPENJARVIS_API_KEY = (uv run jarvis auth generate-key)

# 2. Re-register the task with -ListenHost 0.0.0.0.
powershell -ExecutionPolicy Bypass -File $srv install -ListenHost 0.0.0.0
```

`jarvis-service.ps1 install` refuses `-ListenHost 0.0.0.0` if
`$env:OPENJARVIS_API_KEY` is unset — same guard as the systemd unit's
`EnvironmentFile=/etc/openjarvis/env`.

## Parity table

| Concern | systemd | launchd | Windows |
|---------|---------|---------|---------|
| Service definition | `deploy/systemd/openjarvis.service` | `deploy/launchd/com.openjarvis.plist` | `deploy/windows/jarvis-service.ps1` (cmdlet-driven) |
| Default bind | `0.0.0.0` (with API key) | `127.0.0.1` (no API key) | `127.0.0.1` (no API key) |
| Restart on failure | `Restart=on-failure RestartSec=5` | `KeepAlive=true` | `RestartCount=3 RestartInterval=PT1M` |
| Auto-start | `multi-user.target` | `RunAtLoad=true` | `AtLogOn` trigger |

## Updating

To pull the latest:

```powershell
cd "$env:LOCALAPPDATA\OpenJarvis\src"
git pull --ff-only
uv sync --extra desktop
```

Or re-run the installer with `-Force`:

```powershell
irm https://open-jarvis.github.io/OpenJarvis/install.ps1 | iex
# (then re-run with the file directly, passing -Force)
```

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\OpenJarvis\src\deploy\windows\jarvis-service.ps1" uninstall
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\OpenJarvis"
```

Uninstalling does NOT remove `uv` (it's a separate tool — you may have
other Python projects using it).
