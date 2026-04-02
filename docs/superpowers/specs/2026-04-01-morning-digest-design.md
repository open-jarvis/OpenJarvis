# Morning Digest with Jarvis Voice — Design Spec

**Date:** 2026-04-01
**Author:** Jon Saad-Falcon
**Status:** Draft

## Overview

A "Deep Research / Morning Digest" feature for OpenJarvis that pre-computes a personalized daily briefing from multiple data sources and delivers it with a configurable AI voice (default: Jarvis from Iron Man). The digest is scheduled to run automatically (e.g., 6am) but only delivered when the user explicitly triggers it — instant when you're ready, never interrupting before you are.

This is a standard OpenJarvis config using all five primitives: Intelligence, Engine, Agent, Tools, and Learning.

## Goals

1. **Killer first use case** for OpenJarvis — a daily briefing that feels like having a personal AI assistant
2. **Config-driven and extensible** — new data sources and digest sections added without touching agent code
3. **Voice-first with text companion** — audio narration with Jarvis persona + formatted text
4. **On-device where possible** — Cartesia for fast local TTS, local models for synthesis

## Non-Goals

- Real-time voice conversation (future work)
- Push notifications / unsolicited delivery
- Mobile app (v1 targets CLI + frontend/desktop app)

## Constraints

- **Target audio duration:** 2-5 minutes for a full digest narration
- **Apple Health:** No direct API; requires HealthKit Shortcut export or XML parse (see Connectors section)
- **Staleness:** A cached digest is "fresh" if generated on the same calendar day in the configured timezone

---

## Architecture

### Approach: Agent + Pipeline Hybrid

The `MorningDigestAgent` is a thin orchestrator that delegates to pipeline-stage tools: `digest_collect` (fetches data from sources), LLM synthesis (narrative generation), and `text_to_speech` (audio). The agent's system prompt controls personality and section ordering. Each tool is independently registered and testable.

This maps cleanly to the existing OpenJarvis architecture (registry pattern, agent + tools), gives clear work boundaries (each connector and tool is a self-contained unit), and keeps personality/voice/sections all configurable without touching code.

### Data Flow & Lifecycle

**Phase 1 — Pre-compute (scheduled, e.g., 6am)**

```
AgentScheduler (cron trigger)
  -> MorningDigestAgent.run()
    -> digest_collect tool (calls connectors: Gmail, Slack, Oura, Calendar, etc.)
    -> web_search tool (news, weather, Arxiv)
    -> LLM synthesis (narrative with Jarvis persona)
    -> text_to_speech tool (generates audio from narrative)
    -> Stores result as DigestArtifact in DigestStore
```

**Phase 2 — Hold (waits for user trigger)**

```
DigestStore holds the latest artifact:
  - text: structured markdown per section
  - audio: mp3/wav file path
  - metadata: timestamp, sources used, section summaries
  - staleness: artifact is "fresh" if generated today (same calendar day in
    configured timezone). Otherwise stale and re-generated on demand.
```

**Phase 3 — Deliver (user-triggered)**

```
User says "Good morning Jarvis" or runs `jarvis digest`
  -> System checks DigestStore for today's pre-computed artifact
    -> If fresh: deliver immediately (text + audio playback)
    -> If stale/missing: run Phase 1 on-demand, then deliver

CLI: prints formatted text + plays audio simultaneously
Frontend/Desktop: renders text in chat + plays audio in browser/Tauri
```

The agent does the heavy lifting once. Delivery is just reading from a cache. If the user never triggers it, nothing is wasted except compute.

---

## New MCP Connectors

> **Implementation note:** All MCP connectors below must be created and tested with real data from actual API accounts. This should be a **separate initial PR** before any digest agent work builds on top.

Each connector follows the existing `BaseConnector` pattern with `@ConnectorRegistry.register()`. They sync data into the `KnowledgeStore` so the digest agent can query them uniformly.

### Connector Interface

```python
@ConnectorRegistry.register("oura")
class OuraConnector(BaseConnector):
    def sync(self) -> List[Document]                          # Full sync
    def fetch_recent(self, since: datetime) -> List[Document] # For digest
    def list_sync_sources(self) -> dict                       # Metadata
```

