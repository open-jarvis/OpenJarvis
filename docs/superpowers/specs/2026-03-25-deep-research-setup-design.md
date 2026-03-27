# Deep Research Setup Experience — Design Spec

**Date:** 2026-03-25
**Status:** Draft
**Scope:** End-to-end design for the OpenJarvis "killer install + setup" experience — from first launch to Deep Research over your personal data, accessible via desktop app, CLI, and messaging channels.

---

## 1. Vision

An Apple-like onboarding experience that connects users to their personal data (email, messaging, documents, calendar, contacts, notes), indexes it privately on-device, and provides a Deep Research agent that can navigate the full corpus with multi-hop retrieval — all accessible from the desktop app, CLI, or messaging channels like iMessage, WhatsApp, and Slack.

## 2. Architecture Overview

Seven layers from data sources to user interfaces:

```
Data Sources (12 services)
    ↓  OAuth / API / Local DB access
Connector Layer (native bulk sync + MCP real-time tools)
    ↓  Normalized Document objects
Ingestion Pipeline (normalize → deduplicate → chunk → index)
    ↓
On-Device Storage (SQLite/FTS5 + ColBERTv2 + attachment store)
    ↓
Multi-Layer Retrieval (BM25 recall → ColBERTv2 rerank → agent multi-hop)
    ↓
Deep Research Agent (ToolUsingAgent with knowledge_search, MCP tools, think, web_search)
    ↓
User Interfaces (Desktop App, CLI, iMessage, WhatsApp, Slack)
```

### Design Principles

- **Local-first:** All data stored on-device in SQLite. No cloud dependency for storage or retrieval.
- **Hybrid connectors:** Native bulk sync for initial ingest, MCP tools for real-time agent queries.
- **Two-stage retrieval:** BM25 for fast recall, ColBERTv2 for precise reranking. Agent adds multi-hop.
- **Progressive onboarding:** Pick sources → guided OAuth for each → bulk ingest → ready to research.
- **Escalation model:** Quick answers in chat channels, full reports in desktop app.

## 3. Data Sources

Twelve data sources across three categories:

| Category | Sources | Auth Type |
|----------|---------|-----------|
| **Communication** | Gmail, Slack, iMessage, WhatsApp | OAuth, OAuth, Local DB, Bridge (QR) |
| **Documents** | Google Drive, Dropbox, Notion | OAuth, OAuth, OAuth |
| **PIM** | Google Calendar, Google Contacts, Apple Notes, Obsidian/Markdown | OAuth, OAuth, Local DB, Filesystem |

## 4. Setup Wizard (Desktop-First)

The primary onboarding path is the Tauri desktop app. The CLI gets a simpler `jarvis connect` command that performs the same operations text-based. The desktop wizard is the "wow" experience — polished visual design with real product logos, clean progress bars, and premium feel throughout.

### Step 1: Welcome + Hardware Detection

Auto-detects CPU, RAM, GPU. Shows friendly capability messaging (e.g., "MacBook Pro M4 Max, 128GB RAM — you can run powerful local models"). Background: Ollama starts, recommended model begins downloading.

**Builds on:** Existing desktop boot sequence (Ollama → model → server) and `jarvis init` hardware detection.

**New:** Friendlier UI with hardware capability messaging, sets user expectations for what's possible on their machine.

### Step 2: Engine Setup

If Ollama is already installed, skip silently. If not, one-click install or "Use cloud instead" option. Model download with a polished progress bar. Option to add cloud API keys for hybrid local+cloud mode.

**Builds on:** Existing `jarvis init` engine selection and model download logic.

**New:** Automated Ollama install, cloud key entry UI, visual progress.

### Step 3: Pick Your Sources

A grid of source cards with product logos, grouped by category (Communication / Documents / PIM). User toggles on/off. "Connect what you want now — you can always add more later."

**Entirely new.** This step and everything after it is new functionality.

### Step 4: Connect Each Source (Guided)

For each selected source, one at a time, with a sidebar checklist showing connected/remaining status. "Skip" option for each. Four connection patterns:

