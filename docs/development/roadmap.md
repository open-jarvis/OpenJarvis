# Roadmap

## Current Focus Areas

These are the areas where active development is happening and contributions are most impactful:

- **Post-training data** — building datasets and training pipelines from execution traces to improve agent routing and tool selection
- **Multi-model orchestration pipelines** — coordinating multiple models within a single query (e.g., small model for classification, large model for generation)
- **Energy-aware routing** — using power consumption data from telemetry to optimize for energy efficiency alongside latency and quality
- **Plugin ecosystem** — community-contributed engines, tools, and agents distributed as Python packages
- **Federated memory** — memory backends that synchronize across devices

---

## How to Get Involved

1. Browse the workstreams below for items that interest you
2. Look for **Ready** items and **good first issue** tags
3. Find the matching [GitHub issue](https://github.com/open-jarvis/OpenJarvis/issues) and comment **"take"** to claim it — if no issue exists yet, [open one](https://github.com/open-jarvis/OpenJarvis/issues/new/choose) describing what you'd like to work on
4. Read the [Contributing Guide](https://github.com/open-jarvis/OpenJarvis/blob/main/CONTRIBUTING.md) for the full development setup, PR process, and code conventions

---

## Workstreams

OpenJarvis development is organized into **five independent workstreams**. Contributors can pick any track that matches their skills and interests — workstreams are designed to be worked on in parallel without blocking each other.

Every item carries a maturity tag:

| Tag | Meaning | Contributor guidance |
|-----|---------|---------------------|
| **Ready** | Well-scoped, implementation path is clear | Pick it up — check [issues](https://github.com/open-jarvis/OpenJarvis/issues) for a spec or write one |
| **Design Needed** | Concept is clear but needs a spec before code | Start a [design discussion](https://github.com/open-jarvis/OpenJarvis/discussions) or draft an RFC |
| **Research-Stage** | Exploratory, needs investigation before designing | Read the relevant papers, prototype, share findings |

---

### Workstream 1: Continuous Operators & Agents

Operators are OpenJarvis's key differentiator — persistent, scheduled, stateful agents that run autonomously on personal devices. The current tick-based architecture (OperatorManager → TaskScheduler → AgentExecutor → OperativeAgent) is solid but needs hardening for truly long-horizon autonomy.

#### Where you can help

| Item | Maturity | Details |
|------|----------|---------|
| Operator health checks & heartbeat monitoring | **Ready** | Add liveness probes to OperatorManager; surface in `jarvis operators status`. Detect stalled operators beyond the existing reconciliation loop. |
| Metrics collection for operator manifests | **Ready** | The `metrics` field exists in `OperatorManifest` but is not collected. Wire it to telemetry. **Good first issue.** |
| Capability policy enforcement | **Ready** | `required_capabilities` field exists in manifests but is not enforced. Connect to the existing RBAC `CapabilityPolicy` system. **Good first issue.** |
| Rate limiting per operator | **Ready** | Prevent runaway operators from hammering inference. Add configurable rate limits to OperatorManager. |
| Operator composition / chaining | **Design Needed** | Express dependencies between operators (operator A feeds results to operator B). Requires design for data passing and scheduling semantics. |
| Event-driven operators | **Design Needed** | Operators that trigger on EventBus events (e.g., new file indexed, channel message received) rather than only cron/interval schedules. |
| Operator versioning & rollback | **Design Needed** | Run v2 of an operator alongside v1. Roll back automatically on repeated failures. |
| Self-improving operators via Learning | **Research-Stage** | Operators that use trace feedback to tune their own prompts, tool selection, and routing policies through the Learning primitive. |

---

### Workstream 2: Mobile & Messaging Clients

Personal AI must be accessible from the devices people actually carry. OpenJarvis runs on laptops, workstations, and servers — users interact via their phones. Channels bridge that gap. Today, WhatsApp (Baileys), Slack, and Telegram are bidirectional; iMessage is send-only; Android SMS does not exist.

#### Where you can help

| Item | Maturity | Details |
|------|----------|---------|
| iMessage bidirectional via BlueBubbles | **Ready** | Current implementation is send-only. Add webhook/polling listener for incoming messages using the BlueBubbles API. **Good first issue.** |
| WhatsApp Baileys media support | **Ready** | Currently text-only. Add image, audio, and file handling to the Node.js bridge and Python channel. **Good first issue.** |
| Slack rich messages | **Ready** | Current implementation is plain text. Add Slack Block Kit support for formatted responses, buttons, and attachments. |
| Android SMS via Twilio/Vonage | **Design Needed** | No SMS implementation exists. Requires provider selection, two-way webhook architecture, and phone number provisioning flow. |
| Unified notification system | **Design Needed** | Push notifications when operators complete tasks or need user attention. Requires per-channel notification adapters. |
| Signal bidirectional | **Design Needed** | Currently send-only via signal-cli REST API. Add incoming message listener with background polling. |
| Voice interface | **Research-Stage** | Speech-to-text (Whisper) → agent → text-to-speech loop over phone channels. Existing `speech/` module provides a foundation. |

---

### Workstream 3: Secure Cloud Collaboration

Personal AI's core tension: local models preserve privacy but lack capability; cloud models are powerful but require trusting a provider with your data. This workstream resolves that through **Minions-style collaborative inference** (local handles context, cloud handles reasoning) and **TEE-based confidential computing** (cloud cannot see your data even during inference).

**References:**

- [Minions: Cost-Efficient Local-Cloud LLM Collaboration](https://github.com/HazyResearch/minions)
- [TEE for Confidential AI Inference](https://openreview.net/forum?id=ey87M5iKcX) ([PDF](https://openreview.net/pdf?id=ey87M5iKcX))

#### Where you can help

| Item | Maturity | Details |
|------|----------|---------|
| Query complexity analyzer | **Ready** | Classify incoming queries by difficulty to decide local vs. cloud routing. Extends the existing `MultiEngine` routing logic. |
| Cost tracking per-query | **Ready** | `CloudEngine` already has pricing data. Surface per-query cost in traces and telemetry dashboards. **Good first issue.** |
| Redaction-before-cloud pipeline | **Ready** | Wire the existing `GuardrailsEngine` in REDACT mode as a mandatory pre-step before any cloud transmission. |
| Minion protocol (sequential) | **Design Needed** | Local model extracts and summarizes long context → cloud model reasons over the compressed result. Native reimplementation of the core [Minions](https://github.com/HazyResearch/minions) idea. |
| Minion protocol (parallel) | **Design Needed** | Local and cloud models work simultaneously on different aspects of a query; results are merged. Requires a new `HybridInferenceEngine` abstraction. |
| TEE attestation verification | **Design Needed** | Verify that cloud inference ran inside a trusted execution environment via cryptographic attestation. |
| Taint tracking across local/cloud boundary | **Design Needed** | The `TaintSet` already tracks PII/Secret labels. Add routing enforcement so tainted data only routes to attested TEE endpoints. |
| Speculative decoding (local draft + cloud verify) | **Research-Stage** | Local model generates candidate tokens; cloud model validates in parallel for latency reduction. |

---

### Workstream 4: Tutorials & Documentation

OpenJarvis has reference docs and four tutorials, but critical gaps remain in continuous agents, LM evaluation, learning approaches, and custom tools. Video tutorials are scoped as a contributor opportunity — written tutorials come first, with video scripts included so anyone can record.

#### Where you can help

| Item | Maturity | Details |
|------|----------|---------|
| "Building Continuous Agents" tutorial | **Ready** | Writing an operator TOML manifest, activating it, session persistence across ticks, daemon mode. Example: a research operator that monitors arxiv daily. |
| "Adding Custom Tools" tutorial | **Ready** | Implementing `BaseTool`, registering via `ToolRegistry`, wiring into agents. Example: a weather API tool. **Good first issue.** |
| "Testing & Comparing LMs" tutorial | **Ready** | Running benchmarks, comparing local vs. cloud models, interpreting telemetry (latency, cost, energy per token). Uses the existing `bench/` framework. |
| Per-platform installation guides | **Ready** | Expand `installation.md` with platform-specific walkthroughs: macOS + Ollama, Ubuntu + NVIDIA + vLLM, Windows + Ollama, Raspberry Pi. **Good first issue.** |
| "Learning & Model Selection" tutorial | **Design Needed** | Router policies (heuristic, learned, GRPO), proposed approaches like Thompson Sampling, trace-based reward signals. |
| Video tutorial infrastructure | **Design Needed** | Establish recording workflow, hosting (YouTube), MkDocs embedding. Write video scripts alongside written tutorials. |
| Interactive Jupyter notebook tutorials | **Design Needed** | Notebook versions of key tutorials for exploratory, cell-by-cell learning. |

---

### Workstream 5: Hardware Breadth

Personal AI means running on the hardware people actually own. Each new hardware target expands who can use OpenJarvis and generates data for the research agenda (energy, cost, latency tradeoffs across silicon).

Adding a new hardware target involves up to four components: hardware detection in `core/config.py`, an inference engine adapter in `engine/`, an energy monitor in `telemetry/`, and an entry in the GPU specs database in `telemetry/gpu_monitor.py`.

#### Where you can help

| Item | Maturity | Details |
|------|----------|---------|
| AMD Ryzen AI iGPU path | **Ready** | Strix Point RDNA 3.5 iGPU handles 7-8B via Vulkan. llama.cpp Vulkan backend works today. Needs hardware detection and energy monitor. **Good first issue.** |
| GPU specs database expansion | **Ready** | Add Intel Arc, Jetson Orin, Snapdragon specs to `GPU_SPECS` in `telemetry/gpu_monitor.py` (TFLOPS, bandwidth, TDP). **Good first issue.** |
| Intel Arc GPU (B580/B570) | **Design Needed** | 12GB VRAM, ~$250 consumer GPU. Viable for 7-8B models. Engine path: IPEX-LLM or llama.cpp SYCL backend. |
| NVIDIA Jetson Orin | **Design Needed** | Best-in-class edge device. Orin NX 16GB handles 7-8B models at 15-25 tok/s. Needs hardware detection, energy monitor (tegrastats), deployment guide. |
| Qualcomm Snapdragon X Elite NPU | **Design Needed** | 45 TOPS, Windows Arm laptops. ONNX Runtime + QNN Execution Provider is the viable path. |
| Intel Lunar Lake NPU via OpenVINO | **Design Needed** | 48 TOPS — most mature NPU software stack for x86 laptops. New engine wrapping OpenVINO GenAI. |
| Raspberry Pi 5 | **Design Needed** | CPU-only via llama.cpp ARM NEON for 1-3B models. $100 entry point for hobbyists. |
| Unified hardware benchmark suite | **Design Needed** | Standardized benchmark that runs the same workloads across all supported hardware, producing comparable energy/latency/throughput/cost numbers. |
