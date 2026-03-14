# Agent UX, Auto-Update, and CLI Version Check Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix agent error visibility, add standing instructions + model selection to agents, wire up the scheduler, add desktop auto-update, and CLI version check.

**Architecture:** Three independent sub-projects. Sub-project 1 (agents) touches frontend + backend Python. Sub-project 2 (auto-update) is frontend-only (Tauri plugin already configured). Sub-project 3 (CLI version check) is Python-only.

**Tech Stack:** React 19, TypeScript, Zustand, sonner (toasts), Python (Click CLI, SQLite agent manager), Tauri updater plugin, GitHub releases API

**Spec:** `docs/superpowers/specs/2026-03-14-agents-updates-design.md`

---

## Chunk 1: CLI Version Check (Sub-project 3)

This is the simplest sub-project and fully independent. Start here.

### Task 1: Create _version_check.py

**Files:**
- Create: `src/openjarvis/cli/_version_check.py`

- [ ] **Step 1: Create the version check module**

```python
"""Check for newer OpenJarvis releases on GitHub."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("~/.openjarvis/version-check.json").expanduser()
_CACHE_TTL = 86400  # 24 hours
_GITHUB_API = "https://api.github.com/repos/open-jarvis/OpenJarvis/releases/latest"
_CHECK_COMMANDS = {"ask", "chat", "serve"}


def check_for_updates(command_name: str) -> None:
    """Print a message if a newer version is available. Best-effort, never raises."""
    if command_name not in _CHECK_COMMANDS:
        return
    try:
        _do_check()
    except Exception:
        pass  # Silent — never break CLI for a version check


def _do_check() -> None:
    import openjarvis

    current = openjarvis.__version__
    latest = _get_latest_version(current)
    if latest is None:
        return

    from packaging.version import Version, InvalidVersion

    try:
        if Version(latest) > Version(current):
            sys.stderr.write(
                f"\033[33mA new version of OpenJarvis is available "
                f"(v{current} \u2192 v{latest})\n"
                f"Update: cd ~/OpenJarvis && git pull && uv sync\033[0m\n\n"
            )
    except InvalidVersion:
        pass


def _get_latest_version(current: str) -> str | None:
    """Return latest version string from cache or GitHub API."""
    # Check cache
    try:
        if _CACHE_PATH.exists():
            data = json.loads(_CACHE_PATH.read_text())
            last_check = data.get("last_check", 0)
            if time.time() - last_check < _CACHE_TTL:
                return data.get("latest_version")
    except Exception:
        pass

    # Fetch from GitHub
    try:
        import urllib.request

        req = urllib.request.Request(
            _GITHUB_API,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            tag = data.get("tag_name", "")
            latest = tag.lstrip("v")
    except Exception:
        return None

    # Update cache
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps({
            "last_check": time.time(),
            "latest_version": latest,
            "current_version": current,
        }))
    except Exception:
        pass

    return latest
```

- [ ] **Step 2: Wire into CLI group callback**

In `src/openjarvis/cli/__init__.py`, update the `cli` function (line 39-46) to call the version check:

```python
@click.group(help="OpenJarvis — modular AI assistant backend")
@click.version_option(version=openjarvis.__version__, prog_name="jarvis")
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging")
@click.option("--quiet", is_flag=True, default=False, help="Suppress non-error output")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """Top-level CLI group."""
    from openjarvis.cli.log_config import setup_logging

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet
    setup_logging(verbose=verbose, quiet=quiet)

    # Check for updates on interactive commands
    if not quiet and ctx.invoked_subcommand:
        from openjarvis.cli._version_check import check_for_updates
        check_for_updates(ctx.invoked_subcommand)
```

- [ ] **Step 3: Verify lint passes**

Run: `uv run ruff check src/openjarvis/cli/_version_check.py src/openjarvis/cli/__init__.py`
Expected: All checks passed

- [ ] **Step 4: Commit**

```bash
git add src/openjarvis/cli/_version_check.py src/openjarvis/cli/__init__.py
git commit -m "feat: CLI version check against GitHub releases (daily, cached)"
```

---

## Chunk 2: Desktop Auto-Update (Sub-project 2)

### Task 2: Wire Tauri updater in App.tsx

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add auto-update check**