**OAuth services** (Gmail, Drive, Slack, Calendar, Contacts, Dropbox, Notion): Show what permissions are requested and why → "Open in browser" button → OAuth consent screen → redirect back → green checkmark. OpenJarvis registers its own OAuth apps — users never create developer credentials.

**Local access** (iMessage, Apple Notes): Request macOS Full Disk Access permission → explain why in plain language → link to System Preferences → verify access was granted.

**Bridge services** (WhatsApp): Display QR code in the app → user scans with their phone → connection confirmed.

**Local files** (Obsidian/Markdown): File picker → select vault directory → confirm.

### Step 5: Ingest & Index

Bulk sync begins for all connected sources in parallel. Live dashboard shows per-source progress with item counts and progress bars:

```
✉  Gmail        12,847 / ~45,000 emails     ████████░░░░░░░  28%
💬 Slack         3,201 / ~8,500 messages     ██████████░░░░░  38%
📁 Google Drive  156 / ~420 docs             █████████░░░░░░  37%
📱 iMessage      ✓ Complete                  24,102 messages indexed
```

**Key UX:** User doesn't have to wait. They can start chatting with partial data — "Your data is still syncing, but you can start asking questions now." Ingest is resumable: close the app, come back later, it picks up where it left off.

### Step 6: Ready — First Query

Drops user into the Deep Research chat. Suggested starter queries based on their connected sources:
- "What were the key decisions from last week's team threads?"
- "Find the proposal doc Sarah shared about the Q3 roadmap"
- "Summarize my unread emails from today"

## 5. Connector Layer

### New Abstraction: `BaseConnector`

Lives in `src/openjarvis/connectors/` — separate from channels. Channels are for real-time communication (send/receive). Connectors are for data ingest (bulk download + index history).

```python
class BaseConnector(ABC):
    # Identity
    connector_id: str          # "gmail", "slack", etc.
    display_name: str          # "Gmail", "Slack", etc.
    icon_url: str              # Product logo for UI
    auth_type: str             # "oauth" | "local" | "bridge" | "filesystem"

    # Auth lifecycle
    def auth_url() -> str                    # OAuth: generate consent URL
    def handle_callback(code: str) -> None   # OAuth: exchange code for tokens
    def is_connected() -> bool
    def disconnect() -> None

    # Bulk sync (native)
    def sync(since: datetime | None) -> Iterator[Document]
    def sync_status() -> SyncStatus

    # MCP real-time (agent-callable)
    def mcp_tools() -> list[ToolSpec]
```

Registered via `@ConnectorRegistry.register("gmail")` — new registry alongside the existing ones.

### SyncStatus

```python
@dataclass
class SyncStatus:
    state: str          # "idle", "syncing", "paused", "error"
    items_synced: int   # items completed so far
    items_total: int    # estimated total (0 if unknown)
    last_sync: datetime | None
    cursor: str | None  # opaque checkpoint for resume
    error: str | None   # last error message if state == "error"
```

### Universal Document Schema

All connectors normalize their data into a common dataclass:

```python
@dataclass
class Document:
    doc_id: str              # globally unique (connector:source_id)
    source: str              # "gmail", "slack", "gdrive", etc.
    doc_type: str            # "email", "message", "document", "event", "contact", "note"
    content: str             # plain text body
    title: str               # subject line, filename, event title
    author: str              # sender / creator
    participants: list[str]  # recipients, channel members, attendees
    timestamp: datetime      # when created/sent
    thread_id: str | None    # conversation grouping
    url: str | None          # deep link back to original source
    attachments: list[Attachment]
    metadata: dict           # source-specific (labels, channel name, folder, etc.)
```

Six `doc_type` values: `email`, `message`, `document`, `event`, `contact`, `note`.

### Per-Connector Details

**Gmail** — Gmail API (REST). Scope: `gmail.readonly`. Bulk sync via `messages.list` → `messages.get`, paginated, resumable via `historyId`. MCP tools: `gmail_search_emails`, `gmail_get_thread`, `gmail_list_unread`.

**Slack** — Slack Web API. Scopes: `channels:history`, `channels:read`, `users:read`. Bulk sync via `conversations.history` per channel, cursor-paginated. MCP tools: `slack_search_messages`, `slack_get_thread`, `slack_list_channels`.

