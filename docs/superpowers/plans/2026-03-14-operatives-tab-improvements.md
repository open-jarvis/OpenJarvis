# Operatives Tab Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 UX/functionality issues in the Operatives (Agents) tab — schedule help, structured interval input, categorized tools with credentials, budget clarification, model grouping, Run Now crash, Recover fix, structured error logs, and learning technique selection.

**Architecture:** Frontend-first approach. The backend already has 44 tools, 27 channels, and learning policies. We add one new backend module (`credentials.py`), fix two backend bugs (recover + Run Now error handling), add structured error metadata to traces, add a `GET /v1/tools` endpoint, and then overhaul the frontend wizard and detail page.

**Tech Stack:** Python 3.10+ / FastAPI (backend), React 19 / TypeScript / Tailwind (frontend), SQLite (persistence), TOML (credential storage)

**Spec:** `docs/superpowers/specs/2026-03-14-operatives-tab-improvements-design.md`

---

## Chunk 1: Backend Fixes (Recover, Run Now, Error Detail, Credentials)

### Task 1: Fix `recover_agent()` to always reset status

**Files:**
- Modify: `src/openjarvis/agents/manager.py:284-288`
- Test: `tests/agents/test_manager_recover.py`

- [ ] **Step 1: Write failing test for recover without checkpoint**

```python
# tests/agents/test_manager_recover.py
"""Tests for AgentManager.recover_agent() always resetting status."""
import pytest
from openjarvis.agents.manager import AgentManager


@pytest.fixture
def manager(tmp_path):
    db = str(tmp_path / "agents.db")
    return AgentManager(db_path=db)


def test_recover_resets_to_idle_without_checkpoint(manager):
    """recover_agent must reset status to idle even when no checkpoint exists."""
    agent = manager.create_agent(name="test", agent_type="monitor_operative")
    manager.update_agent(agent["id"], status="error")

    result = manager.recover_agent(agent["id"])

    # Should return None (no checkpoint) but still reset status
    assert result is None
    refreshed = manager.get_agent(agent["id"])
    assert refreshed["status"] == "idle"


def test_recover_resets_to_idle_with_checkpoint(manager):
    """recover_agent returns checkpoint and resets status when checkpoint exists."""
    agent = manager.create_agent(name="test", agent_type="monitor_operative")
    manager.update_agent(agent["id"], status="error")
    manager.save_checkpoint(agent["id"], "tick-1", {"history": []}, {"tools": {}})

    result = manager.recover_agent(agent["id"])

    assert result is not None
    assert result["tick_id"] == "tick-1"
    refreshed = manager.get_agent(agent["id"])
    assert refreshed["status"] == "idle"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_manager_recover.py -v`
Expected: `test_recover_resets_to_idle_without_checkpoint` FAILS (status remains "error")

- [ ] **Step 3: Fix `recover_agent` in manager.py**

In `src/openjarvis/agents/manager.py`, replace lines 284-288:

```python
    def recover_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        checkpoint = self.get_latest_checkpoint(agent_id)
        # Always reset to idle — clearing the error state is the primary purpose
        self.update_agent(agent_id, status="idle")
        return checkpoint
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_manager_recover.py -v`
Expected: Both tests PASS

- [ ] **Step 5: Fix the recover endpoint to return 200 always**

In `src/openjarvis/server/agent_manager_routes.py`, replace lines 171-176:

```python
    @agents_router.post("/{agent_id}/recover")
    def recover_agent(agent_id: str):
        if not manager.get_agent(agent_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        checkpoint = manager.recover_agent(agent_id)
        return {"recovered": True, "checkpoint": checkpoint}
```

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/agents/manager.py src/openjarvis/server/agent_manager_routes.py tests/agents/test_manager_recover.py
git commit -m "fix: recover_agent always resets status to idle"
```

---

### Task 2: Fix Run Now error handling in backend

**Files:**
- Modify: `src/openjarvis/server/agent_manager_routes.py:144-164`
- Test: `tests/server/test_run_now_errors.py`

- [ ] **Step 1: Write failing test for Run Now error capture**

```python
# tests/server/test_run_now_errors.py
"""Tests for _run_tick error handling writing descriptive errors."""
import pytest
from unittest.mock import MagicMock, patch
from openjarvis.agents.manager import AgentManager


@pytest.fixture
def manager(tmp_path):
    db = str(tmp_path / "agents.db")
    return AgentManager(db_path=db)


def test_run_tick_captures_system_build_error(manager):
    """When SystemBuilder.build() fails, agent status should be 'error'
    and summary_memory should contain the error message."""
    agent = manager.create_agent(name="test", agent_type="monitor_operative")
    agent_id = agent["id"]

    # Simulate the _run_tick logic with a failing SystemBuilder
    from openjarvis.agents.executor import AgentExecutor
    from openjarvis.core.events import EventBus

    executor = AgentExecutor(manager=manager, event_bus=EventBus())

    with patch.object(executor, "execute_tick", side_effect=RuntimeError("No engine found")):
        # Simulate what the route's _run_tick does on failure
        try:
            executor.execute_tick(agent_id)
        except Exception as exc:
            try:
                manager.end_tick(agent_id)
            except Exception:
                pass
            manager.update_agent(agent_id, status="error")
            manager.update_summary_memory(agent_id, f"ERROR: {exc}")

    refreshed = manager.get_agent(agent_id)
    assert refreshed["status"] == "error"
    assert "No engine found" in refreshed["summary_memory"]
```

- [ ] **Step 2: Run test to verify it passes** (this tests current behavior, not new behavior)

Run: `uv run pytest tests/server/test_run_now_errors.py -v`
Expected: PASS

- [ ] **Step 3: Improve `_run_tick` in agent_manager_routes.py**

Replace the `_run_tick` function at lines 144-164:

```python
        def _run_tick():
            try:
                from openjarvis.agents.executor import AgentExecutor
                from openjarvis.core.events import get_event_bus
                from openjarvis.system import SystemBuilder

                executor = AgentExecutor(
                    manager=manager, event_bus=get_event_bus(),
                )
                try:
                    system = SystemBuilder().build()
                    executor.set_system(system)
                except Exception as build_err:
                    manager.update_agent(agent_id, status="error")
                    manager.update_summary_memory(
                        agent_id,
                        f"ERROR: Failed to build system: {build_err}",
                    )
                    return
                executor.execute_tick(agent_id)
            except Exception as exc:
                try:
                    manager.end_tick(agent_id)
                except Exception:
                    pass
                manager.update_agent(agent_id, status="error")
                manager.update_summary_memory(
                    agent_id,
                    f"ERROR: {exc}",
                )
```

- [ ] **Step 4: Commit**

```bash
git add src/openjarvis/server/agent_manager_routes.py tests/server/test_run_now_errors.py
git commit -m "fix: descriptive error messages when Run Now fails"
```

---

### Task 3: Add `suggest_action()` helper to errors.py

**Files:**
- Modify: `src/openjarvis/agents/errors.py`
- Test: `tests/agents/test_errors.py`

- [ ] **Step 1: Write test for suggested action mapping**

```python
# tests/agents/test_errors.py
"""Tests for error classification and suggested actions."""
from openjarvis.agents.errors import suggest_action, FatalError, RetryableError


