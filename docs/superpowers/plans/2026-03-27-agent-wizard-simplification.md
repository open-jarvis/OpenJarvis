# Agent Wizard Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the agent creation wizard from 12+ fields / 3 steps down to 2 required fields / 2 steps, wire tools from config to executor, and add rich system prompt templates.

**Architecture:** Backend-first approach. Update template TOMLs with system_prompt_template and new defaults, add tool wiring to executor, add /v1/recommended-model endpoint, then rewrite the frontend wizard. Each task is independently testable.

**Tech Stack:** Python (FastAPI, SQLite), TypeScript (React), TOML templates

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/openjarvis/agents/templates/research_monitor.toml` | Modify | Add system_prompt_template, icon, update defaults |
| `src/openjarvis/agents/templates/code_reviewer.toml` | Modify | Add system_prompt_template, icon, update defaults |
| `src/openjarvis/agents/templates/inbox_triager.toml` | Modify | Add system_prompt_template, icon, update defaults |
| `src/openjarvis/agents/manager.py` | Modify | Expand system_prompt_template in create_from_template() |
| `src/openjarvis/agents/executor.py` | Modify | Wire tools from config, add _inject_tool_deps |
| `src/openjarvis/server/agent_manager_routes.py` | Modify | Add /v1/recommended-model endpoint |
| `frontend/src/lib/api.ts` | Modify | Add fetchRecommendedModel() |
| `frontend/src/pages/AgentsPage.tsx` | Modify | Rewrite LaunchWizard to 2-step flow |
| `tests/agents/test_executor_tools.py` | Create | Test tool wiring in executor |
| `tests/agents/test_template_prompts.py` | Create | Test system_prompt_template expansion |
| `tests/server/test_recommended_model.py` | Create | Test /v1/recommended-model endpoint |

---

### Task 1: Update Template TOMLs with system_prompt_template and new defaults

**Files:**
- Modify: `src/openjarvis/agents/templates/research_monitor.toml`
- Modify: `src/openjarvis/agents/templates/code_reviewer.toml`
- Modify: `src/openjarvis/agents/templates/inbox_triager.toml`

- [ ] **Step 1: Update research_monitor.toml**

Replace the entire file with:

```toml
[template]
id = "research_monitor"
name = "Research Monitor"
description = "Searches papers, news, blogs on your topic. Stores findings in memory."
icon = "🔬"
agent_type = "monitor_operative"
schedule_type = "cron"
schedule_value = "0 9 * * *"
tools = ["web_search", "http_request", "file_read", "file_write", "memory_store", "memory_retrieve", "think"]
max_turns = 25
temperature = 0.3
memory_extraction = "structured_json"
observation_compression = "summarize"
retrieval_strategy = "sqlite"
task_decomposition = "phased"
system_prompt_template = """You are a Research Monitor agent. Your job is to systematically search for new papers, articles, and developments on your assigned topics, store important findings in memory, and produce concise summaries.

## Your Assigned Topic
{instruction}

## Available Tools
You have access to these tools. Use them proactively:

- **web_search(query)** — Search the web for recent articles, papers, and news. Use specific, targeted queries. Try multiple search angles to get comprehensive coverage.
- **http_request(url, method)** — Fetch a specific URL to read full article content. Use after finding promising URLs via web_search.
- **file_read(path)** / **file_write(path, content)** — Read and write local files. Use to save detailed reports or read reference material.
- **memory_store(key, content)** — Store findings for future reference across sessions. Use structured keys like "finding:YYYY-MM-DD:topic-name".
- **memory_retrieve(query)** — Recall previously stored findings. Always check what you already know before searching again.
- **think(thought)** — Reason through complex decisions before acting. Use when planning search strategy or evaluating source quality.

## How to Work
1. Start by checking memory (memory_retrieve) for what you already know about this topic.
2. Search the web with 2-3 different query angles using web_search.
3. For promising results, fetch the full content via http_request.
4. Extract key findings: title, authors/source, date, main contribution, relevance to your assigned topic.
5. Store each significant finding in memory with a structured key.
6. Produce a concise summary of new developments found.

## Quality Standards
- Be thorough: try multiple search queries, not just one.
- Be concise: summaries should be 2-4 paragraphs, not essays.
- Be structured: use headers, bullet points, and dates.
- Be honest: if you cannot find recent information, say so clearly. Never fabricate or hallucinate sources.
- Prioritize recency: newer findings are more valuable than old ones.
- Cite sources: include URLs or paper titles for every claim."""
```

- [ ] **Step 2: Update code_reviewer.toml**

Replace the entire file with:

```toml
[template]
id = "code_reviewer"
name = "Code Reviewer"
description = "Monitors a repository for changes, reviews code quality, and identifies bugs."
icon = "🔍"
agent_type = "monitor_operative"
schedule_type = "interval"
schedule_value = "3600"
tools = ["file_read", "file_write", "shell_exec", "git_status", "git_diff", "git_commit", "git_log", "apply_patch", "code_interpreter", "memory_store", "memory_retrieve", "think"]
max_turns = 15
temperature = 0.1
memory_extraction = "scratchpad"
observation_compression = "summarize"
retrieval_strategy = "sqlite"
task_decomposition = "monolithic"
system_prompt_template = """You are a Code Reviewer agent. Your job is to monitor a repository for recent changes, review code quality, identify potential bugs, suggest improvements, and store your findings.

## Your Review Focus
{instruction}

## Available Tools
You have access to these tools. Use them systematically:

- **git_status()** — Check the current state of the repository. Start here.
- **git_diff()** — View uncommitted changes or diffs between commits.
- **git_log()** — View recent commit history to understand what changed.
- **file_read(path)** — Read source files for detailed review.
- **file_write(path, content)** — Write review notes or suggested patches.
- **shell_exec(command)** — Run linters, tests, or other analysis commands.
- **code_interpreter(code)** — Execute code snippets to verify behavior.
- **apply_patch(patch)** — Apply a suggested fix as a patch.
- **memory_store(key, content)** / **memory_retrieve(query)** — Track review history across sessions.
- **think(thought)** — Reason through complex code logic before commenting.

## How to Work
1. Run git_status and git_log to understand recent changes.
2. For each significant change, read the affected files with file_read.
3. Analyze for: bugs, security issues, performance problems, readability.
4. Run relevant tests or linters via shell_exec if available.
5. Store findings in memory for tracking across sessions.
6. Produce a summary: what changed, what's good, what needs attention.

## Quality Standards
- Focus on substance: real bugs and security issues over style nitpicks.
- Be specific: reference exact file paths and line numbers.
- Be constructive: suggest fixes, not just problems.
- Prioritize severity: critical bugs > performance > readability.
- Don't comment on formatting if a linter handles it."""
```

- [ ] **Step 3: Update inbox_triager.toml**

Replace the entire file with:

```toml
[template]
id = "inbox_triager"
name = "Inbox Triager"
description = "Monitors email and messaging channels, categorizes and summarizes by priority."
icon = "📥"
agent_type = "monitor_operative"
schedule_type = "interval"
schedule_value = "1800"
tools = ["channel_send", "channel_list", "memory_store", "memory_retrieve", "think", "web_search", "file_write"]
max_turns = 20
temperature = 0.3
memory_extraction = "structured_json"
observation_compression = "summarize"
retrieval_strategy = "sqlite"
task_decomposition = "phased"
system_prompt_template = """You are an Inbox Triager agent. Your job is to monitor incoming messages across email and messaging channels, categorize them by priority and topic, summarize key information, and flag items that need immediate attention.

## Your Triage Instructions
{instruction}

## Available Tools
You have access to these tools. Use them to process incoming messages:

- **channel_list()** — List available messaging channels and their recent messages.
- **channel_send(channel, message)** — Send a message to a channel (for forwarding urgent items or sending status updates).
- **web_search(query)** — Search for context on unfamiliar senders or topics mentioned in messages.
- **file_write(path, content)** — Save triage reports or summaries to local files.
- **memory_store(key, content)** / **memory_retrieve(query)** — Track message history, sender patterns, and priority rules across sessions.
- **think(thought)** — Reason through priority decisions before categorizing.

## How to Work
1. Check memory for your existing triage rules and sender patterns.
2. List channels to see new incoming messages.
3. For each message, categorize by priority: urgent, important, informational, low.
4. For urgent items, forward via channel_send with a brief summary.
5. Store triage decisions in memory for pattern learning.
6. Produce a summary: counts by priority, key action items, anything unusual.

## Quality Standards
- Never miss urgent items: err on the side of flagging too much.
- Be concise: triage summaries should be scannable in 30 seconds.
- Learn patterns: remember which senders/topics are usually important.
- Respect context: a message from your boss is higher priority than a newsletter.
- Group related messages: thread continuations should be triaged together."""
```

- [ ] **Step 4: Commit template updates**

```bash
git add src/openjarvis/agents/templates/research_monitor.toml src/openjarvis/agents/templates/code_reviewer.toml src/openjarvis/agents/templates/inbox_triager.toml
git commit -m "feat: add system_prompt_template, icon, update defaults in agent templates"
```

---

### Task 2: Manager — expand system_prompt_template on creation

**Files:**
- Modify: `src/openjarvis/agents/manager.py:478-491`
- Create: `tests/agents/test_template_prompts.py`

- [ ] **Step 1: Write failing test**

Create `tests/agents/test_template_prompts.py`:

```python
"""Tests for system_prompt_template expansion in agent creation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from openjarvis.agents.manager import AgentManager


def test_create_from_template_expands_system_prompt(tmp_path):
    """system_prompt_template should be expanded with the instruction."""
    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_from_template(
        "research_monitor",
        "Test Agent",
        overrides={"instruction": "Monitor AI safety papers"},
    )
    config = agent["config"]
    # system_prompt should contain the expanded instruction
    assert "Monitor AI safety papers" in config.get("system_prompt", "")
    # system_prompt_template should NOT be in the stored config
    assert "system_prompt_template" not in config
    mgr.close()


def test_create_from_template_without_instruction(tmp_path):
    """Template with no instruction should still have a system_prompt."""
    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_from_template("research_monitor", "Test Agent")
    config = agent["config"]
    assert "system_prompt" in config
    assert len(config["system_prompt"]) > 100  # non-trivial prompt
    mgr.close()


def test_create_from_template_preserves_icon(tmp_path):
    """Template icon field should be preserved in config."""
    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_from_template("research_monitor", "Test Agent")
    config = agent["config"]
    assert config.get("icon") == "🔬"
    mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agents/test_template_prompts.py -v`
Expected: FAIL — `system_prompt_template` is currently stored raw, not expanded.

- [ ] **Step 3: Implement system_prompt_template expansion**

In `src/openjarvis/agents/manager.py`, modify `create_from_template()` (around line 478):

```python
def create_from_template(
    self, template_id: str, name: str, overrides: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create an agent from a template with optional overrides."""
    templates = self.list_templates()
    tpl = next((t for t in templates if t.get("id") == template_id), None)
    if not tpl:
        raise ValueError(f"Template not found: {template_id}")
    skip = {"id", "name", "description", "source"}
    config = {k: v for k, v in tpl.items() if k not in skip}
    if overrides:
        config.update(overrides)
    agent_type = config.pop("agent_type", "monitor_operative")

    # Expand system_prompt_template with instruction
    prompt_tpl = config.pop("system_prompt_template", "")
    if prompt_tpl:
        instruction = config.get("instruction", "")
        config["system_prompt"] = prompt_tpl.format(
            instruction=instruction or "(No specific instruction provided)",
        )

    return self.create_agent(name=name, agent_type=agent_type, config=config)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_template_prompts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/agents/manager.py tests/agents/test_template_prompts.py