**iMessage** — Direct SQLite read of `~/Library/Messages/chat.db`. Requires macOS Full Disk Access. Bulk sync queries message + handle tables. MCP tools: `imessage_search_messages`, `imessage_get_conversation`.

**WhatsApp** — Baileys Node.js bridge (existing). Auth via QR code scan. Bulk sync via `fetchMessageHistory` through Baileys protocol. MCP tools: `whatsapp_search_messages`, `whatsapp_get_chat`.

**Google Drive** — Drive API v3. Scope: `drive.readonly`. Bulk sync via `files.list` → export/download. Google Docs/Sheets/Slides exported as text/markdown. MCP tools: `gdrive_search_files`, `gdrive_get_document`, `gdrive_list_recent`.

**Dropbox** — Dropbox API v2. Scopes: `files.metadata.read`, `files.content.read`. Bulk sync via `list_folder` recursive → download text-extractable files. MCP tools: `dropbox_search_files`, `dropbox_get_file`, `dropbox_list_recent`.

**Notion** — Notion API. Read content integration scope. Bulk sync via `search` → retrieve blocks → render to markdown. MCP tools: `notion_search_pages`, `notion_get_page`.

**Google Calendar** — Calendar API v3. Scope: `calendar.readonly`. Bulk sync via `events.list` across calendars, paginated. MCP tools: `calendar_get_events_today`, `calendar_search_events`, `calendar_next_meeting`.

**Google Contacts** — People API. Scope: `contacts.readonly`. Bulk sync via `people.connections.list`, paginated. MCP tools: `contacts_find`, `contacts_get_info`.

**Apple Notes** — Direct SQLite read of `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`. Requires Full Disk Access. Bulk sync decodes `ZICNOTEDATA` (gzipped HTML → plain text). MCP tools: `notes_search`, `notes_get_note`.

**Obsidian/Markdown** — Direct filesystem read of a user-selected vault directory. Bulk sync walks `.md` files, parses YAML frontmatter + wikilinks. MCP tools: `obsidian_search_notes`, `obsidian_get_note`, `obsidian_list_recent`.

### SyncEngine

A shared `SyncEngine` orchestrates all connectors:

- **Checkpoint/Resume:** Stores last sync cursor per connector in SQLite. Interrupted syncs resume from the checkpoint.
- **Rate Limiting:** Per-connector rate limits with exponential backoff. Respects API quotas (e.g., Gmail: 250 quota units/sec).
- **Incremental Sync:** After initial bulk sync, periodic delta sync fetches only new/modified items. Configurable interval.
- **Parallel Ingest:** Multiple connectors sync concurrently. Documents stream into the ingestion pipeline as they arrive.

## 6. Ingestion Pipeline

Four stages from raw documents to retrieval-ready index:

### Stage 1: Normalize

Connectors yield `Document` objects. HTML emails converted to plain text via `html2text`. Google Docs exported as markdown. Notion blocks rendered to markdown. Apple Notes decompressed from gzipped HTML to plain text. Attachments extracted, hashed (SHA-256), stored in content-addressed blob store.

### Stage 2: Deduplicate

Cross-source dedup by `doc_id` (connector:source_id). If the same message appears in a Slack export and an email notification, keep both but link them via metadata. Attachments deduped by SHA-256 — a file shared across Gmail, Slack, and Drive is stored once.

### Stage 3: Chunk

Uses the existing `chunking.py` infrastructure with type-aware strategies. **Chunk size defaults to the active reranker's max context:** 512 tokens when ColBERTv2 is available (its WordPiece max), 256 tokens when falling back to FAISS with `all-MiniLM-L6-v2`.

**Semantic splitting rules (never split mid-sentence):**

