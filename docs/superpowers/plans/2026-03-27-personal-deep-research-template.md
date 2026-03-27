# Personal DeepResearch Template + Server Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register "Personal Deep Research" as a default agent template, wire DeepResearch tools in the server streaming endpoint, and add a `jarvis research` CLI alias — so users can create and chat with the agent from the desktop app, browser, or CLI.

**Architecture:** A new TOML template file auto-discovered by `AgentManager.list_templates()`. The server's `_stream_managed_agent()` is extended to build the 4 DeepResearch tools (knowledge_search, knowledge_sql, scan_chunks, think) from `~/.openjarvis/knowledge.db` when `agent_type == "deep_research"`. A CLI alias `jarvis research` wraps the existing `deep-research-setup` command.

**Tech Stack:** Python 3.10+, TOML, FastAPI, Click, pytest

---

### Task 1: Create the agent template TOML

**Files:**
- Create: `src/openjarvis/agents/templates/personal_deep_research.toml`

- [ ] **Step 1: Create the template file**

Create `src/openjarvis/agents/templates/personal_deep_research.toml`:

```toml
[template]
id = "personal_deep_research"
name = "Personal Deep Research"
description = "Search across your emails, messages, meeting notes, and documents with multi-hop retrieval and cited reports. Uses BM25 keyword search, SQL aggregation, and LM-powered semantic scanning."
agent_type = "deep_research"
schedule_type = "manual"
tools = ["knowledge_search", "knowledge_sql", "scan_chunks", "think"]
max_turns = 8
temperature = 0.3
max_tokens = 4096
```

- [ ] **Step 2: Verify template is discovered**

```bash
uv run python3 -c "
from openjarvis.agents.manager import AgentManager
templates = AgentManager.list_templates()
ids = [t['id'] for t in templates]
print(f'Templates: {ids}')
assert 'personal_deep_research' in ids, 'Template not found!'
t = next(t for t in templates if t['id'] == 'personal_deep_research')
print(f'Name: {t[\"name\"]}')
print(f'Agent type: {t[\"agent_type\"]}')
print(f'Tools: {t.get(\"tools\", [])}')
print('PASS')
"
```

Expected: Template found with correct fields.

- [ ] **Step 3: Commit**

```bash
git add src/openjarvis/agents/templates/personal_deep_research.toml
git commit -m "feat: add Personal Deep Research agent template"
```

---

### Task 2: Wire DeepResearch tools in server streaming endpoint

**Files:**
- Modify: `src/openjarvis/server/agent_manager_routes.py` (lines 263-266)
- Create: `tests/server/test_deep_research_tools_wiring.py`

- [ ] **Step 1: Write the test**

Create `tests/server/test_deep_research_tools_wiring.py`:

```python
"""Test that _stream_managed_agent wires DeepResearch tools correctly."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_deep_research_agent_gets_tools(tmp_path: Path) -> None:
    """When agent_type is deep_research, agent receives 4 tools."""
    from openjarvis.connectors.store import KnowledgeStore

    # Create a knowledge store with some data
    db_path = tmp_path / "knowledge.db"
    store = KnowledgeStore(str(db_path))
    store.store("test content", source="test", doc_type="note")

    from openjarvis.server.agent_manager_routes import _build_deep_research_tools

    tools = _build_deep_research_tools(
        engine=MagicMock(),
        model="test-model",
        knowledge_db_path=str(db_path),
    )

    tool_ids = [t.tool_id for t in tools]
    assert "knowledge_search" in tool_ids
    assert "knowledge_sql" in tool_ids
    assert "scan_chunks" in tool_ids
    assert "think" in tool_ids
    assert len(tools) == 4
    store.close()


def test_deep_research_tools_returns_empty_when_no_db() -> None:
    """When knowledge.db doesn't exist, returns empty list."""
    from openjarvis.server.agent_manager_routes import _build_deep_research_tools

    tools = _build_deep_research_tools(
        engine=MagicMock(),
        model="test-model",
        knowledge_db_path="/nonexistent/path/knowledge.db",
    )

    assert tools == []
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/server/test_deep_research_tools_wiring.py -v --tb=short
```

Expected: FAIL — `ImportError: cannot import name '_build_deep_research_tools'`

- [ ] **Step 3: Add `_build_deep_research_tools` function to agent_manager_routes.py**

Add this function near the top of the file (after the imports, before the router definitions):

```python
def _build_deep_research_tools(
    engine: Any,
    model: str,
    knowledge_db_path: str = "",
) -> list:
    """Build the 4 DeepResearch tools from a KnowledgeStore.

    Returns an empty list if the knowledge DB does not exist.
    """
    from pathlib import Path

    if not knowledge_db_path:
        from openjarvis.core.config import DEFAULT_CONFIG_DIR
        knowledge_db_path = str(DEFAULT_CONFIG_DIR / "knowledge.db")

    if not Path(knowledge_db_path).exists():
        return []

    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    store = KnowledgeStore(knowledge_db_path)
    retriever = TwoStageRetriever(store)
    return [
        KnowledgeSearchTool(retriever=retriever),
        KnowledgeSQLTool(store=store),
        ScanChunksTool(store=store, engine=engine, model=model),
        ThinkTool(),
    ]
```

- [ ] **Step 4: Wire the tools into `_stream_managed_agent`**

In `_stream_managed_agent()`, add tool wiring between the config extraction (line ~263) and the agent instantiation (line ~265). Insert after `if config.get("max_turns") is not None:` block:

```python
    # Build DeepResearch tools when applicable
    if agent_type == "deep_research":
        tools = _build_deep_research_tools(engine=engine, model=model)
        if tools:
            agent_kwargs["tools"] = tools
```

