# OpenJarvis Roadmap — Personal AI on Personal Devices

## Overview

OpenJarvis studies personal AI through five core primitives — **Intelligence**, **Engine**, **Agents**, **Tools** (memory, retrieval, tool APIs), and **Learning** — running on personal hardware. This roadmap organizes development into five independent workstreams, each with items flowing from immediately actionable to exploratory research.

### How to Read This Roadmap

**Workstreams are independent.** Contributors can pick any track without waiting on others. Within each track, items are organized by time horizon:

- **Near-term** — foundations and hardening of what exists
- **Mid-term** — significant new capabilities
- **Long-term** — frontier work requiring design exploration or research

Every item carries a **maturity tag**:

| Tag | Meaning | Contributor guidance |
|-----|---------|---------------------|
| **Ready** | Well-scoped, implementation path is clear | Pick it up — check issues for a spec or write one |
| **Design Needed** | Concept is clear but needs a spec before code | Start a design discussion or draft an RFC |
| **Research-Stage** | Exploratory, needs investigation before designing | Read the relevant papers, prototype, share findings |

Items marked with **"good first issue"** are especially suited for new contributors.

---

## Workstream 1: Continuous Operators & Agents

Operators are OpenJarvis's key differentiator — persistent, scheduled, stateful agents that run autonomously on personal devices. The current tick-based architecture (OperatorManager → TaskScheduler → AgentExecutor → OperativeAgent) is solid but needs hardening for truly long-horizon autonomy.

### Near-term

| Item | Maturity | Details |
|------|----------|---------|
| Operator health checks & heartbeat monitoring | **Ready** | Add liveness probes to OperatorManager; surface in `jarvis operators status`. Detect stalled operators beyond the existing reconciliation loop. |
| Metrics collection for operator manifests | **Ready** | The `metrics` field exists in `OperatorManifest` but is not collected. Wire it to telemetry. Good first issue. |
| Capability policy enforcement | **Ready** | `required_capabilities` field exists in manifests but is not enforced. Connect to the existing RBAC `CapabilityPolicy` system. Good first issue. |
| Rate limiting per operator | **Ready** | Prevent runaway operators from hammering inference. Add configurable rate limits to OperatorManager. |
| Operator composition / chaining | **Design Needed** | Express dependencies between operators (operator A feeds results to operator B). Requires design for data passing and scheduling semantics. |

### Mid-term

| Item | Maturity | Details |
|------|----------|---------|
| Event-driven operators | **Design Needed** | Operators that trigger on EventBus events (e.g., new file indexed, channel message received) rather than only cron/interval schedules. |
| Operator versioning & rollback | **Design Needed** | Run v2 of an operator alongside v1. Roll back automatically on repeated failures. |
| Multi-device operator coordination | **Design Needed** | Operators spanning laptop + workstation + datacenter node. Requires device discovery and task delegation protocols. |
| Dynamic tool loading per operator | **Design Needed** | Runtime tool discovery rather than static string lists in TOML manifests. |

### Long-term

| Item | Maturity | Details |
|------|----------|---------|
| Self-improving operators via Learning | **Research-Stage** | Operators that use trace feedback to tune their own prompts, tool selection, and routing policies through the Learning primitive. |
| Distributed operator mesh | **Research-Stage** | Peer-to-peer operator coordination across devices without a central orchestrator. |

---

## Workstream 2: Mobile & Messaging Clients

Personal AI must be accessible from the devices people actually carry. OpenJarvis runs on laptops, workstations, and servers — users interact via their phones. Channels bridge that gap. Today, WhatsApp (Baileys), Slack, and Telegram are bidirectional; iMessage is send-only; Android SMS does not exist. Beyond the channels listed below, OpenJarvis already supports 20+ additional channels (Discord, Matrix, Mastodon, Nostr, IRC, Line, Viber, Email, etc.) — see `src/openjarvis/channels/` for the full list.

### Near-term

