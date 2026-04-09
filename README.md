<div align="center">
  <img alt="OpenJarvis" src="assets/OpenJarvis_Horizontal_Logo.png" width="400">
</div>

# ⚡ JARVIS — Just A Rather Very Intelligent System

> *"Sometimes you gotta run before you can walk."* — Tony Stark

[![Python](https://img.shields.io/badge/Python-3.10%2B-gold?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-red?style=for-the-badge)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Online-brightgreen?style=for-the-badge&logo=statuspage&logoColor=white)]()
[![Arc Reactor](https://img.shields.io/badge/Powered%20By-Arc%20Reactor-00bfff?style=for-the-badge)]()

---

```
   ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
   ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
   ██║███████║██████╔╝██║   ██║██║███████╗
██ ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝

  Just A Rather Very Intelligent System
  v1.0 — Stark Industries, R&D Division
```

**OpenJarvis** is a modular, open-source AI assistant backend built for people who think a chatbot is beneath them. It listens to your voice, sees your screen, knows your context, reacts to real-world events, and runs autonomous operators — all while you sip your scotch and work on the suit.

---

## The Arc Reactor — Core Architecture

```
                        ┌─────────────────────────────────┐
                        │          YOU  (Stark)           │
                        └──────────────┬──────────────────┘
                                       │  voice / text / screen
                        ┌──────────────▼──────────────────┐
                        │         JARVIS  CORE            │
                        │                                 │
                  ┌─────┤  Intelligence   Engine          ├─────┐
                  │     │  Agents         Memory          │     │
                  │     │  Learning       EventBus        │     │
                  │     └──────────────┬──────────────────┘     │
                  │                    │                         │
         ┌────────▼──────┐   ┌─────────▼──────────┐  ┌─────────▼──────┐
         │  Voice Loop   │   │  Operators / Cron  │  │   Channels     │
         │  Wake Word    │   │  Event Triggers    │  │   Telegram     │
         │  STT -> TTS   │   │  File/HTTP/Metric  │  │   Discord      │
         └───────────────┘   └────────────────────┘  └────────────────┘
```

Five primitives — **Intelligence, Engine, Agents, Memory, Learning** — compose into anything from a voice-controlled desktop companion to a fleet of autonomous operators monitoring your infrastructure.

---

## Suit Features

### 🎤 Voice Loop — *"Jarvis, fire up the Mark V"*
Full always-on voice pipeline. Say "Jarvis" → it wakes, listens, thinks, speaks back.

```bash
jarvis listen                                       # wake-word mode
jarvis listen --no-wake-word                        # always listening
jarvis listen --once                                # one shot, exits cleanly
jarvis listen --screenshot --screenshot-ocr         # Jarvis sees your screen too
```

Pipeline: `Mic → Energy VAD → STT (Whisper/Deepgram) → Wake Word → Agent → TTS (Kokoro/OpenAI) → Playback`

### 👁️ Screen Awareness — *"Enhance. Enhance."*
Jarvis can see your displays. Capture full screen or a region, extract text with OCR, feed it to any LLM.

```bash
jarvis ask "what is this error?" --screenshot
jarvis ask "summarize the document on screen" --screenshot --screenshot-ocr
jarvis ask "describe the left monitor" --screenshot --screenshot-region 0,0,1920,1080
```

### 🧠 Personal Context — *"I'm always online, sir"*
A structured living profile that Jarvis always knows — your identity, contacts, active projects, preferences.

```bash
jarvis profile import                           # first-run wizard
jarvis profile show
jarvis profile set name "Tony Stark"
jarvis profile prefer "never send emails without my go-ahead"
jarvis profile contact add "Pepper" --role ceo --note "handles everything"
jarvis profile project add "Mark VIII" --status active --desc "repulsor upgrade"
```

### ⚡ Event-Driven Operators — *"Alert protocol 7"*
Autonomous agents that wake up and act when things happen in the real world — not just on a timer.

```toml
[[operator.event_triggers]]
type    = "file"
path    = "~/inbox"
pattern = "*.pdf"
events  = ["created"]

[[operator.event_triggers]]
type      = "system_metric"
metric    = "cpu_percent"
threshold = 85.0
operator  = ">"

[[operator.event_triggers]]
type           = "http_poll"
url            = "https://status.openai.com"
fire_on_change = true

[[operator.event_triggers]]
type         = "bus_event"
event_type   = "channel_message_received"
filter_key   = "channel"
filter_value = "telegram"
```

Four trigger types: **file changes**, **system metrics** (CPU/RAM/disk), **HTTP content changes**, **internal event bus**.

### 🤖 9 Agent Types — *"Deploy the drones"*
From a simple one-shot responder to a full ReAct loop with tool use:

| Agent | What it does |
|-------|-------------|
| `simple` | Direct Q&A — fast, no tools |
| `orchestrator` | Breaks tasks into subtasks, delegates |
| `native_react` | ReAct loop with tool calls |
| `operative` | Operator-grade autonomous executor |
| `critic` | Self-critiques and revises output |
| `planner` | Long-horizon planning |
| `summarizer` | Distils and compresses |
| `multimodal` | Vision + text |
| `code` | Code generation and execution |

### 💾 Multi-Layer Memory
SQLite (default) + FAISS vector search + BM25 + ColBERT reranking. Context is automatically injected into every query — Jarvis remembers.

### 🔌 20+ Channel Integrations
Telegram, Discord, Slack, Gmail, Twitter/X, Reddit, Twilio, and more.

```bash
jarvis channel add telegram --token YOUR_BOT_TOKEN
jarvis channel add discord --token YOUR_BOT_TOKEN
```

---

## Installation

```bash
# Clone the suit
git clone https://github.com/akhilyad/__OpenJarvis.git
cd __OpenJarvis

# Sync with uv (recommended)
uv sync

# Or pip
pip install -e .
```

### Voice pipeline
```bash
uv sync --extra voice --extra speech
# Optional: better VAD
uv sync --extra voice-vad
# Optional: Kokoro local TTS
pip install kokoro
```

### Screen awareness
```bash
pip install mss Pillow          # capture
pip install pytesseract         # OCR (also needs Tesseract binary)
```

### Event-driven operators
```bash
uv sync --extra operators-events   # psutil + watchdog
```

### First Boot
```bash
jarvis init                 # initialise ~/.openjarvis/
jarvis profile import       # tell Jarvis who you are
jarvis doctor               # health check
jarvis ask "hello, Jarvis"  # first contact
```

---

## Quick Commands

```bash
# Ask
jarvis ask "what is the weather in Kolkata?"
jarvis ask "draft a reply to this email" --screenshot --screenshot-ocr
jarvis chat                                          # interactive session

# Voice
jarvis listen                                        # always-on voice loop
jarvis listen --no-wake-word --once                  # one command, done

# Agents + Tools
jarvis ask "search and summarise AI news" --agent orchestrator --tools web_search
jarvis ask "write and run this script"   --agent code --tools shell_exec

# Memory
jarvis memory search "project deadline"
jarvis memory add "Mark VIII repulsor upgrade due 2026-05-01"

# Operators
jarvis operators list
jarvis operators activate inbox-monitor
jarvis operators run-once inbox-monitor

# Profile
jarvis profile show
jarvis profile prefer "always use bullet points"

# System
jarvis doctor                    # health check
jarvis model list                # available models
jarvis serve                     # start REST API server
```

---

## Configuration

Config lives at `~/.openjarvis/config.toml`:

```toml
[intelligence]
default_model    = "gpt-4o"
preferred_engine = "openai"

[speech]
backend          = "faster_whisper"
wake_word        = "jarvis"
vad_engine       = "energy"
tts_backend      = "kokoro"
silence_timeout_ms = 1500

[memory]
default_backend = "sqlite"

[telemetry]
enabled = true
```

---

## Optional Extras

| Extra | What you get |
|-------|-------------|
| `voice` | sounddevice + soundfile (mic + playback) |
| `voice-vad` | webrtcvad (better speech detection in noise) |
| `voice-wakeword` | openwakeword (hot-word model, no STT in hot path) |
| `bundle-voice` | voice + speech + kokoro TTS |
| `screen` | mss + Pillow (screen capture + resize) |
| `screen-ocr` | + pytesseract (text extraction from screen) |
| `operators-events` | psutil + watchdog (event-driven operators) |
| `memory-faiss` | FAISS vector search |
| `inference-cloud` | OpenAI + Anthropic |
| `inference-mlx` | Apple MLX (macOS only) |
| `inference-vllm` | vLLM (GPU server) |

```bash
# Full suit — everything
uv sync --extra bundle-voice --extra screen --extra operators-events --extra memory-faiss
```

---

## Roadmap — *The Suit's Still Being Built*

- [x] **Feature 1** — Voice Loop (`jarvis listen`)
- [x] **Feature 2** — Event-Driven Operators
- [x] **Feature 3** — Personal Context Layer
- [x] **Feature 4** — Screen Awareness
- [ ] **Feature 5** — HUD / Heads-Up Display
- [ ] **Feature 6** — Home Automation Bridge
- [ ] **Feature 7** — Minions Protocol (multi-agent swarm)
- [ ] **Feature 8** — Agent-to-Agent (A2A) communication
- [ ] **Feature 9** — Self-Improving Prompts
- [ ] **Feature 10** — Mobile Companion App

---

## Known Issues

> *"Fortunately, I am Iron Man."* — and even I have a punch list.

| # | Severity | Issue |
|---|----------|-------|
| 1 | CRITICAL | `screen_capture` not auto-registered in ToolRegistry |
| 2 | HIGH | `voice/loop.py` imports from CLI layer (arch violation) |
| 3 | HIGH | `_can_fire()` race condition in watcher threads |
| 4 | HIGH | VAD has no max utterance duration limit |
| 5 | MEDIUM | `profile/store.py` reads file without explicit UTF-8 encoding |
| 6 | MEDIUM | Screen resize silently skipped if Pillow absent |

Being fixed in the next sprint.

---

## Contributing

Pull requests welcome. If you break the suit, fix the suit.

1. Fork
2. `git checkout -b feature/repulsor-upgrade`
3. `git commit -m 'add repulsor upgrade'`
4. `git push origin feature/repulsor-upgrade`
5. Open a PR

---

## License

MIT — *"I prefer to think of it as liberating."*

---

<div align="center">

**Built with arc reactor energy.**

*"Jarvis, sometimes I think you're the only one who gets me."*

</div>