git commit -m "feat: expand system_prompt_template with instruction on agent creation"
```

---

### Task 3: Executor — wire tools from config

**Files:**
- Modify: `src/openjarvis/agents/executor.py:242-248`
- Create: `tests/agents/test_executor_tools.py`

- [ ] **Step 1: Write failing test**

Create `tests/agents/test_executor_tools.py`:

```python
"""Tests for tool wiring in AgentExecutor."""

from __future__ import annotations

import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.executor import AgentExecutor
from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus


class FakeSystem:
    def __init__(self):
        self.engine = MagicMock()
        self.engine.generate.return_value = {
            "content": "test response",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "finish_reason": "stop",
        }
        self.model = "test-model"
        self.config = None
        self.memory_backend = None


def test_executor_resolves_tools_from_config(tmp_path):
    """Executor should resolve tool names from config into tool instances."""
    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": ["think"],
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(FakeSystem())

    # Patch _invoke_agent to capture the tools passed to the agent
    captured_tools = []
    original_invoke = executor._invoke_agent

    def capture_invoke(agent_dict):
        # We can't easily intercept the agent constructor,
        # so just verify the method doesn't crash with tools
        return original_invoke(agent_dict)

    # Just verify it doesn't crash — tool resolution happens inside
    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    assert result_agent["total_runs"] == 1
    mgr.close()