- [ ] **Step 5: Ensure tests/server/__init__.py exists**

```bash
touch tests/server/__init__.py
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/server/test_deep_research_tools_wiring.py -v --tb=short
```

Expected: 2/2 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/openjarvis/server/agent_manager_routes.py tests/server/__init__.py tests/server/test_deep_research_tools_wiring.py
git commit -m "feat: wire DeepResearch tools in managed agent streaming endpoint"
```

---

### Task 3: Add `jarvis research` CLI alias

**Files:**
- Modify: `src/openjarvis/cli/__init__.py`

- [ ] **Step 1: Add the alias**

In `src/openjarvis/cli/__init__.py`, find the line that registers `deep-research-setup` (should look like `cli.add_command(deep_research_setup, "deep-research-setup")`). Add the alias right after:

```python
cli.add_command(deep_research_setup, "research")
```

This registers the same command under the shorter name `research`.

- [ ] **Step 2: Verify**

```bash
uv run jarvis research --help | head -5
```

Expected: Shows the same help as `jarvis deep-research-setup --help`.

- [ ] **Step 3: Commit**

```bash
git add src/openjarvis/cli/__init__.py
git commit -m "feat: add 'jarvis research' CLI alias for deep-research-setup"
```

---

### Task 4: End-to-end test — template in Agents tab via API

**Files:** None (manual testing via API)

- [ ] **Step 1: Start the server**

```bash
uv run jarvis serve --host 127.0.0.1 --port 8000 &
sleep 3
```

- [ ] **Step 2: Verify template appears**

```bash
curl -s http://localhost:8000/v1/templates | python3 -c "
import sys, json
data = json.load(sys.stdin)
ids = [t['id'] for t in data['templates']]
print(f'Templates: {ids}')
assert 'personal_deep_research' in ids
print('PASS: template found')
"
```

- [ ] **Step 3: Create agent from template**

```bash
curl -s -X POST http://localhost:8000/v1/managed-agents \
  -H 'Content-Type: application/json' \
  -d '{"name": "My Research Agent", "template_id": "personal_deep_research"}' \
  | python3 -c "
import sys, json
agent = json.load(sys.stdin)
print(f'Agent created: {agent[\"id\"]}')
print(f'Type: {agent[\"agent_type\"]}')
print(f'Status: {agent[\"status\"]}')
print(f'Config tools: {agent.get(\"config\", {}).get(\"tools\", [])}')
"
```

Expected: Agent created with `agent_type: deep_research`.

- [ ] **Step 4: Send a message and verify streaming**

```bash
AGENT_ID=$(curl -s http://localhost:8000/v1/managed-agents | python3 -c "
import sys, json
agents = json.load(sys.stdin)['agents']
dr = [a for a in agents if a['agent_type'] == 'deep_research']
print(dr[0]['id'] if dr else '')
")

curl -s -X POST "http://localhost:8000/v1/managed-agents/${AGENT_ID}/messages" \
  -H 'Content-Type: application/json' \
  -d '{"content": "Who are the 5 people I message the most?", "stream": true}' \
  --no-buffer | head -20
```

Expected: SSE chunks streaming with agent response including tool call results.

- [ ] **Step 5: Stop server and push**

```bash
kill %1
git push origin feat/deep-research-setup
```

---

### Task 5: Update PR #78 title and description

**Files:** None (GitHub CLI)

- [ ] **Step 1: Update PR title and body**

```bash
gh pr edit 78 --repo open-jarvis/OpenJarvis \
  --title "feat: Personal Deep Research — connectors, retrieval, agent, channels, desktop" \
  --body "$(cat <<'PREOF'
## Summary

Full Deep Research experience: connect personal data sources → ingest → multi-hop retrieval → cited research reports via desktop app, browser, CLI, or iMessage.

### What's built
- **13 connectors**: Gmail IMAP, Outlook, Obsidian, Apple Notes, iMessage, Slack, Notion, Granola, Google Drive*, Calendar*, Contacts*, Dropbox*, WhatsApp*
- **Ingestion pipeline**: SemanticChunker, KnowledgeStore (FTS5/BM25), incremental sync, attachment store
- **4 agent tools**: knowledge_search (BM25), knowledge_sql (SQL aggregation), scan_chunks (LM semantic grep), think (reasoning)
- **DeepResearchAgent**: multi-hop with query expansion, forced synthesis, cited reports
- **Agent template**: "Personal Deep Research" in Agents tab — create and chat via desktop/browser
- **CLI**: `jarvis deep-research-setup` / `jarvis research` — auto-detect sources, ingest, chat
- **API**: 6 connector endpoints + managed agent streaming
- **Channel gateway**: ChannelBridge, webhook routes for Twilio/BlueBubbles/WhatsApp
- **220+ tests**

*\* = mocked tests only*

### Live-verified with real data
- 55,302 chunks (Apple Notes + iMessage + Gmail + Slack + Notion + Granola)
- DeepResearchAgent with Qwen3.5 35B MoE producing cited reports
- Cross-source queries: found Spain trip dates from iMessages, ranked top contacts via SQL, identified recurring meetings from Granola

## Test plan
- [ ] `uv run pytest tests/ -v` — all tests pass
- [ ] `uv run jarvis research` — end-to-end CLI flow
- [ ] Create agent from template in Agents tab
- [ ] Stream chat response with tool calls
- [ ] Verify read-only: no writes to any connector

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PREOF
)"
```

- [ ] **Step 2: Push our branch to the PR branch**

```bash
git push origin feat/deep-research-setup:feat/mobile-channel-gateway --force-with-lease
```