In `frontend/src/App.tsx`, add a new `useEffect` after the existing effects (around line 104, after the opt-in modal effect). The `isTauri` import is already present.

```typescript
  // Desktop auto-update check (runs once on launch)
  const updateChecked = useRef(false);
  useEffect(() => {
    if (!isTauri() || updateChecked.current) return;
    updateChecked.current = true;

    (async () => {
      try {
        const { check } = await import('@tauri-apps/plugin-updater');
        const update = await check();
        if (update) {
          await update.downloadAndInstall();
          // Update downloaded — user can restart when ready
          const { toast } = await import('sonner');
          toast.info('Update ready', {
            description: 'A new version has been downloaded. Restart to apply.',
            duration: Infinity,
            action: {
              label: 'Restart Now',
              onClick: async () => {
                const { relaunch } = await import('@tauri-apps/plugin-process');
                await relaunch();
              },
            },
          });
        }
      } catch {
        // Silent — no internet or endpoint issue
      }
    })();
  }, []);
```

Also add `useRef` to the React import at line 1 (if not already present):
```typescript
import { useEffect, useState, useCallback, useRef } from 'react';
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: desktop auto-update — download in background, toast to restart"
```

---

## Chunk 3: Agent UX — Backend (Sub-project 1, Part A)

### Task 3: Write error details to summary_memory on tick failure

**Files:**
- Modify: `src/openjarvis/agents/executor.py:270-280`

- [ ] **Step 1: Add error detail to summary_memory in _finalize_tick**

In `executor.py`, in the error handler (lines 270-280), after `self._manager.update_agent(agent_id, status="error")`, add:

```python
            # Write error detail to summary_memory so frontend can display it
            error_msg = str(error)[:2000]
            self._manager.update_summary_memory(agent_id, f"ERROR: {error_msg}")
```

The full block (lines 270-280) should become:

```python
        else:
            self._manager.end_tick(agent_id)
            self._manager.update_agent(agent_id, status="error")
            # Write error detail to summary_memory so frontend can display it
            error_msg = str(error)[:2000]
            self._manager.update_summary_memory(agent_id, f"ERROR: {error_msg}")
            self._bus.publish(EventType.AGENT_TICK_ERROR, {
                "agent_id": agent_id,
                "error": str(error),
                "error_type": (
                    "fatal" if isinstance(error, FatalError) else "retryable_exhausted"
                ),
                "duration": duration,
            })
```

- [ ] **Step 2: Inject standing instruction into agent context**

In `executor.py`, in `_invoke_agent` (lines 196-205), modify the context building to prepend the instruction:

Replace lines 196-201:
```python
        # Build input from summary_memory + pending messages
        context = agent.get("summary_memory", "") or "Continue your assigned task."
```

With:
```python
        # Build input from instruction + summary_memory + pending messages
        instruction = config.get("instruction", "")
        memory = agent.get("summary_memory", "")
        if instruction:
            context = f"Standing instruction: {instruction}"
            if memory:
                context += f"\n\nPrevious context: {memory}"
        else:
            context = memory or "Continue your assigned task."
```

- [ ] **Step 3: Run lint and tests**

Run: `uv run ruff check src/openjarvis/agents/executor.py`
Run: `uv run pytest tests/server/ -v --tb=short`
Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add src/openjarvis/agents/executor.py
git commit -m "fix: write error to summary_memory on tick failure, inject standing instruction"
```

---

### Task 4: Wire AgentScheduler into the server

**Files:**
- Modify: `src/openjarvis/cli/serve.py:239-260`
- Modify: `src/openjarvis/server/agent_manager_routes.py`

- [ ] **Step 1: Instantiate and start scheduler in serve.py**

In `serve.py`, after the agent_manager creation block (line 250, after `agent_manager = AgentManager(db_path=am_db)`), add scheduler creation:

```python
    # Set up agent scheduler for cron/interval agents
    agent_scheduler = None
    if agent_manager is not None:
        try:
            from openjarvis.agents.executor import AgentExecutor
            from openjarvis.agents.scheduler import AgentScheduler

            executor = AgentExecutor(manager=agent_manager, event_bus=bus)
            # Build system for executor
            from openjarvis.system import SystemBuilder
            system = SystemBuilder(config).build()
            executor.set_system(system)

            agent_scheduler = AgentScheduler(
                manager=agent_manager,
                executor=executor,
                event_bus=bus,
            )
            # Register existing scheduled agents
            for ag in agent_manager.list_agents():
                sched_type = ag.get("config", {}).get("schedule_type", "manual")
                if sched_type in ("cron", "interval") and ag["status"] not in ("archived", "error"):
                    agent_scheduler.register_agent(ag["id"])
            agent_scheduler.start()
            console.print("  Scheduler: [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Agent scheduler init failed: %s", exc)