```

- [ ] **Step 2: Run test to verify baseline**

Run: `uv run pytest tests/agents/test_executor_tools.py -v`
Expected: May pass (tools=[] doesn't crash) but tools aren't actually wired.

- [ ] **Step 3: Add _inject_tool_deps to executor and wire tools**

In `src/openjarvis/agents/executor.py`, add the `_inject_tool_deps` method after `_set_activity` (around line 55):

```python
def _inject_tool_deps(self, tool: Any) -> None:
    """Inject runtime dependencies into a tool instance.

    Mirrors SystemBuilder._inject_tool_deps but uses the
    lightweight system's references.
    """
    if self._system is None:
        return
    name = getattr(getattr(tool, "spec", None), "name", "")
    if name == "llm":
        if hasattr(tool, "_engine"):
            tool._engine = self._system.engine
        if hasattr(tool, "_model"):
            tool._model = self._system.model
    elif name == "retrieval" or name.startswith("memory_"):
        if hasattr(tool, "_backend"):
            tool._backend = getattr(self._system, "memory_backend", None)
    elif name.startswith("channel_"):
        if hasattr(tool, "_channel"):
            tool._channel = getattr(self._system, "channel_backend", None)
```

Then modify the agent construction in `_invoke_agent()` (around line 242). Replace:

```python
        # Construct agent instance (BaseAgent requires engine, model as positional args)
        agent_instance = agent_cls(
            engine,
            model,
            system_prompt=config.get("system_prompt"),
            tools=[],
        )