The digest agent calls `fetch_recent(since=yesterday)` across all enabled connectors to get fresh data without a full re-sync.

### Health & Fitness

| Connector | API | Auth | Data Fetched |
|-----------|-----|------|--------------|
| `oura` | Oura Ring REST API v2 | OAuth2 | Sleep score, readiness, HRV, body temp, activity |
| `apple_health` | Apple Health export (XML) or HealthKit via Shortcut | Local file / Shortcut | Steps, heart rate, workouts, stand hours |
| `strava` | Strava REST API v3 | OAuth2 | Recent activities, distance, pace, PRs |

**Apple Watch / Apple Health note:** There is no direct API for Apple Watch data. Apple Health is the unified source — data flows Apple Watch -> Apple Health automatically. Implementation options: (1) HealthKit Shortcut that exports JSON to a known path, or (2) parse the Apple Health XML export. This is a known constraint.

### Music & Entertainment

| Connector | API | Auth | Data Fetched |
|-----------|-----|------|--------------|
| `spotify` | Spotify Web API | OAuth2 | Recently played, top tracks, currently playing |
| `apple_music` | Apple Music API | Developer token + MUT | Recently played, library stats |
| `soundcloud` | SoundCloud API | OAuth2 | Likes, reposts, recent plays |

### Productivity

| Connector | API | Auth | Data Fetched |
|-----------|-----|------|--------------|
| `google_tasks` | Google Tasks API v1 | OAuth2 | Tasks due today, overdue, recently completed |

### v1 Priority

**Primary (clean REST APIs with OAuth2):** Oura, Strava, Spotify, Google Tasks

**Stretch (ecosystem constraints):** Apple Health, Apple Music, SoundCloud

---

## Morning Digest Agent

### Registration

```python
@AgentRegistry.register("morning_digest")
class MorningDigestAgent(ToolUsingAgent):
    agent_id = "morning_digest"
```

### System Prompt & Persona

The agent's system prompt defines:

1. **Persona** — Jarvis personality (professional, dry wit, concise). Loaded from a configurable prompt file so it's swappable.
2. **Section ordering** — Which sections to include and in what order, driven by config.
3. **Date/time context** — Injected dynamically so the LLM knows "today."
4. **Prioritization rules** — e.g., "Highlight emails from direct manager. Deprioritize marketing newsletters. Flag meetings starting in <2 hours."

Example system prompt skeleton:

```
You are JARVIS, a professional AI assistant with dry wit.
Today is {date}, {day_of_week}. The time is {time} in {timezone}.
The user is {user_name}.

Generate a morning briefing from the data below. Be concise but
insightful. Open with a greeting. Organize by these sections:
{sections}

Prioritization rules:
{priority_rules}

Collected data:
{digest_data}
```

### Agent Flow

```
MorningDigestAgent.run()
  1. Call digest_collect tool -> returns structured data per source
  2. Inject collected data into system prompt
  3. Single LLM call to synthesize narrative
  4. Call text_to_speech tool -> generates audio
  5. Store DigestArtifact (text + audio path + metadata)
  6. Return AgentResult
```

This is intentionally not a multi-turn tool loop. The agent makes 2-3 deterministic tool calls, one LLM synthesis call, and one TTS call. Predictable, fast, debuggable. But since it extends `ToolUsingAgent`, interactive follow-ups can be added later ("Tell me more about that email from Alice").

### DigestArtifact

```python
@dataclass
class DigestArtifact:
    text: str                       # Full narrative markdown
    audio_path: Path                # Path to generated audio file
    sections: dict[str, str]        # Per-section text for selective delivery
    sources_used: list[str]         # Which connectors contributed
    generated_at: datetime
    model_used: str
    voice_used: str
```

Stored in a `DigestStore` (SQLite-backed, following the existing `SessionStore` pattern) so past digests are browsable.

---

## Text-to-Speech Pipeline

### TTS Backend Architecture

Follows the same pattern as the existing `SpeechBackend` (which handles STT). A new `TTSBackend` ABC with swappable implementations:

```python
class TTSBackend(ABC):
    async def synthesize(self, text: str, voice_id: str, **kwargs) -> AudioResult

@TTSRegistry.register("cartesia")
class CartesiaTTSBackend(TTSBackend): ...

@TTSRegistry.register("kokoro")
class KokoroTTSBackend(TTSBackend): ...

@TTSRegistry.register("openai")
class OpenAITTSBackend(TTSBackend): ...
```