| Item | Maturity | Details |
|------|----------|---------|
| iMessage bidirectional via BlueBubbles | **Ready** | Current implementation is send-only. Add webhook/polling listener for incoming messages using the BlueBubbles API. Good first issue. |
| WhatsApp Baileys media support | **Ready** | Currently text-only. Add image, audio, and file handling to the Node.js bridge and Python channel. Good first issue. |
| Slack rich messages | **Ready** | Current implementation is plain text. Add Slack Block Kit support for formatted responses, buttons, and attachments. |
| Android SMS via Twilio/Vonage | **Design Needed** | No SMS implementation exists. Requires provider selection, two-way webhook architecture, and phone number provisioning flow. |

### Mid-term

| Item | Maturity | Details |
|------|----------|---------|
| Unified notification system | **Design Needed** | Push notifications when operators complete tasks or need user attention. Requires per-channel notification adapters. |
| Offline message queue with retry | **Design Needed** | Handle mobile unreliability — queue outbound messages, retry on reconnect, deduplicate. |
| Channel media pipeline | **Design Needed** | Unified image/audio/file handling across all channels with consistent metadata and storage. |
| Signal bidirectional | **Design Needed** | Currently send-only via signal-cli REST API. Add incoming message listener with background polling. |

### Long-term

| Item | Maturity | Details |
|------|----------|---------|
| Voice interface | **Research-Stage** | Speech-to-text (Whisper) → agent → text-to-speech loop over phone channels. Existing `speech/` module provides a foundation. |
| Cross-channel session continuity UX | **Design Needed** | Start a conversation on Slack, continue on WhatsApp seamlessly. The `SessionStore` already supports multi-channel identity linking — this needs UX and channel-level plumbing. |

---

## Workstream 3: Secure Cloud Collaboration

Personal AI's core tension: local models preserve privacy but lack capability; cloud models are powerful but require trusting a provider with your data. This workstream resolves that through three complementary approaches: **Minions-style collaborative inference** (local handles context, cloud handles reasoning), **TEE-based confidential computing** (cloud cannot see your data even during inference, inspired by [Tinfoil](https://tinfoil.sh)), and **secure multi-device coordination**.