```

Then pass `agent_scheduler` to `create_app` — add it as a keyword argument:

```python
    app = create_app(
        engine, model_name, agent=agent, bus=bus,
        engine_name=engine_name, agent_name=agent_key or "",
        channel_bridge=channel_bridge, config=config,
        speech_backend=speech_backend,
        agent_manager=agent_manager,
        agent_scheduler=agent_scheduler,
    )
```

- [ ] **Step 2: Accept scheduler in create_app and store on app state**

In `src/openjarvis/server/app.py`, update the `create_app` function signature to accept `agent_scheduler=None` and store it:

Add parameter: `agent_scheduler=None`

Add to app state (after `app.state.agent_manager = agent_manager`):
```python
    app.state.agent_scheduler = agent_scheduler
```

- [ ] **Step 3: Register new agents with scheduler in create endpoint**

In `src/openjarvis/server/agent_manager_routes.py`, in the create endpoint (around line 78), after the agent is created, register it with the scheduler:

```python
        # Register with scheduler if cron/interval
        scheduler = getattr(request.app.state, "agent_scheduler", None)
        config = body.get("config", {})
        if scheduler and config.get("schedule_type") in ("cron", "interval"):
            scheduler.register_agent(agent["id"])
```

- [ ] **Step 4: Run lint and tests**

Run: `uv run ruff check src/openjarvis/cli/serve.py src/openjarvis/server/app.py src/openjarvis/server/agent_manager_routes.py`
Run: `uv run pytest tests/server/ -v --tb=short`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/cli/serve.py src/openjarvis/server/app.py src/openjarvis/server/agent_manager_routes.py
git commit -m "feat: wire AgentScheduler into server, register agents on create"
```

---

## Chunk 4: Agent UX — Frontend (Sub-project 1, Part B)

### Task 5: Add instruction + model fields to agent wizard

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx`

- [ ] **Step 1: Add fields to WizardState interface**

Find the `WizardState` interface (around line 133) and add:

```typescript
interface WizardState {
  step: number;
  templateId: string;
  name: string;
  instruction: string;      // NEW
  model: string;            // NEW
  scheduleType: string;
  scheduleValue: string;
  selectedTools: string[];
  budget: string;
  learningEnabled: boolean;
}
```

Update the `useState<WizardState>` initial value (around line 154) to include:

```typescript
    instruction: '',
    model: '',
```

- [ ] **Step 2: Add instruction textarea and model dropdown to wizard Step 2**

Find the Step 2 configuration section in the JSX (search for "Schedule Type" or `scheduleType`). Add the instruction textarea and model dropdown BEFORE the schedule type selector:

```tsx
              {/* Instruction */}
              <div>
                <div className="text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                  What should this agent do?
                  {(wizard.scheduleType === 'cron' || wizard.scheduleType === 'interval') && (
                    <span style={{ color: 'var(--color-error)' }}> *</span>
                  )}
                </div>
                <textarea
                  value={wizard.instruction}
                  onChange={(e) => update({ instruction: e.target.value })}
                  placeholder="e.g. Monitor my inbox and summarize new emails every hour"
                  rows={3}
                  className="w-full text-sm px-3 py-2 rounded-lg outline-none resize-none"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    color: 'var(--color-text)',
                    border: '1px solid var(--color-border)',
                  }}
                />
                <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                  This instruction runs every tick. Tasks are optional one-off goals.
                </div>
              </div>

              {/* Model */}
              <div>
                <div className="text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>Model</div>
                <select
                  value={wizard.model}
                  onChange={(e) => update({ model: e.target.value })}
                  className="w-full text-sm px-3 py-2 rounded-lg outline-none cursor-pointer"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    color: 'var(--color-text)',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  <option value="">Server default</option>
                  {useAppStore.getState().models.map((m) => (
                    <option key={m.id} value={m.id}>{m.id}</option>
                  ))}
                </select>
              </div>