### Cartesia as Default

- **Cartesia Ink** — fast, low-latency, high-quality voices. Ideal for on-device TTS.
- Supports voice cloning/design for creating a custom Jarvis voice.
- REST API + streaming support.
- Falls back to OpenAI TTS or Kokoro (fully open-source, runs locally) if unavailable.

### The `text_to_speech` Tool

Registered as a normal tool so any agent can use it:

```python
@ToolRegistry.register("text_to_speech")
class TextToSpeechTool(BaseTool):
    def execute(self, text: str, voice_id: str = "jarvis-v1",
                backend: str = "cartesia") -> ToolResult:
        # Delegates to TTSRegistry.get(backend).synthesize()
        # Returns: audio file path, duration, format
```

### Audio Output by Delivery Target

- **CLI**: `sounddevice`, `pygame.mixer`, or shell out to `afplay`/`aplay`/`ffplay`
- **Frontend**: HTML5 `<audio>` element, streamed from the API server
- **Desktop (Tauri)**: Same as frontend, or native audio playback

---

## Delivery Layer

### CLI: `jarvis digest`

New subcommand on the existing CLI entry point:

```bash
# Play today's digest (text + voice)
jarvis digest

# Text only, no audio
jarvis digest --text-only

# Re-generate fresh (skip cache)
jarvis digest --fresh

# Show past digests
jarvis digest --history

# Play a specific section only
jarvis digest --section health
```

Behavior:

1. Check `DigestStore` for today's artifact.
2. If found and fresh: print formatted text to terminal (rich/markdown) **and** play audio simultaneously in a background thread.
3. If stale/missing: run the digest agent on-demand, then deliver.
4. Text prints section by section with headers, audio plays the full narrative.

### Frontend / Desktop App

Delivered as a regular chat message through the existing channel system:

1. User types "Good morning Jarvis" (or hits a digest button in the UI).
2. Server endpoint `/api/digest` checks DigestStore, returns the artifact.
3. Frontend renders text in chat bubble (formatted markdown per section) + audio player component at top (auto-plays).
4. Sections are collapsible for quick scanning.

No new channel type needed — the existing chat UI + an audio player component handles it.

### API Endpoints

```
GET  /api/digest          -> Latest digest artifact (text + audio URL)
GET  /api/digest/audio    -> Audio file stream
POST /api/digest/generate -> Force re-generation
GET  /api/digest/history  -> Past digests
```

These sit in the existing FastAPI server (`src/openjarvis/server/`).

### Trigger Detection

For "Good morning Jarvis" natural language trigger: the system prompt for the default agent includes a routing instruction — if the user's message matches a greeting/digest intent, delegate to the digest delivery flow. Simple pattern matching as fast path, LLM classification as fallback.

---

## Configuration

### Full TOML Config

```toml
[intelligence]
default_model = "claude-sonnet-4-6"

[agent]
default_agent = "morning_digest"
tools = "digest_collect,web_search,text_to_speech"

[agent.morning_digest]
schedule = "0 6 * * *"
persona = "jarvis"
sections = ["messages", "calendar", "health", "world"]
optional_sections = ["github", "financial", "music", "fitness"]

[digest]
enabled = true
timezone = "America/Los_Angeles"

[digest.messages]
sources = ["gmail", "slack", "google_tasks"]
priority_contacts = ["advisor@stanford.edu", "team-channel"]
max_items = 10

[digest.calendar]
sources = ["gcalendar"]
lookahead_hours = 14

[digest.health]
sources = ["oura", "apple_health"]

[digest.world]
news_topics = ["artificial intelligence", "machine learning"]
arxiv_categories = ["cs.AI", "cs.CL", "cs.LG"]
include_weather = true
weather_location = "Stanford, CA"

[digest.github]
repos = ["OpenJarvis/OpenJarvis"]
include_prs = true
include_issues = true

[digest.financial]
tickers = ["NVDA", "GOOGL", "MSFT"]

[speech]
tts_backend = "cartesia"
tts_model = "sonic"
voice_id = "jarvis-v1"
speed = 1.0
output_format = "mp3"

[speech.cartesia]
api_key = "${CARTESIA_API_KEY}"

[speech.kokoro]
model_path = "~/.openjarvis/models/kokoro-v1"
device = "auto"
```

