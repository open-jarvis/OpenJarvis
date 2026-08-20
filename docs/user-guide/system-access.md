# System Access

How to give an agent access to the machine it runs on, and where the real
limits are.

!!! warning
    `shell_exec` runs arbitrary commands as your user. There is no command
    allowlist, no denylist, and no sandbox unless you turn one on. An agent
    holding this tool can do anything you can do from a terminal.

---

## Start here: you probably have no tools enabled

If the agent tells you it can't run commands or read files, that's usually not
a permissions problem. It means no tools were enabled in the first place.

Tools come from `tools.enabled`, falling back to `agent.tools`. Both default to
empty, and an empty value builds the agent with **zero tools**. Nothing is
enabled by default.

First check whether you have a config file at all:

```bash
cat ~/.openjarvis/config.toml
```

If it isn't there, that's your answer. Create it:

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "qwen3.5:9b"

[agent]
default_agent = "orchestrator"

[tools]
enabled = ["shell_exec", "file_read", "file_write", "think"]
```

There's a fuller version at
`configs/openjarvis/examples/full-system-access.toml`.

Then confirm the list actually resolved:

```bash
python -c "from openjarvis.core.config import load_config; print(load_config().tools.enabled)"
```

---

## What the tools reach

| Tool | Scope |
|------|-------|
| `shell_exec` | Any command, as your user. 30s default timeout, 300s max, output capped at 100 KB per stream. |
| `file_read` | Any readable path. 1 MB cap. |
| `file_write` | Any writable path. 10 MB cap, can create parent directories. |
| `apply_patch` | Applies unified diffs to any path. |
| `code_interpreter` | Python in a subprocess, behind a coarse pattern blocklist. |

`file_read` and `file_write` take an `allowed_dirs` argument that limits them to
a set of directories, but no config key populates it. When it's empty every path
is allowed. If you want a filesystem jail today, use the container sandbox
instead of relying on these tools to enforce one.

### Sensitive filenames

`file_read` and `file_write` refuse names matching a short glob list: `.env`,
`*.pem`, `id_rsa`, `credentials.*` and a dozen or so others. It matches on the
filename only, not the path or the contents, and only those two tools consult
it. `shell_exec`, `apply_patch` and `code_interpreter` skip it entirely, so
`cat ~/.ssh/id_rsa` through `shell_exec` works fine. Treat it as protection
against fat fingers, not as a security boundary.

---

## Confirmation behaviour

`shell_exec`, `git_commit` and `agent_kill` are marked `requires_confirmation`.
What that translates to depends entirely on how you launched the agent:

| Entry point | Behaviour |
|-------------|-----------|
| `jarvis chat` | Prompts before each call. |
| `jarvis ask` | Auto-approves. |
| `jarvis agent ask` | Auto-approves. Pass `--no-yes` if you want prompts. |
| HTTP server, desktop app | Auto-approves. Tools you added to an agent's toolkit count as pre-approved. |
| Embedded via `SystemBuilder` | No callback is wired, so these tools fail closed. |

That last row catches people out. If `shell_exec` returns "requires
confirmation but no confirmation callback is available", you're constructing the
agent yourself and need to pass a `confirm_callback`.

!!! note "`enforce_tool_confirmation` doesn't do anything"
    The config loader accepts `security.enforce_tool_confirmation`, but nothing
    on the tool execution path reads it. Setting it won't change confirmation
    behaviour anywhere. Use the table above instead.

---

## macOS: Full Disk Access

On macOS the operating system is the real boundary, not the config. Shell
access and ordinary file access start working as soon as you enable the tools.
TCC-protected data does not: Messages, Mail, Photos, Safari history, Contacts
and Calendar all stay locked, and no config key will change that.

Grant Full Disk Access to whichever process hosts the backend. Child processes
inherit it:

| How you run OpenJarvis | Grant access to |
|------------------------|-----------------|
| CLI (`jarvis ask`, `jarvis chat`) | Your terminal (Terminal, iTerm, Warp) |
| Desktop app | `OpenJarvis.app`, which spawns `jarvis serve` beneath it |
| launchd (`deploy/launchd/com.openjarvis.plist`) | The `jarvis` binary, as its own entry |

System Settings, then Privacy & Security, then Full Disk Access, then **+**.

A launchd daemon gets its own TCC context, so granting access to Terminal does
nothing for it. Add `/usr/local/bin/jarvis` separately.

To check whether the grant took:

```bash
head -c 16 ~/Library/Messages/chat.db >/dev/null 2>&1 \
  && echo "granted" || echo "denied"
```

Restart the host process after you change the setting.

### Driving Mac apps

AppleScript works through `shell_exec`:

```
osascript -e 'tell application "Music" to play'
```

macOS asks for Automation permission once per target app, the first time you
touch it.

---

## What you can't do

There's no computer use. OpenJarvis can't see your screen, move the pointer or
send keystrokes. No tool for it is registered and no input automation library
appears anywhere in the codebase, so granting Accessibility or Screen Recording
buys you nothing on its own.

The `click` and `type` actions you'll find are Playwright, scoped to a browser
page rather than the desktop.

Some of this is reachable through `shell_exec` if you bring the tooling
yourself. `screencapture` will take screenshots once you've granted Screen
Recording, and something like `cliclick` will move the pointer. That gets you
scripted actions. It doesn't get you an agent that looks at the screen and
works out where to click.

---

## Narrowing access

Access widens and narrows through `tools.enabled`. Drop entries to take
capabilities away. That list is the whole grant.

Two stronger isolation options exist. Both are off by default:

```toml
[sandbox]
enabled = true          # run tools inside a container
runtime = "docker"

[security.capabilities]
enabled = true          # RBAC over declared tool capabilities
policy_path = "~/.openjarvis/policy.yaml"
```

!!! note "Capabilities are open by default even once enabled"
    `CapabilityPolicy` is built with `default_deny=False` and no config key
    exposes that flag, so an agent with no explicit policy entry gets every
    capability. Write entries for every agent you mean to restrict.

For anything untrusted, reach for `docker_shell_exec` and
`code_interpreter_docker` rather than the host-side versions.

---

## See also

- [Security](security.md) for scanners, the audit log and guardrails
- [Tools](tools.md) for the full registry
- [Code Assistant](code-assistant.md) for a narrower shell-enabled setup
- [External MCP Servers](mcp-external-servers.md) for capabilities OpenJarvis doesn't ship