```

- [ ] **Step 3: Pass instruction and model to config in handleLaunch**

Update the `handleLaunch` function (around line 192) to include instruction and model:

```typescript
      const config: Record<string, unknown> = {
        schedule_type: wizard.scheduleType,
        schedule_value: wizard.scheduleValue || undefined,
        tools: wizard.selectedTools,
        learning_enabled: wizard.learningEnabled,
      };
      if (wizard.budget) config.budget = parseFloat(wizard.budget);
      if (wizard.instruction.trim()) config.instruction = wizard.instruction.trim();
      if (wizard.model) config.model = wizard.model;
```

Also add validation before the existing name check:

```typescript
    if ((wizard.scheduleType === 'cron' || wizard.scheduleType === 'interval') && !wizard.instruction.trim()) {
      toast.error('Instruction is required for scheduled agents');
      return;
    }
```

- [ ] **Step 4: Auto-run interval agents after creation**

In `handleLaunch`, after `toast.success(...)` and before `onLaunched()`, add:

```typescript
      // Auto-run first tick for interval agents
      if (wizard.scheduleType === 'interval' && created.id) {
        runManagedAgent(created.id).catch(() => {});
      }
```

Note: capture the return value from `createManagedAgent`:

```typescript
      const created = await createManagedAgent({
        name: wizard.name,
        template_id: wizard.templateId || undefined,
        config,
      });
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx
git commit -m "feat: instruction + model fields in agent wizard, auto-run interval agents"
```

---

### Task 6: Add error toasts and polling to AgentsPage

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx`

- [ ] **Step 1: Add error polling and post-run error check**

In the main `AgentsPage` component, find the `handleRun` function. Update it to check for errors after running:

```typescript
  const handleRun = async (id: string) => {
    await runManagedAgent(id).catch(() => {});
    // Wait 3 seconds then check if the agent errored
    setTimeout(async () => {
      try {
        const agent = await fetchManagedAgent(id);
        if (agent.status === 'error') {
          toast.error(`Agent "${agent.name}" failed`, {
            description: agent.summary_memory?.replace(/^ERROR: /, '') || 'Unknown error',
          });
          useAppStore.getState().addLogEntry({
            timestamp: Date.now(), level: 'error', category: 'model',
            message: `Agent "${agent.name}" failed: ${agent.summary_memory || 'Unknown error'}`,
          });
        }
      } catch {}
      await refresh();
    }, 3000);
    await refresh();
  };
```

- [ ] **Step 2: Add 30-second polling for error detection**

In the main `AgentsPage` component, add a `useEffect` that polls for agent errors:

```typescript
  // Poll for agent errors every 30 seconds
  const prevStatuses = useRef<Record<string, string>>({});
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const agents = await fetchManagedAgents();
        for (const agent of agents) {
          const prev = prevStatuses.current[agent.id];
          if (prev && prev !== 'error' && agent.status === 'error') {
            toast.error(`Agent "${agent.name}" failed`, {
              description: agent.summary_memory?.replace(/^ERROR: /, '') || 'Unknown error',
            });
          }
          prevStatuses.current[agent.id] = agent.status;
        }
      } catch {}
    }, 30000);
    return () => clearInterval(interval);
  }, []);
```

Make sure `useRef` is imported from React.

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx
git commit -m "feat: error toasts for agent failures, 30s polling for error detection"
```

---

## Chunk 5: Final Verification

### Task 7: Build and test everything

- [ ] **Step 1: TypeScript check**
Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 2: Frontend build**
Run: `cd frontend && npm run build`

- [ ] **Step 3: Python lint**
Run: `uv run ruff check src/ tests/`

- [ ] **Step 4: Python tests**
Run: `uv run pytest tests/server/ -v --tb=short`

- [ ] **Step 5: Cargo check**
Run: `cd desktop/src-tauri && cargo check`

- [ ] **Step 6: Push**
```bash
git push origin main
```
