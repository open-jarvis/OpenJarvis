# Personal DeepResearch Agent Template — Desktop + Browser + CLI

## Goal

Register "Personal Deep Research" as a default agent template so users can create it from the Agents tab in the desktop/browser app, chat with it via streaming SSE, and use it from the CLI. All read-only — no writes to any connector.

## Scope

**In scope:**
- New template TOML: `personal_deep_research.toml`
- Wire DeepResearch tools in `_stream_managed_agent()` when `agent_type == "deep_research"`
- Ensure KnowledgeStore at `~/.openjarvis/knowledge.db` is loaded when the agent runs
- Verify end-to-end: create from template in Agents tab → send message → get streamed cited report

**Out of scope:**
- Google OAuth (Sub-project 2)
- Channel listeners (Sub-project 3)
- New frontend components (existing Agents tab + chat UI work as-is)

## Architecture

### Template File

`src/openjarvis/agents/templates/personal_deep_research.toml`:

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

This is auto-discovered by `AgentManager.list_templates()` and appears in the Agents tab wizard alongside the existing templates (code_reviewer, inbox_triager, research_monitor).

### Server-Side Tool Wiring

In `_stream_managed_agent()` (agent_manager_routes.py), when the agent type is `deep_research`, build the tools from the shared KnowledgeStore:

```python
if agent_record["agent_type"] == "deep_research":
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.connectors.retriever import TwoStageRetriever
    from openjarvis.tools.knowledge_search import KnowledgeSearchTool
    from openjarvis.tools.knowledge_sql import KnowledgeSQLTool
    from openjarvis.tools.scan_chunks import ScanChunksTool
    from openjarvis.tools.think import ThinkTool

    store = KnowledgeStore()  # defaults to ~/.openjarvis/knowledge.db
    retriever = TwoStageRetriever(store)
    model = agent_record.get("config", {}).get("model") or engine_model
    tools = [
        KnowledgeSearchTool(retriever=retriever),
        KnowledgeSQLTool(store=store),
        ScanChunksTool(store=store, engine=engine, model=model),
        ThinkTool(),
    ]
```

These tools are passed to `DeepResearchAgent(engine=engine, model=model, tools=tools)` when instantiating the agent for this request.

### Flow

```
User clicks "Personal Deep Research" template in Agents tab
  → POST /v1/managed-agents {template_id: "personal_deep_research", name: "My Research"}
  → AgentManager.create_from_template() → stores agent record in SQLite

User types question in chat
  → POST /v1/managed-agents/{id}/messages {content: "...", stream: true}
  → _stream_managed_agent() detects agent_type == "deep_research"
  → Builds 4 tools from KnowledgeStore
  → Instantiates DeepResearchAgent with tools
  → agent.run(query) → multi-hop tool calls
  → Streams response as SSE word-by-word
  → Frontend renders streamed markdown with citations
```

### CLI Alias

Add `jarvis research` as a convenience alias that runs `jarvis deep-research-setup`. Same behavior, shorter command.

### Multi-Channel Messaging — iMessage, Slack, WhatsApp, SMS

Users can message their DeepResearch agent from their phone via iMessage, Slack, WhatsApp, or SMS. This builds on the `ChannelBridge` + webhook architecture from PR #78 (open-jarvis/OpenJarvis#78).

**Three options for iMessage (user picks during setup):**

1. **AppleScript daemon (free, no external services)** — Background daemon on the Mac polls `chat.db` for new messages in a designated conversation, routes to agent, responds via AppleScript. Requires Mac to be running.

2. **BlueBubbles (free, self-hosted)** — Install BlueBubbles on the Mac, which provides a REST API + webhook for iMessage. PR #78 already has webhook handler at `/webhooks/bluebubbles`. More reliable than AppleScript, supports media.

3. **Sendblue (paid cloud API)** — Cloud iMessage API, no Mac required for sending. Works from any server. Costs money but no local dependencies. We'd add a Sendblue webhook handler alongside the existing BlueBubbles one.

**Architecture (from PR #78):**

```
Phone sends message
  → Webhook hits /webhooks/{twilio|bluebubbles|whatsapp}
  → ChannelBridge.handle_incoming(sender, content, channel_type)
  → SessionStore tracks per-sender conversation
  → Routes to DeepResearchAgent.run(query)
  → Response sent back via channel adapter (same channel)
```

For the AppleScript daemon (option 1), the flow is:
```
iPhone sends iMessage → Mac Messages.app → chat.db
  → iMessageDaemon polls chat.db (read-only)
  → ChannelBridge.handle_incoming(sender, content, "imessage")
  → DeepResearchAgent.run(query)
  → AppleScript sends response via Messages.app
  → Response appears on iPhone
```

**What we build (from PR #78 + new):**
- Merge/rebase PR #78's `ChannelBridge`, `SessionStore`, `webhook_routes`, `auth_middleware`
- Add AppleScript-based iMessage daemon as an alternative to BlueBubbles
- Add `jarvis channels setup` CLI command to configure channel(s)
- Add `jarvis channels start` / `stop` / `status` for daemon lifecycle
- Wire `ChannelBridge` to route to DeepResearchAgent instead of generic `JarvisSystem.ask()`

**Finding the agent address (shown in CLI + Desktop + Browser):**

| Channel | How user finds the address |
|---------|---------------------------|
| iMessage (AppleScript) | `jarvis channels status` → "iMessage: listening on [chat name]" |
| iMessage (BlueBubbles) | `jarvis channels status` → "iMessage: via BlueBubbles at [url]" |
| Slack | Agent detail → Channels tab → shows Slack workspace + channel |
| WhatsApp | Agent detail → Channels tab → shows WhatsApp number |
| SMS (Twilio) | Agent detail → Channels tab → shows Twilio phone number |

**Read-only guarantee:** All channel adapters only READ incoming messages and SEND responses. No channel adapter modifies, deletes, or marks messages as read. The iMessage daemon reads chat.db in read-only mode (`?mode=ro`). Responses go through Messages.app (AppleScript) or BlueBubbles API, not by writing to chat.db.

## What Does NOT Change

- Frontend Agents tab UI (already supports templates)
- Frontend chat components (already support SSE streaming)
- Agent CRUD endpoints (already work)
- DeepResearchAgent class (already has all 4 tools + prompt)
- KnowledgeStore / ingestion pipeline (already populated)
- iMessage connector (read-only data source — separate from the iMessage agent channel)

## Test Plan

- Template appears in `GET /v1/templates` response
- Creating from template succeeds via `POST /v1/managed-agents`
- Sending a message with `stream: true` returns SSE chunks
- Agent uses knowledge_search/knowledge_sql/scan_chunks/think tools
- Response includes citations
- `jarvis research` CLI alias works
- iMessage daemon detects new messages in designated chat
- iMessage daemon sends response via AppleScript
- `jarvis channels status` shows correct state per channel
- ChannelBridge routes incoming webhook to DeepResearchAgent
- Webhook endpoints return correct HTTP responses (TwiML for Twilio, 200 for BlueBubbles/WhatsApp)
- SessionStore tracks per-sender conversations across channels