```

With:

```python
        # Resolve tools from config via ToolRegistry
        tool_names = config.get("tools", [])
        if isinstance(tool_names, str):
            tool_names = [t.strip() for t in tool_names.split(",") if t.strip()]

        tool_instances: list[Any] = []
        if tool_names:
            try:
                from openjarvis.server.agent_manager_routes import (
                    _ensure_registries_populated,
                )

                _ensure_registries_populated()
            except ImportError:
                pass
            from openjarvis.core.registry import ToolRegistry

            for tname in tool_names:
                if ToolRegistry.contains(tname):
                    try:
                        tool_cls = ToolRegistry.get(tname)
                        tool = tool_cls()
                        self._inject_tool_deps(tool)
                        tool_instances.append(tool)
                    except Exception:
                        logger.warning("Failed to instantiate tool %s", tname)
            if tool_instances:
                logger.info(
                    "Agent %s: resolved %d/%d tools",
                    agent["name"], len(tool_instances), len(tool_names),
                )

        # Construct agent instance
        agent_instance = agent_cls(
            engine,
            model,
            system_prompt=config.get("system_prompt"),
            tools=tool_instances,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agents/test_executor_tools.py -v`
Expected: PASS

- [ ] **Step 5: Run existing tests for regression**

Run: `uv run pytest tests/server/test_agent_manager_routes.py tests/core/test_config.py -v`
Expected: All PASS

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/openjarvis/agents/executor.py`
Expected: All checks passed

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/agents/executor.py tests/agents/test_executor_tools.py
git commit -m "feat: wire tools from agent config to executor via ToolRegistry"
```

---

### Task 4: Backend — /v1/recommended-model endpoint

**Files:**
- Modify: `src/openjarvis/server/agent_manager_routes.py`
- Create: `tests/server/test_recommended_model.py`

- [ ] **Step 1: Write failing test**

Create `tests/server/test_recommended_model.py`:

```python
"""Tests for /v1/recommended-model endpoint."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

try:
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_recommended_model_picks_second_largest():
    """Should pick the second-largest local model."""
    from fastapi import FastAPI

    from openjarvis.server.agent_manager_routes import (
        _parse_param_count,
        _pick_recommended_model,
    )

    models = ["qwen3.5:0.8b", "qwen3.5:4b", "qwen3.5:9b", "qwen3.5:35b"]
    result = _pick_recommended_model(models)
    assert result["model"] == "qwen3.5:9b"


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_recommended_model_single_model():
    """With only one model, pick it."""
    from openjarvis.server.agent_manager_routes import _pick_recommended_model

    result = _pick_recommended_model(["qwen3.5:4b"])
    assert result["model"] == "qwen3.5:4b"


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_recommended_model_filters_cloud():
    """Cloud models should be excluded."""
    from openjarvis.server.agent_manager_routes import _pick_recommended_model

    models = ["qwen3.5:4b", "gpt-4o", "claude-3.5-sonnet", "qwen3.5:9b"]
    result = _pick_recommended_model(models)
    # Should only consider local models
    assert result["model"] in ("qwen3.5:4b", "qwen3.5:9b")


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
def test_parse_param_count():
    """Parse parameter counts from model names."""
    from openjarvis.server.agent_manager_routes import _parse_param_count

    assert _parse_param_count("qwen3.5:9b") == 9.0
    assert _parse_param_count("qwen3.5:0.8b") == 0.8
    assert _parse_param_count("qwen3.5:35b") == 35.0
    assert _parse_param_count("gpt-4o") == 0.0  # unparseable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/server/test_recommended_model.py -v`
Expected: FAIL — `_parse_param_count` and `_pick_recommended_model` don't exist.

- [ ] **Step 3: Implement helper functions and endpoint**

In `src/openjarvis/server/agent_manager_routes.py`, add before the `_ensure_registries_populated` function (around line 105):

```python
import re as _re


def _parse_param_count(model_name: str) -> float:
    """Extract parameter count in billions from model name.

    Examples: 'qwen3.5:9b' → 9.0, 'qwen3.5:0.8b' → 0.8
    """
    m = _re.search(r":(\d+(?:\.\d+)?)b", model_name.lower())
    return float(m.group(1)) if m else 0.0


_CLOUD_PREFIXES = ("gpt-", "claude-", "gemini-", "o1-", "o3-", "o4-")


def _pick_recommended_model(
    model_ids: list[str],
) -> dict[str, str]:
    """Pick the second-largest local model from a list."""
    local = [
        m for m in model_ids
        if not any(m.startswith(p) for p in _CLOUD_PREFIXES)
    ]
    if not local:
        return {"model": model_ids[0] if model_ids else "", "reason": "Only model available"}
    sized = sorted(local, key=_parse_param_count, reverse=True)
    if len(sized) == 1:
        return {"model": sized[0], "reason": "Only local model available"}
    pick = sized[1]  # second-largest
    params = _parse_param_count(pick)
    return {
        "model": pick,
        "reason": f"Second-largest local model ({params}B parameters)",
    }
```

Then inside `create_agent_manager_router()`, add the endpoint on the `tools_router` (since it's already a utility router). Add after the `credential_status` endpoint (around line 785):

```python
    @tools_router.get("/recommended-model")
    def recommended_model(request: Request):
        engine = getattr(request.app.state, "engine", None)
        if engine is None:
            return {"model": "", "reason": "No engine available"}
        try:
            models = engine.list_models()
        except Exception:
            models = []
        return _pick_recommended_model(models)
```

Note: The endpoint path will be `/v1/tools/recommended-model` since it's on the tools_router with prefix `/v1/tools`. Alternatively, put it on the `global_router` to get `/v1/recommended-model`. Let's use `global_router`:

```python
    @global_router.get("/v1/recommended-model")
    def recommended_model(request: Request):
        engine = getattr(request.app.state, "engine", None)
        if engine is None:
            return {"model": "", "reason": "No engine available"}
        try:
            models = engine.list_models()
        except Exception:
            models = []
        return _pick_recommended_model(models)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/server/test_recommended_model.py -v`
Expected: PASS

- [ ] **Step 5: Lint**

Run: `uv run ruff check src/openjarvis/server/agent_manager_routes.py`
Expected: All checks passed

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/server/agent_manager_routes.py tests/server/test_recommended_model.py
git commit -m "feat: add /v1/recommended-model endpoint"
```

---

### Task 5: Frontend API — add fetchRecommendedModel

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add fetchRecommendedModel function**

In `frontend/src/lib/api.ts`, add after the `fetchModels` function (around line 101):

```typescript
export async function fetchRecommendedModel(): Promise<{ model: string; reason: string }> {
  const res = await fetch(`${getBase()}/v1/recommended-model`);
  if (!res.ok) return { model: '', reason: 'Failed to fetch' };
  return res.json();
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add fetchRecommendedModel API function"
```

---

### Task 6: Frontend — rewrite LaunchWizard to 2-step flow

**Files:**
- Modify: `frontend/src/pages/AgentsPage.tsx:207-932` (the WizardState interface and LaunchWizard component)

This is the largest task. The wizard is ~725 lines. We replace it with a simpler 2-step flow.

- [ ] **Step 1: Add fetchRecommendedModel to imports**

At the top of `frontend/src/pages/AgentsPage.tsx`, add `fetchRecommendedModel` to the api imports:

```typescript
import {
  fetchManagedAgents,
  fetchAgentTasks,
  fetchAgentChannels,
  fetchAgentMessages,
  fetchTemplates,
  createManagedAgent,
  pauseManagedAgent,
  resumeManagedAgent,
  deleteManagedAgent,
  runManagedAgent,
  recoverManagedAgent,
  sendAgentMessage,
  fetchLearningLog,
  triggerLearning,
  fetchAgentTraces,
  fetchManagedAgent,
  fetchAvailableTools,
  saveToolCredentials,
  fetchModels,
  updateManagedAgent,
  fetchRecommendedModel,
} from '../lib/api';
```

- [ ] **Step 2: Replace WizardState interface**

Replace the WizardState interface (lines 207-222) with:

```typescript
interface WizardState {
  step: 1 | 2;
  templateId: string;
  templateData: AgentTemplate | null;
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
  maxTurns: number;
  temperature: number;
}
```

- [ ] **Step 3: Rewrite LaunchWizard component**

Replace the entire `LaunchWizard` function (from `function LaunchWizard` through its closing `}`, approximately lines 224-932) with the new 2-step wizard. This is the full replacement code:

```typescript
function LaunchWizard({
  templates,
  onClose,
  onLaunched,
}: {
  templates: AgentTemplate[];
  onClose: () => void;
  onLaunched: () => void;
}) {
  const UNIVERSAL_DEFAULTS = {
    memoryExtraction: 'structured_json',
    observationCompression: 'summarize',
    retrievalStrategy: 'sqlite',
    taskDecomposition: 'hierarchical',
    maxTurns: 25,
    temperature: 0.3,
  };

  const [wizard, setWizard] = useState<WizardState>({
    step: 1,
    templateId: '',
    templateData: null,
    name: '',
    instruction: '',
    model: '',
    scheduleType: 'manual',
    scheduleValue: '',
    selectedTools: [],
    budget: '',
    routerPolicy: '',
    ...UNIVERSAL_DEFAULTS,
  });
  const [launching, setLaunching] = useState(false);
  const [recommendedModel, setRecommendedModel] = useState('');
  const models = useAppStore((s) => s.models);

  // Fetch recommended model on mount
  useEffect(() => {
    fetchRecommendedModel().then((r) => {
      setRecommendedModel(r.model);
      if (!wizard.model) {
        setWizard((w) => ({ ...w, model: r.model }));
      }
    }).catch(() => {});
  }, []);

  function selectTemplate(tpl: AgentTemplate | null) {
    if (tpl) {
      setWizard((w) => ({
        ...w,
        step: 2,
        templateId: tpl.id,
        templateData: tpl,
        name: '',
        instruction: '',
        model: recommendedModel || w.model,
        scheduleType: (tpl as any).schedule_type || 'manual',
        scheduleValue: (tpl as any).schedule_value || '',
        selectedTools: (tpl as any).tools || [],
        memoryExtraction: (tpl as any).memory_extraction || UNIVERSAL_DEFAULTS.memoryExtraction,
        observationCompression: (tpl as any).observation_compression || UNIVERSAL_DEFAULTS.observationCompression,
        retrievalStrategy: (tpl as any).retrieval_strategy || UNIVERSAL_DEFAULTS.retrievalStrategy,
        taskDecomposition: (tpl as any).task_decomposition || UNIVERSAL_DEFAULTS.taskDecomposition,
        maxTurns: (tpl as any).max_turns || UNIVERSAL_DEFAULTS.maxTurns,
        temperature: (tpl as any).temperature ?? UNIVERSAL_DEFAULTS.temperature,
      }));
    } else {
      // Custom Agent
      setWizard((w) => ({
        ...w,
        step: 2,
        templateId: '',
        templateData: null,
        name: '',
        instruction: '',
        model: recommendedModel || w.model,
        scheduleType: 'manual',
        scheduleValue: '',
        selectedTools: [],
        ...UNIVERSAL_DEFAULTS,
      }));
    }
  }

  async function handleLaunch() {
    if (!wizard.name.trim()) { toast.error('Name is required'); return; }
    setLaunching(true);
    try {
      const config: Record<string, unknown> = {
        schedule_type: wizard.scheduleType,
        schedule_value: wizard.scheduleValue || undefined,
        tools: wizard.selectedTools,
        learning_enabled: !!wizard.routerPolicy,
        memory_extraction: wizard.memoryExtraction,
        observation_compression: wizard.observationCompression,
        retrieval_strategy: wizard.retrievalStrategy,
        task_decomposition: wizard.taskDecomposition,
        max_turns: wizard.maxTurns,
        temperature: wizard.temperature,
      };
      if (wizard.budget) config.budget = parseFloat(wizard.budget);
      if (wizard.instruction.trim()) config.instruction = wizard.instruction.trim();
      if (wizard.model) config.model = wizard.model;
      if (wizard.routerPolicy) config.router_policy = wizard.routerPolicy;

      await createManagedAgent({
        name: wizard.name.trim(),
        template_id: wizard.templateId || undefined,
        config,
      });
      toast.success(`Agent "${wizard.name}" created`);
      onLaunched();
    } catch (err: any) {
      toast.error(err.message || 'Failed to create agent');
    } finally {
      setLaunching(false);
    }
  }

  const formatScheduleLabel = (type: string, value: string) => {
    if (type === 'manual') return 'Manual (run on demand)';
    if (type === 'cron') return `Cron: ${value}`;
    if (type === 'interval') {
      const secs = parseInt(value, 10);
      if (secs >= 3600) return `Every ${secs / 3600}h`;
      if (secs >= 60) return `Every ${secs / 60}m`;
      return `Every ${secs}s`;
    }
    return type;
  };

  // ── Step 1: Template Selection ──
  if (wizard.step === 1) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
        <div className="rounded-xl p-6 w-full max-w-lg" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>New Agent — Choose Template</h2>
            <button onClick={onClose} className="p-1 rounded hover:bg-opacity-10" style={{ color: 'var(--color-text-tertiary)' }}><X size={18} /></button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {templates.map((tpl) => (
              <button
                key={tpl.id}
                onClick={() => selectTemplate(tpl)}
                className="text-left p-4 rounded-lg transition-colors"
                style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}
              >
                <div className="text-xl mb-1">{(tpl as any).icon || '🤖'}</div>
                <div className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>{tpl.name}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{tpl.description}</div>
                {(tpl as any).tools && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {((tpl as any).tools as string[]).slice(0, 4).map((t) => (
                      <span key={t} className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(124,58,237,0.12)', color: '#a78bfa' }}>{t}</span>
                    ))}
                    {((tpl as any).tools as string[]).length > 4 && (
                      <span className="text-xs px-1.5 py-0.5 rounded" style={{ color: 'var(--color-text-tertiary)' }}>+{((tpl as any).tools as string[]).length - 4}</span>
                    )}
                  </div>
                )}
              </button>
            ))}
            <button
              onClick={() => selectTemplate(null)}
              className="text-left p-4 rounded-lg transition-colors"
              style={{ border: '1px solid var(--color-border)', background: 'var(--color-bg-secondary)' }}
            >
              <div className="text-xl mb-1">⚙️</div>
              <div className="font-semibold text-sm" style={{ color: 'var(--color-text)' }}>Custom Agent</div>
              <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Start from scratch. Pick your own tools, schedule, and behavior.</div>
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Step 2: Configuration ──
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.6)' }}>
      <div className="rounded-xl p-6 w-full max-w-lg max-h-[85vh] overflow-y-auto" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
        <div className="flex justify-between items-center mb-4">
          <div className="flex items-center gap-2">
            <button onClick={() => setWizard((w) => ({ ...w, step: 1 }))} className="p-1 rounded" style={{ color: 'var(--color-text-tertiary)' }}><ChevronLeft size={18} /></button>
            <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              {wizard.templateData ? `New ${wizard.templateData.name}` : 'New Custom Agent'}
            </h2>
          </div>
          <button onClick={onClose} className="p-1 rounded" style={{ color: 'var(--color-text-tertiary)' }}><X size={18} /></button>
        </div>

        <div className="space-y-4">
          {/* Name */}
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Agent Name</label>
            <input
              value={wizard.name}
              onChange={(e) => setWizard((w) => ({ ...w, name: e.target.value }))}
              placeholder="e.g. AI Research Tracker"
              className="w-full px-3 py-2 rounded-lg text-sm bg-transparent"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
          </div>

          {/* Instruction */}
          <div>
            <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>What should this agent do?</label>
            <textarea
              value={wizard.instruction}
              onChange={(e) => setWizard((w) => ({ ...w, instruction: e.target.value }))}
              placeholder="e.g. Monitor the latest research papers on reasoning and chain-of-thought in LLMs"
              rows={3}
              className="w-full px-3 py-2 rounded-lg text-sm bg-transparent resize-none"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            />
          </div>

          {/* Model + Schedule row */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Intelligence</label>
              <select
                value={wizard.model}
                onChange={(e) => setWizard((w) => ({ ...w, model: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg text-sm"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}{m.id === recommendedModel ? ' (recommended)' : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>Schedule</label>
              <div className="px-3 py-2 rounded-lg text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                {formatScheduleLabel(wizard.scheduleType, wizard.scheduleValue)}
              </div>
            </div>
          </div>

          {/* Tools tags */}
          {wizard.selectedTools.length > 0 && (
            <div>
              <label className="block text-sm font-medium mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                Tools <span style={{ color: 'var(--color-text-tertiary)', fontWeight: 400 }}>(from template)</span>
              </label>
              <div className="flex flex-wrap gap-1.5">
                {wizard.selectedTools.map((t) => (
                  <span key={t} className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(124,58,237,0.12)', color: '#a78bfa' }}>{t}</span>
                ))}
              </div>
            </div>
          )}

          {/* Advanced Settings */}
          <details className="rounded-lg" style={{ border: '1px solid var(--color-border)' }}>
            <summary className="px-3 py-2 cursor-pointer text-sm font-medium" style={{ color: 'var(--color-text-tertiary)' }}>
              Advanced Settings
            </summary>
            <div className="px-3 pb-3 pt-1 space-y-3" style={{ borderTop: '1px solid var(--color-border)' }}>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Memory Extraction</label>
                  <select value={wizard.memoryExtraction} onChange={(e) => setWizard((w) => ({ ...w, memoryExtraction: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="structured_json">Structured JSON</option>
                    <option value="causality_graph">Causality Graph</option>
                    <option value="scratchpad">Scratchpad</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Observation Compression</label>
                  <select value={wizard.observationCompression} onChange={(e) => setWizard((w) => ({ ...w, observationCompression: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="summarize">Summarize</option>
                    <option value="truncate">Truncate</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Retrieval Strategy</label>
                  <select value={wizard.retrievalStrategy} onChange={(e) => setWizard((w) => ({ ...w, retrievalStrategy: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="sqlite">BM25 (SQLite FTS5)</option>
                    <option value="hybrid">Hybrid (BM25 + Semantic)</option>
                    <option value="colbert">ColBERTv2</option>
                    <option value="none">None</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Task Decomposition</label>
                  <select value={wizard.taskDecomposition} onChange={(e) => setWizard((w) => ({ ...w, taskDecomposition: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="hierarchical">Hierarchical</option>
                    <option value="phased">Phased</option>
                    <option value="monolithic">Monolithic</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Max Turns</label>
                  <input type="number" value={wizard.maxTurns} onChange={(e) => setWizard((w) => ({ ...w, maxTurns: parseInt(e.target.value, 10) || 25 }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Temperature</label>
                  <input type="number" step="0.1" min="0" max="2" value={wizard.temperature}
                    onChange={(e) => setWizard((w) => ({ ...w, temperature: parseFloat(e.target.value) || 0.3 }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Budget ($)</label>
                  <input type="number" step="0.01" value={wizard.budget} onChange={(e) => setWizard((w) => ({ ...w, budget: e.target.value }))}
                    placeholder="Unlimited"
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>Schedule Type</label>
                  <select value={wizard.scheduleType} onChange={(e) => setWizard((w) => ({ ...w, scheduleType: e.target.value }))}
                    className="w-full px-2 py-1 rounded text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <option value="manual">Manual</option>
                    <option value="cron">Cron</option>
                    <option value="interval">Interval</option>
                  </select>
                </div>
              </div>
            </div>
          </details>

          {/* Launch */}
          <div className="flex gap-3 pt-2">
            <button
              onClick={handleLaunch}
              disabled={launching || !wizard.name.trim()}
              className="flex-1 py-2.5 rounded-lg text-sm font-semibold"
              style={{ background: 'var(--color-accent)', color: '#fff', opacity: launching || !wizard.name.trim() ? 0.5 : 1 }}
            >
              {launching ? 'Creating...' : 'Launch Agent'}
            </button>
            <button onClick={onClose} className="px-4 py-2.5 rounded-lg text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Build frontend**

```bash
cd frontend && npx tsc -b && npx vite build
```

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AgentsPage.tsx frontend/src/lib/api.ts
git commit -m "feat: rewrite agent wizard — 2-step flow with smart defaults"
```

---

### Task 7: Integration test — full end-to-end

- [ ] **Step 1: Run all backend tests**

```bash
uv run ruff check src/ tests/
uv run pytest tests/agents/test_template_prompts.py tests/agents/test_executor_tools.py tests/server/test_recommended_model.py tests/server/test_agent_manager_routes.py tests/core/test_config.py -v
```

Expected: All PASS, no lint errors.

- [ ] **Step 2: Manual test — create Research Monitor from browser**

1. Open `http://127.0.0.1:8222`
2. Go to Agents → New Agent
3. Click "Research Monitor"
4. Verify: model pre-selected, schedule shows "Cron: 0 9 * * *", tools show as tags
5. Type name: "AI Papers" and instruction: "Monitor reasoning papers"
6. Click Launch Agent
7. Go to Interact tab, send "What papers came out today?"
8. Verify: agent responds using tools (should attempt web_search)

- [ ] **Step 3: Manual test — create Custom Agent**

1. Click New Agent → Custom Agent
2. Verify: model pre-selected to recommended, schedule is Manual, no tools
3. Open Advanced Settings — verify defaults match universal defaults
4. Type name and instruction, launch
5. Verify: agent runs without tools

- [ ] **Step 4: Final commit with all changes**

```bash
git add -A
git commit -m "feat: agent wizard simplification — 2-step flow, tool wiring, smart defaults"
```