Key references:
- [Minions: Cost-Efficient Local-Cloud LLM Collaboration](https://github.com/HazyResearch/minions)
- [TEE for Confidential AI Inference](https://openreview.net/forum?id=ey87M5iKcX)
- [Tinfoil: Verifiably Private AI](https://tinfoil.sh)

### Near-term

| Item | Maturity | Details |
|------|----------|---------|
| Query complexity analyzer | **Ready** | Classify incoming queries by difficulty (token count, entity density, reasoning depth) to decide local vs. cloud routing. Extends the existing `MultiEngine` routing logic. |
| Cost tracking per-query | **Ready** | `CloudEngine` already has pricing data. Surface per-query cost in traces and telemetry dashboards. Good first issue. |
| Redaction-before-cloud pipeline | **Ready** | Wire the existing `GuardrailsEngine` in REDACT mode as a mandatory pre-step before any cloud transmission. The security primitives exist — this is integration work. |
| Minion protocol (sequential) | **Design Needed** | Local model extracts and summarizes long context → cloud model reasons over the compressed result. Native reimplementation of the core [Minions](https://github.com/HazyResearch/minions) idea in the `engine/` layer. |

### Mid-term

| Item | Maturity | Details |
|------|----------|---------|
| Minions protocol (parallel) | **Design Needed** | Local and cloud models work simultaneously on different aspects of a query; results are merged. Requires a new `HybridInferenceEngine` abstraction. Depends on: Minion protocol (sequential) from near-term. |
| Adaptive routing with learning | **Design Needed** | Router learns which queries need cloud vs. local based on trace feedback (accuracy, cost, latency). Connects the Engine and Learning primitives. |
| TEE attestation verification | **Design Needed** | Verify that cloud inference ran inside a trusted execution environment via cryptographic attestation. Add attestation checking to `CloudEngine` response handling. |
| Confidential inference provider support | **Design Needed** | Add Tinfoil (or similar TEE-backed providers) as a first-class engine backend. OpenAI-compatible API with attestation verification built in. |
| Taint tracking across local/cloud boundary | **Design Needed** | The `TaintSet` (Python: `security/taint.py`, Rust: `crates/openjarvis-security/src/taint.rs`) already tracks PII/Secret labels. Add routing enforcement at the `engine/` layer so tainted data only routes to attested TEE endpoints, never to unattested cloud APIs. |

### Long-term

| Item | Maturity | Details |
|------|----------|---------|
| Speculative decoding (local draft + cloud verify) | **Research-Stage** | Local model generates candidate tokens speculatively; cloud model validates in parallel for latency reduction. |
| KV cache sharing between local and cloud | **Research-Stage** | Transfer attention state between engines to avoid recomputation. Requires a shared cache serialization format and encrypted transport. |
| Secure multi-device federation | **Research-Stage** | Multiple personal devices collaborate on inference with end-to-end encryption. Extends operator mesh from Workstream 1. |
| Early exit detection | **Research-Stage** | When local model confidence is high, skip cloud entirely. Dynamic cost/quality tradeoff learned from traces. |

---

## Workstream 4: Tutorials & Documentation

OpenJarvis has strong reference docs and four tutorials (deep research, scheduled ops, messaging hub, code companion), but critical gaps remain in continuous agents, LM evaluation, learning approaches, and custom tools. Video tutorials are scoped as a contributor opportunity — written tutorials come first, with video scripts included so anyone can record.

### Near-term

| Item | Maturity | Details |
|------|----------|---------|
| "Building Continuous Agents" tutorial | **Ready** | Writing an operator TOML manifest, activating it, session persistence across ticks, state management, daemon mode. Example: a research operator that monitors arxiv daily. Follows the existing tutorial template (Python script + TOML recipe + markdown walkthrough). |
| "Adding Custom Tools" tutorial | **Ready** | Implementing `BaseTool`, registering via `ToolRegistry`, wiring into agents. Example: a weather API tool. `docs/development/extending.md` covers engine extensions but there is no standalone tools tutorial with a runnable end-to-end example. Good first issue. |
| "Testing & Comparing LMs" tutorial | **Ready** | Running benchmarks, comparing local vs. cloud models, interpreting telemetry (latency, cost, energy per token). Uses the existing `bench/` framework. |
| Per-platform installation guides | **Ready** | Expand `installation.md` with platform-specific walkthroughs: macOS Apple Silicon + Ollama, Ubuntu + NVIDIA + vLLM, Windows + Ollama, Raspberry Pi. Good first issue. |

### Mid-term

| Item | Maturity | Details |
|------|----------|---------|
| "Learning & Model Selection" tutorial | **Design Needed** | Router policies (heuristic, learned, GRPO), proposed approaches like Thompson Sampling, trace-based reward signals. This is the least-documented of the five primitives. |
| "Multi-Channel Deployment" tutorial | **Design Needed** | Deploying one agent across Slack + WhatsApp + iMessage simultaneously. Cross-channel session continuity. |
| Video tutorial infrastructure | **Design Needed** | Establish recording workflow, hosting (YouTube), MkDocs embedding. Write video scripts alongside written tutorials so contributors can record independently. |
| Interactive Jupyter notebook tutorials | **Design Needed** | Notebook versions of key tutorials for exploratory, cell-by-cell learning. |

### Long-term

| Item | Maturity | Details |
|------|----------|---------|
| Contributor tutorial program | **Research-Stage** | Templates and guidelines for community members to submit their own tutorials. Review process, quality bar, and integration with the docs site. |
| Tutorial localization (i18n) | **Research-Stage** | Translate core tutorials into major languages. |

---

## Workstream 5: Hardware Breadth

Personal AI means running on the hardware people actually own. Each new hardware target expands who can use OpenJarvis and generates data for the research agenda (energy, cost, latency tradeoffs across silicon).

Adding a new hardware target involves up to four components: hardware detection in `core/config.py`, an inference engine adapter in `engine/`, an energy monitor in `telemetry/`, and an entry in the GPU specs database in `telemetry/gpu_monitor.py`.

### Near-term

| Item | Maturity | Details |
|------|----------|---------|
| Intel Arc GPU (B580/B570) | **Design Needed** | 12GB VRAM, ~$250 consumer GPU. Viable for 7-8B models. Engine path: IPEX-LLM or llama.cpp SYCL backend. Needs `_detect_intel_arc_gpu()`, energy monitor via RAPL/sysfs, engine adapter. |
| NVIDIA Jetson Orin | **Design Needed** | Best-in-class edge device. Orin NX 16GB handles 7-8B models at 15-25 tok/s. Ollama/llama.cpp already work; needs hardware detection, energy monitor (tegrastats), deployment guide. |
| Qualcomm Snapdragon X Elite NPU | **Design Needed** | 45 TOPS, Windows Arm laptops. ONNX Runtime + QNN Execution Provider is the viable path. Needs new engine adapter, hardware detection, energy monitor. |
| AMD Ryzen AI iGPU path | **Ready** | Strix Point RDNA 3.5 iGPU handles 7-8B via Vulkan. llama.cpp Vulkan backend works today. Needs hardware detection and energy monitor. Good first issue. |
| GPU specs database expansion | **Ready** | Add Intel Arc, Jetson Orin, Snapdragon specs to `GPU_SPECS` in `telemetry/gpu_monitor.py` (TFLOPS, bandwidth, TDP). Good first issue. |

### Mid-term

| Item | Maturity | Details |
|------|----------|---------|
| Intel Lunar Lake NPU via OpenVINO | **Design Needed** | 48 TOPS — most mature NPU software stack for x86 laptops. New engine wrapping OpenVINO GenAI. Good for offloading 1-3B models while GPU handles larger ones. |
| Qualcomm mobile (Snapdragon 8 Gen 3/4) | **Design Needed** | 1-7B on phones via QNN SDK. Ties into Workstream 2 — inference on the phone itself rather than relaying to a server. |
| Raspberry Pi 5 | **Design Needed** | CPU-only via llama.cpp ARM NEON for 1-3B models. $100 entry point for hobbyists. Hailo-8L NPU is not viable for LLMs (vision-only architecture). |
| Unified hardware benchmark suite | **Design Needed** | Standardized benchmark that runs the same workloads across all supported hardware, producing comparable energy/latency/throughput/cost numbers. |

### Long-term

| Item | Maturity | Details |
|------|----------|---------|
| MediaTek Dimensity NPU | **Research-Stage** | Most aggressive mobile LLM push (45-50 TOPS) but closed NeuroPilot SDK. Monitor for SDK openness or third-party framework support. |
| Hailo-10 | **Research-Stage** | Hailo announced generative AI targeting for next-gen hardware. Watch for availability and transformer support. Current Hailo-8/8L is vision-only. |
| AMD XDNA2/3 NPU | **Research-Stage** | 50 TOPS but software stack (Ryzen AI SDK) is immature for LLMs. Revisit as AMD improves tooling. The AMD Ryzen AI iGPU item above is the practical AMD target today. |
| Intel Gaudi 3 / Falcon Shores | **Research-Stage** | 128GB HBM, datacenter-class. Gaudi product line being discontinued in favor of Falcon Shores architecture. Wait for clarity before investing. |
| RISC-V + NPU SoCs | **Research-Stage** | 3-5 years behind ARM/x86. Watch Sophgo SG2380 and similar. Not actionable for production use yet. |

---

## Contributing

Each workstream is independent — pick the one that matches your skills and interests:

| Workstream | Skills needed |
|------------|--------------|
| 1. Continuous Operators | Python, async/scheduling, agent systems |
| 2. Mobile & Messaging | Node.js (Baileys bridge), Python, messaging platform APIs |
| 3. Secure Cloud Collaboration | Cryptography, TEE/confidential computing, distributed systems, ML |
| 4. Tutorials & Documentation | Technical writing, MkDocs, video production |
| 5. Hardware Breadth | Systems programming, hardware-specific SDKs (IPEX-LLM, OpenVINO, QNN), Rust |

**To get started:** Look for items tagged **Ready** — these have clear scope and are ready for implementation. Items tagged **good first issue** are especially approachable. Open an issue or discussion on the repo to claim work or propose a design for **Design Needed** items.
