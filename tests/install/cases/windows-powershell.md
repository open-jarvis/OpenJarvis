# Case: PowerShell user runs the bash one-liner

**Reported:** #334 — *"The term 'bash' is not recognized as the name of a cmdlet…"*

## Symptom

A Windows user pastes the documented install command into **PowerShell** (or
`cmd`):

```powershell
curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash
```

and gets:

```
bash : The term 'bash' is not recognized as the name of a cmdlet, function,
script file, or operable program.
```

## Why

`install.sh` is a bash script. PowerShell/cmd have no `bash`, so the pipe
fails before any installer code runs. The script's own native-Windows refusal
(`uname -s` = `MINGW*/MSYS*/CYGWIN*`) cannot help here — that branch requires
bash to already exist.

## Expected behavior

There is a PowerShell entry point published alongside `install.sh`:

```powershell
irm https://open-jarvis.github.io/OpenJarvis/install.ps1 | iex
```

`install.ps1` is **guidance-only** (native Windows CLI is unsupported): it
prints the two supported paths — WSL2 (`wsl --install -d Ubuntu-24.04`, then
re-run the bash one-liner inside Ubuntu) and the desktop app — links the WSL2
walkthrough, and exits non-zero. It never attempts a native install.

## Regression guard

- `scripts/install/install.ps1` exists and exits non-zero with the WSL2 /
  desktop guidance.
- `docs/gen_install_script.py` publishes it to the site (`install.ps1`).
- `install.sh` still refuses on MINGW/MSYS/CYGWIN (bash-on-Windows) shells.