### Digest Sections

**Core sections (always present):**

| Section | Sources | Content |
|---------|---------|---------|
| `messages` | Gmail, Slack, iMessage (existing connector), Google Tasks | Important emails, messages, and tasks prioritized by relevance |
| `calendar` | Google Calendar | Today's meetings with prep notes |
| `health` | Oura Ring, Apple Health | Sleep score, readiness, activity summary |
| `world` | Web search (Tavily), Arxiv API, OpenWeatherMap API | Headlines, AI/tech news, papers, local forecast |

**Optional/pluggable sections:**

| Section | Sources | Content |
|---------|---------|---------|
| `github` | GitHub API | PRs, issues, CI status on configured repos |
| `financial` | Market data API | Ticker movements, portfolio summary |
| `music` | Spotify, Apple Music | Yesterday's listening, new releases |
| `fitness` | Strava | Recent workouts, streaks, PRs |

### Adding a New Section

1. **Create a connector** (if new data source) — `@ConnectorRegistry.register("foo")`
2. **Add section config** — new `[digest.section_name]` block in TOML
3. **Update persona prompt** — add instructions for how Jarvis narrates that section

No code changes to the digest agent. The `digest_collect` tool reads `config.digest.sections`, iterates over enabled connectors, and returns structured data. The LLM handles the rest.

### Persona System

Personas live as prompt files, swappable via config:

```
prompts/personas/jarvis.md    -- Professional, dry wit, "Good morning sir"
prompts/personas/friday.md    -- Warmer, more casual
prompts/personas/neutral.md   -- Straight facts, no personality
prompts/personas/custom.md    -- User-defined
```

Selected via `persona = "jarvis"` in config. The persona file is injected into the agent's system prompt at runtime.

---

## Testing Strategy

### Connector Tests
- Each connector tested against real APIs with real account data
- Integration tests verify `fetch_recent()` returns valid `Document` objects
- Mock tests for offline CI using recorded API responses (VCR pattern)

### Agent Tests
- Unit test: given mock collected data, verify LLM prompt is constructed correctly
- Integration test: end-to-end digest generation with stubbed connectors
- Snapshot tests for digest output format

### TTS Tests
- Unit test: `TTSBackend` interface compliance for each backend
- Integration test: Cartesia API produces valid audio bytes
- Audio duration sanity check (digest should be 2-5 minutes)

### Delivery Tests
- CLI: verify text output formatting and audio playback trigger
- API: endpoint returns correct artifact structure
- Frontend: component renders text + audio player

### Markers
- `@pytest.mark.cloud` for tests hitting real APIs (Cartesia, Oura, Spotify, etc.)
- `@pytest.mark.live` for tests needing a running engine
- Standard offline tests run in CI without credentials

---

## Implementation Sequence

### PR 1: MCP Connectors (separate, foundational)
Build and test all new connectors with real API data:
- Oura Ring connector
- Strava connector
- Spotify connector
- Google Tasks connector
- Apple Health connector (stretch)
- Apple Music connector (stretch)
- SoundCloud connector (stretch)

### PR 2: TTS Backend Infrastructure
- `TTSBackend` ABC + `TTSRegistry`
- Cartesia backend implementation
- Kokoro backend implementation (open-source fallback)
- OpenAI TTS backend implementation
- `text_to_speech` tool registration
- Config section `[speech]` for TTS

### PR 3: Digest Agent + Store
- `MorningDigestAgent` registration
- `digest_collect` tool
- `DigestArtifact` dataclass
- `DigestStore` (SQLite-backed)
- Persona prompt files (jarvis, neutral)
- Agent scheduler integration
- Config section `[digest]`

### PR 4: Delivery Layer
- CLI `jarvis digest` subcommand with audio playback
- API endpoints (`/api/digest`, `/api/digest/audio`, etc.)
- Frontend audio player component
- "Good morning Jarvis" trigger detection

### PR 5: Polish & Integration
- End-to-end testing with all connectors live
- Digest quality tuning (prompt engineering)
- Voice tuning (Cartesia voice design)
- Documentation