- **Emails/Messages:** Keep whole if under the chunk limit. For long threads, split on message/reply boundaries — never mid-message. If a single message exceeds the limit, fall back to sentence-boundary splitting.
- **Documents:** Split on section boundaries (`## Heading`) first, then paragraph boundaries within sections. If a single paragraph exceeds the limit, split on sentence boundaries. Each chunk inherits its section heading as metadata.
- **Events:** Single chunk per event (title + attendees + description + location). No splitting needed.
- **Contacts:** Single chunk per contact (name + email + phone + org + notes). Structured for entity lookup.
- **Notes:** Same rules as documents — section boundaries first, then paragraphs, then sentences.

**Metadata carries context:** Each chunk inherits the parent document's title, author, timestamp, source, and its section heading (if any), so retrieval results are never orphaned fragments with no context about where they came from.

### Stage 4: Index (Dual-Write)

Each chunk is written to both indexes simultaneously:

**SQLite + FTS5** — durable store with BM25 ranking. Rust-backed (existing infrastructure). Stores: chunk content, doc_id, source, doc_type, title, author, participants, timestamp, thread_id, url, metadata JSON, chunk_index.

**ColBERTv2 Index** — token-level embeddings for semantic reranking. **New: persisted to disk** (current implementation is in-memory). Memory-mapped tensor file with chunk_id→offset index. Append-only for incremental indexing. Lazy loading — only map pages touched by current query.

### SQLite Schema

Extends the existing `documents` table with source-aware columns:

```sql
CREATE TABLE documents (
    id            TEXT PRIMARY KEY,   -- chunk_id
    doc_id        TEXT NOT NULL,      -- parent document (connector:source_id)
    content       TEXT NOT NULL,      -- chunk text
    source        TEXT NOT NULL,      -- "gmail", "slack", "gdrive", ...
    doc_type      TEXT NOT NULL,      -- "email", "message", "document", ...
    title         TEXT,               -- subject / filename / event title
    author        TEXT,               -- sender / creator
    participants  TEXT,               -- JSON array
    timestamp     TEXT NOT NULL,      -- ISO 8601
    thread_id     TEXT,               -- conversation grouping
    url           TEXT,               -- deep link to original
    metadata      TEXT,               -- JSON (labels, channel, folder, etc.)
    chunk_index   INTEGER,            -- position within parent doc
    created_at    TEXT NOT NULL       -- when indexed
);

CREATE VIRTUAL TABLE documents_fts USING fts5(
    content, title, author,
    content=documents, content_rowid=rowid,
    tokenize='porter unicode61'
);

CREATE INDEX idx_source ON documents(source);
CREATE INDEX idx_doc_type ON documents(doc_type);
CREATE INDEX idx_author ON documents(author);
CREATE INDEX idx_timestamp ON documents(timestamp);
CREATE INDEX idx_thread ON documents(thread_id);
CREATE INDEX idx_doc_id ON documents(doc_id);
```

### ColBERTv2 Persistence (New)

The current ColBERT backend is in-memory only. For a personal knowledge base with 100K+ chunks, disk persistence is required.

- **On-disk format:** Memory-mapped tensor file + chunk_id→offset index. Lazy loading. Append-only for incremental indexing.
- **Fallback:** Systems without ColBERT dependencies (no torch) fall back to BM25 + FAISS (single-vector with `all-MiniLM-L6-v2`). The retrieval API is identical — callers don't know which reranker is active. When falling back to FAISS, chunk size adjusts to 256 tokens to match the embedding model's context.

### Attachment Store

Content-addressed blob store at `~/.openjarvis/blobs/{sha256[:2]}/{sha256}`. A metadata table tracks: hash, filename, mime_type, size_bytes, and source doc_ids.

Text extraction: PDFs via pdfplumber (existing). Office docs via python-docx/openpyxl. Images skipped for now (future: OCR). Extracted text gets chunked and indexed alongside the parent document.

## 7. Multi-Layer Retrieval

Two-stage retrieval as the base primitive, with agent-level multi-hop on top:

### Stage 1: BM25 Recall

FTS5 MATCH query with Porter stemming against the `documents_fts` virtual table. Returns top-100 candidates ranked by BM25. Supports pre-filtering by source, doc_type, author, and timestamp range via SQL WHERE clauses before the FTS5 MATCH.

### Stage 2: ColBERTv2 Rerank