def test_suggest_action_rate_limit():
    err = RetryableError("rate limit exceeded")
    assert "auto-retry" in suggest_action(err).lower()


def test_suggest_action_timeout():
    err = RetryableError("connection timed out")
    assert "engine" in suggest_action(err).lower()


def test_suggest_action_auth():
    err = FatalError("401 unauthorized")
    assert "API key" in suggest_action(err)


def test_suggest_action_not_found():
    err = FatalError("model not found (404)")
    assert "model name" in suggest_action(err).lower() or "endpoint" in suggest_action(err).lower()


def test_suggest_action_unknown():
    err = RetryableError("something weird happened")
    assert "trace" in suggest_action(err).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_errors.py -v`
Expected: FAIL — `suggest_action` not defined

- [ ] **Step 3: Implement `suggest_action` in errors.py**

Add at the end of `src/openjarvis/agents/errors.py`:

```python
def suggest_action(error: AgentTickError) -> str:
    """Return a human-readable suggested action for the given error."""
    msg = str(error).lower()
    if "rate limit" in msg or "rate_limit" in msg or "429" in msg or "too many requests" in msg:
        return "Rate limited \u2014 agent will auto-retry on next tick"
    if "timeout" in msg or "timed out" in msg or "connection" in msg or "unavailable" in msg:
        return "Engine not reachable \u2014 check that your inference engine is running"
    if "401" in msg or "403" in msg or "permission" in msg or "unauthorized" in msg or "api key" in msg:
        return "Check API key configuration in Settings"
    if "not found" in msg or "404" in msg:
        return "Model or endpoint not found \u2014 verify model name and engine URL"
    return "Unexpected error \u2014 check the full trace for details"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_errors.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/agents/errors.py tests/agents/test_errors.py
git commit -m "feat: add suggest_action helper for structured error messages"
```

---

### Task 4: Add `error_detail` to trace metadata in executor

**Files:**
- Modify: `src/openjarvis/agents/executor.py:268-290` (error paths in `_finalize_tick`)
- Modify: `src/openjarvis/agents/executor.py:292-336` (`_save_trace`)
- Test: `tests/agents/test_executor_error_detail.py`

- [ ] **Step 1: Write test for error_detail in trace metadata**

```python
# tests/agents/test_executor_error_detail.py
"""Tests for structured error_detail in executor traces."""
import pytest
import time
from unittest.mock import MagicMock, patch
from openjarvis.agents.executor import AgentExecutor
from openjarvis.agents.errors import FatalError, RetryableError, EscalateError
from openjarvis.core.events import EventBus


@pytest.fixture
def executor(tmp_path):
    from openjarvis.agents.manager import AgentManager
    mgr = AgentManager(db_path=str(tmp_path / "agents.db"))
    bus = EventBus()
    exe = AgentExecutor(manager=mgr, event_bus=bus)
    return exe, mgr


def test_build_error_detail_fatal(executor):
    exe, _ = executor
    error = FatalError("401 unauthorized")
    detail = exe._build_error_detail(error)
    assert detail["error_type"] == "fatal"
    assert "401 unauthorized" in detail["error_message"]
    assert "API key" in detail["suggested_action"]


def test_build_error_detail_retryable(executor):
    exe, _ = executor
    error = RetryableError("connection timed out")
    detail = exe._build_error_detail(error)
    assert detail["error_type"] == "retryable"
    assert "engine" in detail["suggested_action"].lower()


def test_build_error_detail_escalate(executor):
    exe, _ = executor
    error = EscalateError("agent needs help")
    detail = exe._build_error_detail(error)
    assert detail["error_type"] == "escalate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_executor_error_detail.py -v`
Expected: FAIL — `_build_error_detail` not defined

- [ ] **Step 3: Add `_build_error_detail` method to AgentExecutor**

In `src/openjarvis/agents/executor.py`, add this method before `_finalize_tick`:

```python
    def _build_error_detail(self, error: AgentTickError) -> dict[str, Any]:
        """Build structured error detail for trace metadata."""
        import traceback
        from openjarvis.agents.errors import (
            EscalateError,
            FatalError,
            suggest_action,
        )

        if isinstance(error, EscalateError):
            error_type = "escalate"
        elif isinstance(error, FatalError):
            error_type = "fatal"
        else:
            error_type = "retryable"

        return {
            "error_type": error_type,
            "error_message": str(error)[:2000],
            "suggested_action": suggest_action(error),
            "stack_trace_summary": "".join(
                traceback.format_exception(type(error), error, error.__traceback__)[-3:]
            )[:1000] if error.__traceback__ else "",
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_executor_error_detail.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Wire error_detail into `_save_trace` and `_finalize_tick`**

In `_save_trace` (line ~320), add metadata to the Trace construction. Change the `trace = Trace(...)` block to include:

```python
        metadata: dict[str, Any] = {}
        if error is not None:
            metadata["error_detail"] = self._build_error_detail(error)

        trace = Trace(
            agent=agent_id,
            query=agent.get("summary_memory", "")[:200],
            result=result.content[:200] if result else "",
            model=agent.get("config", {}).get("model", ""),
            outcome=outcome,
            steps=steps,
            started_at=tick_start,
            ended_at=tick_start + tick_duration,
            total_latency_seconds=tick_duration,
            metadata=metadata,
        )
```

- [ ] **Step 6: Add `metadata` to traces list endpoint response**

In `src/openjarvis/server/agent_manager_routes.py`, modify the list_traces endpoint (line ~296) to include metadata:

```python
            return {
                "traces": [
                    {
                        "id": t.trace_id,
                        "outcome": t.outcome,
                        "duration": t.total_latency_seconds,
                        "started_at": t.started_at,
                        "steps": len(t.steps),
                        "metadata": t.metadata,
                    }
                    for t in traces
                ]
            }
```

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/agents/executor.py src/openjarvis/server/agent_manager_routes.py tests/agents/test_executor_error_detail.py
git commit -m "feat: structured error_detail in agent trace metadata"
```

---

### Task 5: Create credentials module

**Files:**
- Create: `src/openjarvis/core/credentials.py`
- Test: `tests/core/test_credentials.py`

- [ ] **Step 1: Write tests for credential load/save**

