# WSL2 Install

OpenJarvis runs in WSL2 on Windows. Native Windows is not supported.

## One-time WSL setup

In an admin PowerShell:

```powershell
wsl --install
```

Then open the Ubuntu (or Debian) shell that gets installed.

## Install OpenJarvis

```bash
curl -fsSL https://openjarvis.ai/install.sh | bash
```

About 3 minutes. Type `jarvis` to start.

## WSL-specific notes

- The installer detects WSL via `/proc/sys/kernel/osrelease` and uses `nohup ollama serve &` instead of systemd to start the Ollama daemon (WSL2 doesn't ship systemd by default).
- The first time you run `jarvis`, the WSL kernel may show a "process running in background" notification — that's the bg-orchestrator detaching. It's expected.
- Models are stored in WSL's filesystem (`~/.openjarvis/`), not your Windows drive. To free up space later: `jarvis-uninstall` removes everything.

## See also

- [Full installer reference](install.md)