The top-100 BM25 candidates are reranked using ColBERTv2 late interaction scoring (MaxSim). Returns top-K results (default K=10). This is where semantic understanding kicks in — ColBERT's token-level matching catches results that keyword search alone would miss or misrank.

### Stage 3: Agent Multi-Hop

The Deep Research agent can invoke the retrieval primitive (stages 1+2) multiple times across turns, refining its subqueries based on what it's found. Configurable max turns (default: 5 hops). The multi-hop logic lives at the agent level, not the retrieval level — clean separation of concerns.

## 8. Deep Research Agent

### Agent Configuration

```python
@AgentRegistry.register("deep_research")
class DeepResearchAgent(ToolUsingAgent):
    agent_id = "deep_research"
    # Default model: largest Qwen3.5 that fits locally, or cloud model if configured
    # Default max_turns: 5 (multi-hop research turns)
```

### Tool Belt

**`knowledge_search`** (core retrieval tool): BM25→ColBERT with filters: `query`, `source`, `doc_type`, `author`, `since`/`until`, `top_k`. Returns chunks with content, source, author, timestamp, url (deep link), relevance score.

**MCP connector tools** (real-time data access): Each connected source registers MCP tools. Agent can call these for fresh data not yet in the index — `gmail_search_emails`, `gmail_get_thread`, `slack_search_messages`, `gdrive_get_document`, `calendar_get_events`, `contacts_find`, etc.

**`think`** (reasoning scratchpad): Existing tool. The agent uses this between retrieval hops to synthesize findings and plan the next subquery. Critical for multi-hop research.

**`web_search`** (external supplement): Existing tool (DuckDuckGo or Tavily). When personal data references external context (a news article, a product, a company), the agent supplements with public web search.

### Multi-Hop Research Loop

Example for "What was the context around the Kubernetes migration decision?":

```
Turn 1: think → "I need to find discussions about K8s migration across email and Slack"
        knowledge_search(query="Kubernetes migration", top_k=10) → 8 results

Turn 2: think → "Found a Slack thread from March. Sarah and Mike debated cost. Get full thread + related docs"
        knowledge_search(query="Kubernetes cost analysis", author="sarah", doc_type="document") → 3 results
        slack_get_thread(thread_ts="1709234567.123") → full thread

Turn 3: think → "Sarah's doc references a meeting on March 5th. Check calendar + find the proposal"
        calendar_get_events(query="Kubernetes", since="2024-03-01") → 1 event
        knowledge_search(query="Kubernetes proposal", doc_type="document") → 2 results

Synthesize: Comprehensive report with cross-platform citations + deep links
```

### Output Format

Structured research report with:
- Narrative synthesis of findings
- Inline citations as clickable deep links back to the original source (Slack thread, Gmail message, Drive doc, Calendar event)
- Source list at the bottom with platform, title, author, and date

### Conversational Follow-up

After the initial report, the user can drill deeper or pivot:
- "Show me just Mike's cost concerns in detail" → new retrieval, focused summary
- "Draft a summary of this for my manager" → uses conversation context, no new retrieval needed
- "What happened after the decision?" → new time-scoped retrieval

## 9. Channel Plugins

### ChannelAgent

A lightweight layer between existing channel transports and the Deep Research Agent. Classifies incoming queries automatically and routes them — the user never specifies "quick" or "deep."

**Classification is automatic** based on query analysis:
- **Quick signals:** Single entity lookup, starts with "when"/"where"/"find", short query (<20 words), mentions a specific person/file/event.
- **Deep signals:** "summarize", "research", "what was the context", time ranges ("last month"), multi-entity queries.
- **Adaptive:** If the agent starts down the quick path but realizes mid-retrieval it needs more hops, it escalates on the fly.

### Quick Path (Answer Inline)

Simple lookups answered in a single retrieval hop that fit in a chat message:

```
User: When's my next meeting with Sarah?
Jarvis: Tomorrow at 2pm — "Q3 Planning Sync" with Sarah Chen, Mike Ross, and you.
        Google Meet link: meet.google.com/abc-defg-hij
```

### Deep Path (Escalate to Desktop)

Complex queries requiring multi-hop retrieval or long-form output:

```
User: What was the full context behind the decision to switch to Kubernetes?
Jarvis: That's a complex question spanning multiple sources — I found relevant threads
        in Slack, emails from Sarah and Mike, and a proposal doc in Drive.
        I'm preparing a full research report for you.
        📄 Open full report in OpenJarvis → openjarvis://research/{session_id}
```

Escalation flow:
1. Agent kicks off multi-hop research in the background (doesn't block the chat)
2. Sends brief preview + escalation link in the chat channel
3. When report is ready, sends follow-up notification: "Your report is ready"
4. Deep link (`openjarvis://research/{session_id}`) opens desktop app directly to the research session — Tauri registers as URL handler

### Per-Channel Implementation

**iMessage:** BlueBubbles bridge. Currently send-only — needs incoming message support added. Plain text + URL only. Escalation via `openjarvis://` deep link.

**WhatsApp:** Baileys bridge (existing, already bidirectional). Supports WhatsApp markdown (*bold*, _italic_). Escalation via deep link (WhatsApp renders URLs as tappable).

**Slack:** Socket Mode (existing, already bidirectional). Can use Block Kit for richer formatting — bullet lists, bold, links, buttons. DM the Jarvis bot or @mention in a channel.

### Shared Auth

For WhatsApp and Slack, the data connector and channel plugin share the same authentication. Connecting Slack as a data source automatically enables the Slack channel plugin. One OAuth flow, two capabilities. Channel plugins are configured from a "Connected Apps" settings page after initial setup.

## 10. CLI: `jarvis connect`

The CLI equivalent of the desktop setup wizard. Simpler, text-based, but same underlying logic:

```bash
jarvis connect                    # Interactive: pick sources, walk through auth
jarvis connect gmail              # Connect a specific source
jarvis connect --list             # Show connected sources and sync status
jarvis connect --sync             # Trigger incremental sync for all sources
jarvis connect --disconnect gmail # Disconnect a source
```

OAuth flows open the system browser for consent, then listen on a localhost callback URL. Local access (iMessage, Apple Notes) checks permissions and provides instructions. Filesystem sources (Obsidian) accept a path argument.

## 11. Implementation Phases

### Phase 1: Connector Foundation + Gmail + Obsidian
- `BaseConnector` ABC and `ConnectorRegistry`
- `Document` schema and `SyncEngine` (checkpoint/resume, rate limiting)
- Gmail connector (OAuth flow + bulk sync + MCP tools)
- Obsidian/Markdown connector (filesystem, simplest possible)
- Extended SQLite schema with source-aware columns
- `knowledge_search` tool with filtered BM25 retrieval
- CLI `jarvis connect` command
- Tests for all of the above

### Phase 2: Desktop Wizard + More Connectors
- Desktop setup wizard UI (Steps 1-6) with product logos, progress bars, polished design
- Slack connector
- Google Drive connector
- Google Calendar + Contacts connectors
- iMessage connector (macOS local DB access)
- Parallel ingest dashboard in desktop UI

### Phase 3: ColBERTv2 Persistence + Deep Research Agent
- ColBERTv2 on-disk persistence (memory-mapped tensors)
- Two-stage retrieval (BM25 recall → ColBERT rerank)
- `DeepResearchAgent` with multi-hop loop
- Research report output with inline citations and deep links
- Conversational follow-up support
- Desktop app research UI (report rendering, source panel)

### Phase 4: Channel Plugins + Remaining Connectors
- `ChannelAgent` with automatic quick/deep classification
- iMessage channel plugin (add incoming message support to BlueBubbles)
- WhatsApp channel plugin (leverage existing Baileys bridge)
- Slack channel plugin (leverage existing Socket Mode)
- `openjarvis://` URL handler registration in Tauri
- Remaining connectors: WhatsApp, Dropbox, Notion, Apple Notes

### Phase 5: Polish + Incremental Sync
- Incremental delta sync for all connectors
- Attachment store with content-addressed dedup and text extraction
- Desktop "Connected Apps" settings page (manage sources post-setup)
- Sync status dashboard (last sync time, item counts, errors)
- Error handling and retry UX across all connectors