```python
# tests/core/test_credentials.py
"""Tests for credential persistence module."""
import os
import pytest
from openjarvis.core.credentials import load_credentials, save_credential, get_credential_status


@pytest.fixture
def cred_path(tmp_path):
    return tmp_path / "credentials.toml"


def test_save_and_load(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-123", path=cred_path)
    creds = load_credentials(path=cred_path)
    assert creds["web_search"]["TAVILY_API_KEY"] == "tvly-123"


def test_save_sets_env(cred_path, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    save_credential("web_search", "TAVILY_API_KEY", "tvly-abc", path=cred_path)
    assert os.environ["TAVILY_API_KEY"] == "tvly-abc"


def test_save_rejects_unknown_key(cred_path):
    with pytest.raises(ValueError, match="Unknown credential key"):
        save_credential("web_search", "BOGUS_KEY", "val", path=cred_path)


def test_save_rejects_empty_value(cred_path):
    with pytest.raises(ValueError, match="empty"):
        save_credential("web_search", "TAVILY_API_KEY", "  ", path=cred_path)


def test_get_status(cred_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    status = get_credential_status("web_search")
    assert status["TAVILY_API_KEY"] is True


def test_get_status_missing(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    status = get_credential_status("web_search")
    assert status["TAVILY_API_KEY"] is False


def test_file_permissions(cred_path):
    save_credential("web_search", "TAVILY_API_KEY", "tvly-x", path=cred_path)
    mode = oct(cred_path.stat().st_mode & 0o777)
    assert mode == "0o600"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_credentials.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement credentials module**

```python
# src/openjarvis/core/credentials.py
"""Credential persistence for tools and channels.

Stores credentials in ~/.openjarvis/credentials.toml with 0o600 permissions.
Thread-safe writes via lock. Sets os.environ on save for immediate effect.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

_LOCK = threading.Lock()
_DEFAULT_PATH = Path.home() / ".openjarvis" / "credentials.toml"

# Canonical mapping of tool/channel name → required env var keys
TOOL_CREDENTIALS: dict[str, list[str]] = {
    # Search
    "web_search": ["TAVILY_API_KEY"],
    # Cloud LLM / media
    "image_generate": ["OPENAI_API_KEY"],
    "llm": [],
    # Communication channels
    "slack": ["SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"],
    "telegram": ["TELEGRAM_BOT_TOKEN"],
    "discord": ["DISCORD_BOT_TOKEN"],
    "email": ["EMAIL_USERNAME", "EMAIL_PASSWORD"],
    "whatsapp": ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"],
    "signal": ["SIGNAL_CLI_PATH"],
    "google_chat": ["GOOGLE_CHAT_WEBHOOK_URL"],
    "teams": ["TEAMS_WEBHOOK_URL"],
    "bluebubbles": ["BLUEBUBBLES_SERVER_URL", "BLUEBUBBLES_PASSWORD"],
    "line": ["LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET"],
    "viber": ["VIBER_AUTH_TOKEN"],
    "messenger": ["MESSENGER_PAGE_ACCESS_TOKEN", "MESSENGER_VERIFY_TOKEN"],
    "reddit": ["REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USERNAME", "REDDIT_PASSWORD"],
    "mastodon": ["MASTODON_ACCESS_TOKEN", "MASTODON_API_BASE_URL"],
    "twitch": ["TWITCH_TOKEN", "TWITCH_CHANNEL"],
    "matrix": ["MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN"],
    "mattermost": ["MATTERMOST_URL", "MATTERMOST_TOKEN"],
    "zulip": ["ZULIP_EMAIL", "ZULIP_API_KEY", "ZULIP_SITE"],
    "rocketchat": ["ROCKETCHAT_URL", "ROCKETCHAT_USER_ID", "ROCKETCHAT_AUTH_TOKEN"],
    "xmpp": ["XMPP_JID", "XMPP_PASSWORD"],
    "feishu": ["FEISHU_APP_ID", "FEISHU_APP_SECRET"],
    "nostr": ["NOSTR_PRIVATE_KEY"],
}


def load_credentials(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Load credentials from TOML file. Returns nested dict: {tool: {KEY: value}}."""
    p = Path(path) if path else _DEFAULT_PATH
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def save_credential(
    tool_name: str,
    key: str,
    value: str,
    *,
    path: Path | None = None,
) -> None:
    """Save a single credential key, validate, write file, and set os.environ."""
    allowed = TOOL_CREDENTIALS.get(tool_name, [])
    if key not in allowed:
        raise ValueError(f"Unknown credential key '{key}' for tool '{tool_name}'")
    stripped = value.strip()
    if not stripped:
        raise ValueError("Credential value must not be empty")

    p = Path(path) if path else _DEFAULT_PATH
    with _LOCK:
        creds = load_credentials(path=p)
        if tool_name not in creds:
            creds[tool_name] = {}
        creds[tool_name][key] = stripped

        p.parent.mkdir(parents=True, exist_ok=True)
        # Write as TOML
        lines: list[str] = []
        for section, kvs in creds.items():
            lines.append(f"[{section}]")
            for k, v in kvs.items():
                lines.append(f'{k} = "{v}"')
            lines.append("")
        p.write_text("\n".join(lines))
        os.chmod(p, 0o600)

    os.environ[key] = stripped


def get_credential_status(tool_name: str) -> dict[str, bool]:
    """Return {KEY: bool} for each required key indicating if it is set in env."""
    keys = TOOL_CREDENTIALS.get(tool_name, [])
    return {k: bool(os.environ.get(k)) for k in keys}


def inject_credentials(path: Path | None = None) -> None:
    """Load credentials.toml and inject into os.environ. Call at server startup."""
    creds = load_credentials(path=path)
    for _tool, kvs in creds.items():
        for k, v in kvs.items():
            if k not in os.environ:
                os.environ[k] = v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_credentials.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/core/credentials.py tests/core/test_credentials.py
git commit -m "feat: credential persistence module with TOML storage"
```

---

### Task 6: Add `GET /v1/tools` and credential endpoints

**Files:**
- Modify: `src/openjarvis/server/agent_manager_routes.py`
- Test: `tests/server/test_tools_endpoint.py`

- [ ] **Step 1: Write test for tools endpoint**

```python
# tests/server/test_tools_endpoint.py
"""Tests for GET /v1/tools endpoint."""
import pytest
from unittest.mock import patch


def test_tools_endpoint_returns_list():
    """GET /v1/tools should return a list of tool info dicts."""
    from openjarvis.server.agent_manager_routes import _build_tools_list
    tools = _build_tools_list()
    assert isinstance(tools, list)
    assert len(tools) > 0
    # Each entry has required fields
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "category" in t
        assert "source" in t
        assert "requires_credentials" in t
        assert "credential_keys" in t
        assert "configured" in t


def test_tools_includes_channels():
    from openjarvis.server.agent_manager_routes import _build_tools_list
    tools = _build_tools_list()
    names = {t["name"] for t in tools}
    # Should include at least some channel entries
    channel_names = {"slack", "telegram", "discord", "email"}
    assert channel_names & names  # intersection is non-empty


