# Native Windows (advanced)

Phase-1 of the native-Windows-support RFC (#298). Mirrors the Linux
(systemd) and macOS (launchd) deployments — but for PowerShell, without
WSL2 or Docker. Choose this over [WSL2](wsl2.md) only if you want to
avoid a Linux VM; WSL2 remains the smoother experience for most users.

## Windows ARM64 desktop

The existing Tauri/React desktop app can be built for Windows 11 on ARM.
The desktop release workflow produces an `arm64-setup.exe` NSIS installer and
adds `windows-aarch64` to the updater manifest alongside the x64 build. Use
the ARM64 installer when it appears in a new desktop release; older releases
only include x64 installers.

This uses the same UI, backend, and Ollama integration as the other desktop
builds. The desktop executable and bundled Ollama are ARM64. The current
Python dependency stack has no Windows ARM64 wheels for several packages,
including the locked NumPy, PyArrow, and speech dependencies. The app
therefore selects uv-managed **x64 CPython 3.12** and builds the Rust Python
extension for x64; Windows runs that backend through x64 emulation. This
preserves the existing features without a separate UI or dependency stack.

First-launch prerequisites are the same as the x64 desktop: Git, uv, Rust,
and Visual Studio Build Tools with the **x64 C++ workload**. With an ARM64
Rust installation, install the x64 target for stable Rust:

```powershell
rustup target add --toolchain stable x86_64-pc-windows-msvc
```

The ARM64 app uses stable Rust for backend builds so the compiler matches the
installed x64 target, rather than selecting a separate minimum-version toolchain.
It also supplies PyO3's cross-compilation settings for x64 CPython 3.12.
The Python extension still targets x64. The ARM64 desktop build itself requires the
ARM64 C++ build tools and Clang (the Visual Studio **C++ Clang tools for Windows**
component, with `clang.exe` on PATH). Setup still requires the user's
inference-source choice before starting local inference or downloading a model.

### Testing without a Windows ARM laptop

The desktop workflow's `test-windows-arm64` PR job runs on GitHub's
`windows-11-arm` runner. It checks backend imports and CLI startup under x64
emulation, builds an unsigned NSIS installer, checks that the desktop and
Ollama executable headers identify ARM64, and uploads the
`windows-arm64-test-installer` artifact. Passing this job verifies the build
and dependency path; it does not verify interactive chat or hardware acceleration.

For an interactive test, use Windows 11 ARM in UTM, Parallels, or VMware Fusion
on an Apple silicon Mac. Download the installer artifact from the PR's Actions
run, then check:

1. Settings → System → About identifies an ARM-based processor.
2. The installer completes and OpenJarvis launches.
3. Local setup completes with a small model; chat streams and Stop cancels.
4. Settings, conversation history, and relaunch work as on the x64 app.
5. In Task Manager's Details tab, enable the Architecture column: the desktop
   and Ollama are ARM64, while Python is x64.

A VM is useful for compatibility testing; it does not validate GPU/NPU
performance on physical Windows ARM hardware.

## What you get

- A PowerShell installer that probes prerequisites, installs `uv`,
  clones the repo, and runs `uv sync --extra desktop --group desktop-native`.
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
6. Run `uv sync --extra desktop --group desktop-native`.
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
