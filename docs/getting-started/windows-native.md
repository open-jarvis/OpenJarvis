# Native Windows (advanced)

Phase-1 of the native-Windows-support RFC (#298). Mirrors the Linux
(systemd) and macOS (launchd) deployments — but for PowerShell, without
WSL2 or Docker. Choose this over [WSL2](wsl2.md) only if you want to
avoid a Linux VM; WSL2 remains the smoother experience for most users.

## What you get

- A PowerShell installer that probes prerequisites, installs `uv`,
  clones the repo, and runs `uv sync --extra desktop`.
- An optional Windows scheduled-task service equivalent to the systemd
  unit and launchd plist.
- Loopback default — the service binds `127.0.0.1` so no API key is
  required.

## What you need

- Windows 10 1809+ or Windows 11.
- Python 3.10 – 3.13 (Python 3.14 has no numpy Windows wheels yet —
  see [#432](https://github.com/open-jarvis/OpenJarvis/issues/432)).
- `git` on PATH.
- ~5 GB free disk on `%LOCALAPPDATA%`.

## Install

In any PowerShell:

```powershell
irm https://open-jarvis.github.io/OpenJarvis/install.ps1 | iex
```

The installer will:

1. Refuse non-Windows hosts and old Windows builds.
2. Confirm Python 3.10 – 3.13.
3. Confirm `git`.
4. Install `uv` if absent (via the official `astral.sh/uv` PowerShell
   installer).
5. Clone the repo to `%LOCALAPPDATA%\OpenJarvis\src`.
6. Run `uv sync --extra desktop`.
7. Prompt to register the scheduled-task service (skip with
   `-SkipService`).

## Run it

```powershell
cd "$env:LOCALAPPDATA\OpenJarvis\src"
uv run jarvis serve
```

Open `http://127.0.0.1:8000/health` to verify.

## Scheduled-task service

If you skipped the prompt during install, register the auto-start task
manually:

```powershell
$srv = "$env:LOCALAPPDATA\OpenJarvis\src\deploy\windows\jarvis-service.ps1"
powershell -ExecutionPolicy Bypass -File $srv install
```

State:

```powershell
powershell -ExecutionPolicy Bypass -File $srv status
```

Remove:

```powershell
powershell -ExecutionPolicy Bypass -File $srv uninstall
```

See [`deploy/windows/README.md`](https://github.com/open-jarvis/OpenJarvis/blob/main/deploy/windows/README.md)
for the LAN-exposed configuration and the parity table against
systemd / launchd.

## See also

- [WSL2 install](wsl2.md) — the recommended Windows path.
- [Full installer reference](install.md).