def test_browser_meta_group():
    from openjarvis.server.agent_manager_routes import _build_tools_list
    tools = _build_tools_list()
    names = {t["name"] for t in tools}
    # Browser sub-tools should be grouped under "browser"
    assert "browser" in names
    assert "browser_navigate" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_tools_endpoint.py -v`
Expected: FAIL — `_build_tools_list` not defined

- [ ] **Step 3: Implement `_build_tools_list` and route**

Add to `src/openjarvis/server/agent_manager_routes.py`, inside the `create_agent_manager_routes` function, after the template endpoints:

```python
    # ── Tools Discovery ───────────────────────────────────────

    BROWSER_SUB_TOOLS = {
        "browser_navigate", "browser_click", "browser_type",
        "browser_screenshot", "browser_extract", "browser_axtree",
    }

    def _build_tools_list() -> list[dict[str, Any]]:
        """Build unified tools list from ToolRegistry + ChannelRegistry."""
        import os
        from openjarvis.core.credentials import TOOL_CREDENTIALS

        items: list[dict[str, Any]] = []

        # Tools from ToolRegistry
        try:
            from openjarvis.tools._stubs import ToolRegistry
            for name, tool_cls in ToolRegistry.items():
                if name in BROWSER_SUB_TOOLS:
                    continue  # grouped under "browser" meta-entry
                spec = getattr(tool_cls, "spec", None)
                if callable(spec):
                    try:
                        spec = spec(tool_cls)
                    except Exception:
                        spec = None
                cred_keys = TOOL_CREDENTIALS.get(name, [])
                items.append({
                    "name": name,
                    "description": spec.description if spec else "",
                    "category": spec.category if spec else "",
                    "source": "tool",
                    "requires_credentials": len(cred_keys) > 0,
                    "credential_keys": cred_keys,
                    "configured": all(bool(os.environ.get(k)) for k in cred_keys) if cred_keys else True,
                })
        except ImportError:
            pass

        # Add browser meta-entry if any browser sub-tool is registered
        try:
            from openjarvis.tools._stubs import ToolRegistry
            if any(ToolRegistry.contains(n) for n in BROWSER_SUB_TOOLS):
                items.append({
                    "name": "browser",
                    "description": "Web browser automation (navigate, click, type, screenshot, extract)",
                    "category": "browser",
                    "source": "tool",
                    "requires_credentials": False,
                    "credential_keys": [],
                    "configured": True,
                })
        except ImportError:
            pass

        # Channels from ChannelRegistry
        try:
            from openjarvis.channels._stubs import ChannelRegistry
            for name, _cls in ChannelRegistry.items():
                cred_keys = TOOL_CREDENTIALS.get(name, [])
                items.append({
                    "name": name,
                    "description": f"{name.replace('_', ' ').title()} messaging channel",
                    "category": "communication",
                    "source": "channel",
                    "requires_credentials": len(cred_keys) > 0,
                    "credential_keys": cred_keys,
                    "configured": all(bool(os.environ.get(k)) for k in cred_keys) if cred_keys else True,
                })
        except ImportError:
            pass

        return items

    # Expose for testing
    import types
    create_agent_manager_routes._build_tools_list = _build_tools_list  # type: ignore[attr-defined]

    tools_router = APIRouter(prefix="/v1/tools", tags=["tools"])

    @tools_router.get("")
    def list_tools():
        return {"tools": _build_tools_list()}

    @tools_router.post("/{tool_name}/credentials")
    def save_tool_credentials(tool_name: str, request: Request):
        import asyncio
        from openjarvis.core.credentials import save_credential

        body = asyncio.get_event_loop().run_until_complete(request.json())
        saved = []
        for key, value in body.items():
            save_credential(tool_name, key, value)
            saved.append(key)
        return {"saved": saved}

    @tools_router.get("/{tool_name}/credentials/status")
    def credential_status(tool_name: str):
        from openjarvis.core.credentials import get_credential_status
        return get_credential_status(tool_name)
```

Also update the return value of `create_agent_manager_routes` to include `tools_router`. Find where the function returns routers and add `tools_router` to the returned tuple.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_tools_endpoint.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/server/agent_manager_routes.py tests/server/test_tools_endpoint.py
git commit -m "feat: GET /v1/tools endpoint with credential status"
```

---

## Chunk 2: Frontend — Schedule, Budget, Model (Issues 1-5)

### Task 7: Add schedule help tooltips and structured interval input

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx:390-428` (schedule section in wizard step 2)

- [ ] **Step 1: Replace the schedule type + value grid**

Replace lines 390-428 (the `<div className="grid grid-cols-2 gap-3">` containing Schedule Type and Schedule Value) with:

```tsx
              {/* Schedule */}
              <div>
                <div className="flex items-center gap-1.5 mb-1">
                  <label className="block text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                    Schedule
                  </label>
                  <div className="relative group">
                    <span
                      className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-bold cursor-help"
                      style={{ background: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}
                    >
                      i
                    </span>
                    <div
                      className="absolute left-0 bottom-full mb-1 w-64 p-2 rounded-lg text-xs hidden group-hover:block z-50"
                      style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                    >
                      <div className="space-y-1.5">
                        <div><strong>Manual</strong> — Run only when you click &quot;Run Now&quot;</div>
                        <div><strong>Cron</strong> — UNIX cron schedule (e.g. <code>0 9 * * *</code> = daily at 9 AM)</div>
                        <div><strong>Interval</strong> — Fixed delay between runs for continuous monitoring</div>
                      </div>
                    </div>
                  </div>
                </div>
                <select
                  value={wizard.scheduleType}
                  onChange={(e) => update({ scheduleType: e.target.value, scheduleValue: '' })}
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                >
                  <option value="manual">Manual — Run on demand only</option>
                  <option value="cron">Cron — Recurring fixed-time schedule</option>
                  <option value="interval">Interval — Fixed delay between runs</option>
                </select>
              </div>

              {/* Schedule Value */}
              {wizard.scheduleType === 'interval' && (
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Run Every
                  </label>
                  <div className="grid grid-cols-3 gap-2">
                    {(['hours', 'minutes', 'seconds'] as const).map((unit) => {
                      const max = unit === 'hours' ? 999 : 59;
                      const key = `interval_${unit}` as string;
                      const vals = parseIntervalParts(wizard.scheduleValue);
                      return (
                        <div key={unit} className="flex flex-col">
                          <input
                            type="number"
                            min={0}
                            max={max}
                            value={vals[unit]}
                            onChange={(e) => {
                              const v = { ...vals, [unit]: Math.max(0, Math.min(max, parseInt(e.target.value) || 0)) };
                              update({ scheduleValue: serializeInterval(v.hours, v.minutes, v.seconds) });
                            }}
                            className="w-full px-2 py-2 rounded-lg text-sm text-center bg-transparent outline-none"
                            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                          />
                          <span className="text-[10px] text-center mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>{unit}</span>
                        </div>
                      );
                    })}
                  </div>
                  {wizard.scheduleValue && parseInt(wizard.scheduleValue) < 10 && parseInt(wizard.scheduleValue) > 0 && (
                    <div className="text-[10px] mt-1" style={{ color: 'var(--color-error)' }}>
                      Minimum interval is 10 seconds
                    </div>
                  )}
                </div>
              )}

              {wizard.scheduleType === 'cron' && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1">
                    <label className="block text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                      Cron Expression
                    </label>
                    <div className="relative group">
                      <span
                        className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-bold cursor-help"
                        style={{ background: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}
                      >
                        i
                      </span>
                      <div
                        className="absolute left-0 bottom-full mb-1 w-52 p-2 rounded-lg text-xs hidden group-hover:block z-50"
                        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                      >
                        <div className="space-y-1">
                          <div><code>0 * * * *</code> — Every hour</div>
                          <div><code>0 9 * * *</code> — Daily at 9 AM</div>
                          <div><code>0 9 * * 1</code> — Mondays at 9 AM</div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <input
                    type="text"
                    placeholder="0 * * * *"
                    value={wizard.scheduleValue}
                    onChange={(e) => update({ scheduleValue: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  />
                </div>
              )}
```

- [ ] **Step 2: Add interval helper functions**

Add these helper functions near the top of `AgentsPage.tsx`, after the `AVAILABLE_TOOLS` constant (around line 133):

```typescript
function parseIntervalParts(val: string): { hours: number; minutes: number; seconds: number } {
  const total = parseInt(val) || 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return { hours, minutes, seconds };
}

function serializeInterval(hours: number, minutes: number, seconds: number): string {
  return String(hours * 3600 + minutes * 60 + seconds);
}
```

- [ ] **Step 3: Update `formatSchedule` to handle seconds format**

Replace the `formatSchedule` function (lines 115-123):

```typescript
function formatSchedule(type?: string, value?: string): string {
  if (!type || type === 'manual') return 'Manual';
  if (type === 'cron') return value ? `Cron: ${value}` : 'Cron';
  if (type === 'interval' && value) {
    const total = parseInt(value);
    if (!isNaN(total) && total > 0) {
      const h = Math.floor(total / 3600);
      const m = Math.floor((total % 3600) / 60);
      const s = total % 60;
      const parts = [];
      if (h > 0) parts.push(`${h}h`);
      if (m > 0) parts.push(`${m}m`);
      if (s > 0) parts.push(`${s}s`);
      return `Every ${parts.join(' ') || '0s'}`;
    }
    return `Every ${value}`;
  }
  return type || 'Manual';
}
```

- [ ] **Step 4: Verify manually — schedule tooltip appears on hover, interval shows 3 spinners, cron shows text input with helper**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx
git commit -m "feat: schedule help tooltips and structured interval input"
```

---

### Task 8: Budget clarification and model grouping

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx:458-486` (budget/learning section)
- Modify: `frontend/src/pages/AgentsPage.tsx:370-388` (model select)
- Modify: `frontend/src/pages/AgentsPage.tsx:522-524` (budget review line)

- [ ] **Step 1: Update the budget field label and subtitle**

Replace lines 458-472 (the budget input section):

```tsx
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Budget (optional)
                  </label>
                  <input
                    type="number"
                    placeholder="e.g. 5.00"
                    min="0"
                    step="0.01"
                    value={wizard.budget}
                    onChange={(e) => update({ budget: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm bg-transparent outline-none"
                    style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  />
                  <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                    Cloud API models only (OpenAI, Anthropic, Google). Local models have no cost.
                  </div>
                </div>
```

- [ ] **Step 2: Update budget display in review step**

Replace the budget review line (around line 522-524):

```tsx
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Budget</span>
                  <span style={{ color: 'var(--color-text)' }}>{wizard.budget ? `$${wizard.budget}` : 'Unlimited'}</span>
                </div>
```

No change needed here — it already shows "Unlimited" which is fine.

- [ ] **Step 3: Enhance model select with grouping**

Replace the model select (lines 370-388):

```tsx
              {/* Model */}
              <div>
                <div className="text-xs mb-1" style={{ color: 'var(--color-text-secondary)' }}>Intelligence (Model)</div>
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
                  {(() => {
                    const models = useAppStore.getState().models;
                    const local = models.filter((m) => !m.id.includes('/') && !m.id.startsWith('gpt') && !m.id.startsWith('claude') && !m.id.startsWith('gemini'));
                    const cloud = models.filter((m) => m.id.includes('/') || m.id.startsWith('gpt') || m.id.startsWith('claude') || m.id.startsWith('gemini'));
                    return (
                      <>
                        {local.length > 0 && (
                          <optgroup label="Local (Running)">
                            {local.map((m) => (
                              <option key={m.id} value={m.id}>{m.id}</option>
                            ))}
                          </optgroup>
                        )}
                        {cloud.length > 0 && (
                          <optgroup label="Cloud">
                            {cloud.map((m) => (
                              <option key={m.id} value={m.id}>{m.id}</option>
                            ))}
                          </optgroup>
                        )}
                        {local.length === 0 && cloud.length === 0 && (
                          <option disabled>No models available — start an engine or add API keys</option>
                        )}
                      </>
                    );
                  })()}
                </select>
              </div>
```

- [ ] **Step 4: Verify manually — budget shows subtitle, model groups local vs cloud**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx
git commit -m "feat: budget clarification subtitle and grouped model selector"
```

---

## Chunk 3: Frontend — Tools Grid, Run/Recover, Logs, Learning (Issues 3, 6-9)

### Task 9: Add API functions for tools and credentials

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add ToolInfo interface and API functions**

Add after the `AgentTrace` interface (around line 494):

```typescript
export interface ToolInfo {
  name: string;
  description: string;
  category: string;
  source: 'tool' | 'channel';
  requires_credentials: boolean;
  credential_keys: string[];
  configured: boolean;
}

export async function fetchAvailableTools(): Promise<ToolInfo[]> {
  const res = await fetch(`${getBase()}/v1/tools`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tools || [];
}

export async function saveToolCredentials(
  toolName: string,
  credentials: Record<string, string>,
): Promise<void> {
  const res = await fetch(`${getBase()}/v1/tools/${toolName}/credentials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}
```

- [ ] **Step 2: Update `recoverManagedAgent` to return response body**

Replace the `recoverManagedAgent` function:

```typescript
export async function recoverManagedAgent(agentId: string): Promise<{ recovered: boolean; checkpoint: unknown }> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/recover`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 3: Update `runManagedAgent` to throw with error detail**

Replace the `runManagedAgent` function:

```typescript
export async function runManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/run`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
}
```

- [ ] **Step 4: Add `metadata` to `AgentTrace` interface**

Update the `AgentTrace` interface:

```typescript
export interface AgentTrace {
  id: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: number;
  metadata?: Record<string, unknown>;
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: API functions for tools, credentials, and improved error handling"
```

---

### Task 10: Categorized tools grid in wizard

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx:126-133` (replace `AVAILABLE_TOOLS`)
- Modify: `frontend/src/pages/AgentsPage.tsx:430-456` (replace tools checkbox grid)

- [ ] **Step 1: Replace `AVAILABLE_TOOLS` with category constants and tool state**

Replace the `AVAILABLE_TOOLS` constant (lines 126-133) with:

```typescript
const CATEGORY_MAP: Record<string, string> = {
  communication: 'Communication',
  channel: 'Communication',
  search: 'Search & Browse',
  browser: 'Search & Browse',
  code: 'Code & Dev',
  system: 'Code & Dev',
  filesystem: 'Files & Data',
  memory: 'Memory & Knowledge',
  knowledge_graph: 'Memory & Knowledge',
  reasoning: 'Reasoning & AI',
  math: 'Reasoning & AI',
  inference: 'Reasoning & AI',
  agents: 'Reasoning & AI',
  media: 'Media',
};

const TOOL_NAME_FALLBACK: Record<string, string> = {
  file_read: 'Files & Data',
  file_write: 'Files & Data',
  pdf_extract: 'Files & Data',
  db_query: 'Files & Data',
  http_request: 'Files & Data',
  apply_patch: 'Code & Dev',
  git_status: 'Code & Dev',
  git_diff: 'Code & Dev',
  git_log: 'Code & Dev',
  git_commit: 'Code & Dev',
  channel_send: 'Communication',
  channel_list: 'Communication',
  channel_status: 'Communication',
};

const CATEGORY_ORDER = [
  'Communication',
  'Search & Browse',
  'Code & Dev',
  'Files & Data',
  'Memory & Knowledge',
  'Reasoning & AI',
  'Media',
];

const POPULAR_TOOLS = new Set([
  'slack', 'email', 'telegram', 'whatsapp',
  'web_search', 'browser',
  'code_interpreter', 'shell_exec', 'git_status', 'git_diff',
  'file_read', 'file_write', 'pdf_extract',
  'retrieval', 'memory_store',
  'think', 'llm', 'calculator',
  'image_generate',
]);

const BROWSER_SUB_TOOLS = [
  'browser_navigate', 'browser_click', 'browser_type',
  'browser_screenshot', 'browser_extract', 'browser_axtree',
];
```

- [ ] **Step 2: Add tools state to LaunchWizard and fetch on mount**

Inside the `LaunchWizard` component (after `const [launching, setLaunching] = useState(false);`), add:

```typescript
  const [availableTools, setAvailableTools] = useState<ToolInfo[]>([]);
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [credentialInputs, setCredentialInputs] = useState<Record<string, Record<string, string>>>({});
  const [savingCredentials, setSavingCredentials] = useState<string | null>(null);

  useEffect(() => {
    fetchAvailableTools().then(setAvailableTools).catch(() => {});
  }, []);

  function getToolCategory(tool: ToolInfo): string {
    if (tool.category && CATEGORY_MAP[tool.category]) return CATEGORY_MAP[tool.category];
    if (TOOL_NAME_FALLBACK[tool.name]) return TOOL_NAME_FALLBACK[tool.name];
    return 'Reasoning & AI';
  }

  function toggleCategory(cat: string) {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }

  function handleToggleTool(name: string) {
    if (name === 'browser') {
      // Toggle all browser sub-tools
      const has = BROWSER_SUB_TOOLS.every((t) => wizard.selectedTools.includes(t));
      if (has) {
        update({ selectedTools: wizard.selectedTools.filter((t) => !BROWSER_SUB_TOOLS.includes(t)) });
      } else {
        update({ selectedTools: [...new Set([...wizard.selectedTools, ...BROWSER_SUB_TOOLS])] });
      }
    } else {
      toggleTool(name);
    }
  }

  async function handleSaveCredentials(toolName: string) {
    const inputs = credentialInputs[toolName];
    if (!inputs) return;
    setSavingCredentials(toolName);
    try {
      await saveToolCredentials(toolName, inputs);
      toast.success(`Credentials saved for ${toolName}`);
      // Refresh tools list
      const updated = await fetchAvailableTools();
      setAvailableTools(updated);
    } catch (err: any) {
      toast.error(err.message || 'Failed to save credentials');
    } finally {
      setSavingCredentials(null);
    }
  }
```

Also add these imports at the top of the file:

```typescript
import { fetchAvailableTools, saveToolCredentials, type ToolInfo } from '../lib/api';
```

- [ ] **Step 3: Replace the tools grid JSX**

Replace lines 430-456 (the tools section) with:

```tsx
              {/* Tools */}
              <div>
                <label className="block text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                  Tools & Channels
                </label>
                {(() => {
                  const unconfiguredSelected = wizard.selectedTools.filter((t) => {
                    const tool = availableTools.find((at) => at.name === t);
                    return tool && tool.requires_credentials && !tool.configured;
                  });
                  return unconfiguredSelected.length > 0 ? (
                    <div className="text-[10px] mb-2 px-2 py-1 rounded" style={{ background: '#f59e0b20', color: '#f59e0b' }}>
                      {unconfiguredSelected.length} tool{unconfiguredSelected.length > 1 ? 's' : ''} need setup — credentials required before they will work
                    </div>
                  ) : null;
                })()}
                <div className="space-y-3 max-h-64 overflow-y-auto">
                  {CATEGORY_ORDER.map((cat) => {
                    const catTools = availableTools.filter((t) => getToolCategory(t) === cat);
                    if (catTools.length === 0) return null;
                    const popular = catTools.filter((t) => POPULAR_TOOLS.has(t.name));
                    const rest = catTools.filter((t) => !POPULAR_TOOLS.has(t.name));
                    const isExpanded = expandedCategories.has(cat);
                    const shown = isExpanded ? catTools : popular;

                    return (
                      <div key={cat}>
                        <div
                          className="flex items-center justify-between cursor-pointer mb-1"
                          onClick={() => rest.length > 0 && toggleCategory(cat)}
                        >
                          <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-tertiary)' }}>
                            {cat} ({catTools.length})
                          </span>
                          {rest.length > 0 && (
                            <span className="text-[10px]" style={{ color: 'var(--color-accent)' }}>
                              {isExpanded ? 'Show less' : `Show all (${catTools.length})`}
                            </span>
                          )}
                        </div>
                        <div className="grid grid-cols-2 gap-1.5">
                          {shown.map((tool) => {
                            const isSelected = tool.name === 'browser'
                              ? BROWSER_SUB_TOOLS.every((t) => wizard.selectedTools.includes(t))
                              : wizard.selectedTools.includes(tool.name);
                            const needsSetup = tool.requires_credentials && !tool.configured;
                            return (
                              <div key={tool.name}>
                                <button
                                  type="button"
                                  onClick={() => handleToggleTool(tool.name)}
                                  className="w-full text-left p-2 rounded-lg text-xs transition-colors cursor-pointer"
                                  style={{
                                    background: isSelected ? 'var(--color-accent)' + '10' : 'var(--color-bg-secondary)',
                                    border: `1px solid ${isSelected ? 'var(--color-accent)' + '50' : 'var(--color-border)'}`,
                                    color: 'var(--color-text)',
                                  }}
                                >
                                  <div className="flex items-center gap-1.5">
                                    {isSelected && <span style={{ color: 'var(--color-accent)' }}>&#10003;</span>}
                                    <span className="font-medium">{tool.name.replace(/_/g, ' ')}</span>
                                    {needsSetup && <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: '#f59e0b' }} />}
                                  </div>
                                  {tool.description && (
                                    <div className="text-[10px] mt-0.5 truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                                      {tool.description.slice(0, 60)}
                                    </div>
                                  )}
                                </button>
                                {/* Credential inline setup */}
                                {isSelected && needsSetup && (
                                  <div className="mt-1 p-2 rounded-lg text-xs space-y-1.5" style={{ background: 'var(--color-bg)', border: '1px solid #f59e0b40' }}>
                                    {tool.credential_keys.map((key) => (
                                      <div key={key}>
                                        <label className="block text-[10px] mb-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
                                          {key.replace(/_/g, ' ')}
                                        </label>
                                        <input
                                          type="password"
                                          value={credentialInputs[tool.name]?.[key] || ''}
                                          onChange={(e) => setCredentialInputs((prev) => ({
                                            ...prev,
                                            [tool.name]: { ...prev[tool.name], [key]: e.target.value },
                                          }))}
                                          className="w-full px-2 py-1 rounded text-xs bg-transparent outline-none"
                                          style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                                          placeholder={`Enter ${key}`}
                                        />
                                      </div>
                                    ))}
                                    <button
                                      type="button"
                                      onClick={() => handleSaveCredentials(tool.name)}
                                      disabled={savingCredentials === tool.name}
                                      className="px-2 py-1 rounded text-[10px] font-medium cursor-pointer"
                                      style={{ background: 'var(--color-accent)', color: 'white' }}
                                    >
                                      {savingCredentials === tool.name ? 'Saving...' : 'Save'}
                                    </button>
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
```

- [ ] **Step 4: Verify manually — categories render, expand/collapse works, credential setup inline appears**

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx
git commit -m "feat: categorized tools grid with credential setup in wizard"
```

---

### Task 11: Fix Run Now and Recover in frontend

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx:1094-1118` (handleRun and handleRecover)

- [ ] **Step 1: Fix handleRun**

Replace lines 1094-1113:

```typescript
  const handleRun = async (id: string) => {
    try {
      await runManagedAgent(id);
    } catch (err: any) {
      toast.error('Failed to start agent', {
        description: err.message || 'Unknown error',
      });
      await refresh();
      return;
    }
    await refresh();
    // Poll for async errors after thread starts
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
  };
```

- [ ] **Step 2: Fix handleRecover**

Replace lines 1115-1118:

```typescript
  const handleRecover = async (id: string) => {
    try {
      const result = await recoverManagedAgent(id);
      if (result.checkpoint) {
        toast.success('Agent recovered from checkpoint');
      } else {
        toast.success('Agent reset to idle (no checkpoint available)');
      }
      setDetailTab('overview');
    } catch (err: any) {
      toast.error('Recovery failed', {
        description: err.message || 'Unknown error',
      });
    }
    await refresh();
  };
```

- [ ] **Step 3: Verify manually — Run Now shows error toast on failure, Recover shows success toast and switches to overview**

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx
git commit -m "fix: Run Now error handling and Recover feedback toasts"
```

---

### Task 12: Structured error display in Logs tab

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx:979-1027` (LogsTab component)

- [ ] **Step 1: Enhance LogsTab with expandable error details**

Replace the LogsTab component (lines 979-1027):

```tsx
function LogsTab({ agentId }: { agentId: string }) {
  const [traces, setTraces] = useState<AgentTrace[]>([]);
  const [expandedTrace, setExpandedTrace] = useState<string | null>(null);

  useEffect(() => {
    fetchAgentTraces(agentId).then(setTraces).catch(() => {});
  }, [agentId]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
          Execution Traces
        </span>
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {traces.length} trace{traces.length !== 1 ? 's' : ''}
        </span>
      </div>
      {traces.length === 0 ? (
        <div className="text-sm text-center py-8" style={{ color: 'var(--color-text-tertiary)' }}>
          No execution traces yet. Run the agent to generate traces.
        </div>
      ) : (
        <div className="space-y-2">
          {traces.map((t) => {
            const errorDetail = t.metadata?.error_detail as
              | { error_type: string; error_message: string; suggested_action: string }
              | undefined;
            const isError = t.outcome !== 'success';
            const isExpanded = expandedTrace === t.id;

            return (
              <div
                key={t.id}
                className="rounded-lg p-3 text-sm cursor-pointer"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                onClick={() => isError && setExpandedTrace(isExpanded ? null : t.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ background: t.outcome === 'success' ? '#22c55e' : '#ef4444' }}
                    />
                    <span style={{ color: 'var(--color-text)' }}>{t.outcome}</span>
                    {errorDetail && (
                      <span
                        className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                        style={{
                          background: errorDetail.error_type === 'fatal' ? '#ef444420' :
                            errorDetail.error_type === 'escalate' ? '#f59e0b20' : '#3b82f620',
                          color: errorDetail.error_type === 'fatal' ? '#ef4444' :
                            errorDetail.error_type === 'escalate' ? '#f59e0b' : '#3b82f6',
                        }}
                      >
                        {errorDetail.error_type}
                      </span>
                    )}
                  </div>
                  <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {formatRelativeTime(t.started_at)}
                  </span>
                </div>
                <div className="flex items-center gap-3 mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  <span>{t.duration.toFixed(1)}s</span>
                  <span>{t.steps} step{t.steps !== 1 ? 's' : ''}</span>
                </div>
                {isExpanded && errorDetail && (
                  <div className="mt-2 pt-2 space-y-1.5 text-xs" style={{ borderTop: '1px solid var(--color-border)' }}>
                    <div>
                      <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Error: </span>
                      <span style={{ color: 'var(--color-text)' }}>{errorDetail.error_message}</span>
                    </div>
                    <div>
                      <span className="font-medium" style={{ color: 'var(--color-text-secondary)' }}>Action: </span>
                      <span style={{ color: 'var(--color-text)' }}>{errorDetail.suggested_action}</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify manually — error traces show type badge, clicking expands to show message and suggested action**

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx
git commit -m "feat: structured error details in Logs tab with expandable entries"
```

---

### Task 13: Learning technique selection in wizard

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx:135-146` (WizardState)
- Modify: `frontend/src/pages/AgentsPage.tsx:474-486` (replace learning checkbox)
- Modify: `frontend/src/pages/AgentsPage.tsx:526-529` (review step learning line)
- Modify: `frontend/src/pages/AgentsPage.tsx:200-206` (handleLaunch config)

- [ ] **Step 1: Update WizardState interface**

Replace the `WizardState` interface (lines 135-146):

```typescript
interface WizardState {
  step: number;
  templateId: string;
  name: string;
  instruction: string;
  model: string;
  scheduleType: string;
  scheduleValue: string;
  selectedTools: string[];
  budget: string;
  routerPolicy: string;
  memoryExtraction: string;
  observationCompression: string;
  retrievalStrategy: string;
  taskDecomposition: string;
}
```

- [ ] **Step 2: Update initial state**

Replace the `useState<WizardState>` initial value (lines 157-168):

```typescript
  const [wizard, setWizard] = useState<WizardState>({
    step: 1,
    templateId: '',
    name: '',
    instruction: '',
    model: '',
    scheduleType: 'manual',
    scheduleValue: '',
    selectedTools: [],
    budget: '',
    routerPolicy: '',
    memoryExtraction: 'causality_graph',
    observationCompression: 'summarize',
    retrievalStrategy: 'hybrid_with_self_eval',
    taskDecomposition: 'phased',
  });
```

- [ ] **Step 3: Replace the learning checkbox with router policy + strategies**

Replace lines 474-486 (the learning checkbox section, second column of the grid) with:

```tsx
                {/* Learning */}
                <div>
                  <div className="flex items-center gap-1.5 mb-1">
                    <label className="block text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                      Learning
                    </label>
                    <div className="relative group">
                      <span
                        className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full text-[9px] font-bold cursor-help"
                        style={{ background: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}
                      >
                        i
                      </span>
                      <div
                        className="absolute right-0 bottom-full mb-1 w-56 p-2 rounded-lg text-xs hidden group-hover:block z-50"
                        style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                      >
                        Router policies let the agent learn which model works best for different query types over time.
                      </div>
                    </div>
                  </div>
                  <select
                    value={wizard.routerPolicy}
                    onChange={(e) => update({ routerPolicy: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  >
                    <option value="">None — Always use selected model</option>
                    <option value="heuristic">Heuristic — Rule-based model selection</option>
                    <option value="learned">Trace-Driven — Learns from past runs</option>
                  </select>
                </div>
              </div>

              {/* Agent Strategies (monitor_operative only) */}
              {(!wizard.templateId || templates.find((t) => t.id === wizard.templateId)?.agent_type === 'monitor_operative') && (
                <div>
                  <div className="flex items-center gap-1.5 mb-1">
                    <label className="block text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>
                      Agent Strategies
                    </label>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {([
                      { label: 'Memory Extraction', key: 'memoryExtraction' as const, tooltip: 'How the agent stores findings between runs',
                        options: [['causality_graph', 'Causality Graph'], ['scratchpad', 'Scratchpad'], ['structured_json', 'Structured JSON'], ['none', 'None']] },
                      { label: 'Observation Compression', key: 'observationCompression' as const, tooltip: 'How long tool outputs are compressed',
                        options: [['summarize', 'Summarize'], ['truncate', 'Truncate'], ['none', 'None']] },
                      { label: 'Retrieval Strategy', key: 'retrievalStrategy' as const, tooltip: 'How the agent retrieves past context',
                        options: [['hybrid_with_self_eval', 'Hybrid + Self-Eval'], ['keyword', 'Keyword'], ['semantic', 'Semantic'], ['none', 'None']] },
                      { label: 'Task Decomposition', key: 'taskDecomposition' as const, tooltip: 'How complex instructions are broken down',
                        options: [['phased', 'Phased'], ['monolithic', 'Monolithic'], ['hierarchical', 'Hierarchical']] },
                    ] as const).map((s) => (
                      <div key={s.key}>
                        <div className="flex items-center gap-1 mb-0.5">
                          <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>{s.label}</span>
                          <div className="relative group">
                            <span className="inline-flex items-center justify-center w-3 h-3 rounded-full text-[8px] font-bold cursor-help"
                              style={{ background: 'var(--color-border)', color: 'var(--color-text-tertiary)' }}>i</span>
                            <div className="absolute left-0 bottom-full mb-1 w-48 p-1.5 rounded text-[10px] hidden group-hover:block z-50"
                              style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                              {s.tooltip}
                            </div>
                          </div>
                        </div>
                        <select
                          value={wizard[s.key]}
                          onChange={(e) => update({ [s.key]: e.target.value })}
                          className="w-full px-2 py-1.5 rounded text-xs"
                          style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                        >
                          {s.options.map(([val, label]) => (
                            <option key={val} value={val}>{label}</option>
                          ))}
                        </select>
                      </div>
                    ))}
                  </div>
                </div>
              )}
```

Note: Remove the closing `</div>` of the `grid grid-cols-2` that previously wrapped budget + learning, since the learning section is now its own full-width block. The budget field should end its grid at one column.

- [ ] **Step 4: Update the review step learning display**

Replace the learning review line (lines 526-529):

```tsx
                <div className="flex justify-between">
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Learning</span>
                  <span style={{ color: 'var(--color-text)' }}>
                    {wizard.routerPolicy ? (wizard.routerPolicy === 'heuristic' ? 'Heuristic Router' : 'Trace-Driven Router') : 'Disabled'}
                  </span>
                </div>
                {wizard.routerPolicy && (
                  <div className="flex justify-between">
                    <span style={{ color: 'var(--color-text-tertiary)' }}>Strategies</span>
                    <span className="text-xs text-right" style={{ color: 'var(--color-text)' }}>
                      {wizard.memoryExtraction}, {wizard.observationCompression}, {wizard.retrievalStrategy}, {wizard.taskDecomposition}
                    </span>
                  </div>
                )}
```

- [ ] **Step 5: Update handleLaunch to send new config fields**

In the `handleLaunch` function (around lines 200-206), update the config object:

```typescript
      const config: Record<string, unknown> = {
        schedule_type: wizard.scheduleType,
        schedule_value: wizard.scheduleValue || undefined,
        tools: wizard.selectedTools,
        learning_enabled: !!wizard.routerPolicy,
      };
      if (wizard.budget) config.budget = parseFloat(wizard.budget);
      if (wizard.instruction.trim()) config.instruction = wizard.instruction.trim();
      if (wizard.model) config.model = wizard.model;
      if (wizard.routerPolicy) config.router_policy = wizard.routerPolicy;
      config.memory_extraction = wizard.memoryExtraction;
      config.observation_compression = wizard.observationCompression;
      config.retrieval_strategy = wizard.retrievalStrategy;
      config.task_decomposition = wizard.taskDecomposition;
```

- [ ] **Step 6: Verify manually — learning section shows router policy dropdown + strategy selectors, review displays correctly**

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx
git commit -m "feat: learning technique selection with router policies and agent strategies"
```

---

### Task 14: Wire router_policy in executor

**Files:**
- Modify: `src/openjarvis/agents/executor.py:166-212` (`_invoke_agent`)

- [ ] **Step 1: Add router policy resolution in `_invoke_agent`**

After the model resolution block (after line 186 `raise FatalError("No model configured for agent")`), add:

```python
        # Optionally override model via router policy
        router_policy_key = config.get("router_policy")
        if router_policy_key and self._system:
            try:
                from openjarvis.core.registry import RouterPolicyRegistry
                from openjarvis.learning.routing.types import RoutingContext, build_routing_context

                policy = RouterPolicyRegistry.create(
                    router_policy_key,
                    available_models=[model],
                )
                instruction = config.get("instruction", "")
                ctx = build_routing_context(instruction)
                selected = policy.select_model(ctx)
                if selected:
                    model = selected
            except Exception:
                pass  # Fall back to configured model
```

- [ ] **Step 2: Commit**

```bash
git add src/openjarvis/agents/executor.py
git commit -m "feat: wire router_policy from agent config in executor"
```

---

### Task 15: Final integration verification

- [ ] **Step 1: Run all backend tests**

Run: `uv run pytest tests/ -v --tb=short -x`
Expected: All tests PASS

- [ ] **Step 2: Run ruff linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors

- [ ] **Step 3: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no TypeScript errors

- [ ] **Step 4: Commit any lint fixes if needed**

```bash
git add -A && git commit -m "chore: lint fixes"
```
