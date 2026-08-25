# Changelog

All notable changes to OpenJarvis are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

### Added

**Apple Foundation Models (AFM 3)** — a new in-process `afm` engine drives
Apple's `apple-fm-sdk` directly, with no HTTP hop and no second process whose
CPU draw would land inside the same energy measurement window. Install with
`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer uv sync --extra afm`
(the SDK compiles Swift bindings, so a full Xcode is required), then
`jarvis ask --engine afm --model afm-3-core "..."`. Requires an Apple Silicon
Mac on macOS 26+ with Apple Intelligence enabled.

Token counts are real, via `SystemLanguageModel.token_count` (added in SDK
0.2.1, hence the floor). Because `token_count` rejects a value and
instructions together, both ends are measured against the session transcript:
`prompt_tokens = <transcript before> + <prompt alone>` and
`completion_tokens = <transcript after> - prompt_tokens`.

Two caveats worth reading before comparing AFM numbers to other backends:
`stream_response` yields cumulative snapshots batching roughly 8-10 tokens, so
`ttft` is time-to-first-*chunk* (~450 ms on an M1 Pro) and derived
inter-token latencies are inter-chunk; and the SDK exposes no variant
selector, so `afm-3` / `afm-3-core` / `afm-3-core-advanced` are run labels
only — the framework's dynamic profile chooses what actually executes.
Bench results record `metadata["engine_info"]` (SDK version, context size,
host chip) so a run can be attributed after the fact.

**Eval results record which rail did the work.** Result rows and summaries
previously carried only `energy_joules` and `power_watts`, so nothing in an
eval artifact distinguished a Neural Engine run from an idle GPU, or a
hardware measurement from a modelled estimate. Rows now include the per-rail
breakdown (`cpu`/`gpu`/`dram`/`ane`/`soc`), `energy_basis`, and
`energy_method`; summaries add `energy_joules_by_rail` alongside both. On a
ToolCall-15 run against AFM the ANE rail is the largest single component —
91.7 J of 223.7 J, against 3.0 J on the GPU — which is now visible in the
file rather than only through live instrumentation.

**ANE and whole-SoC energy** — `EnergySample.ane_energy_joules` existed but
died at the monitor boundary. Apple Neural Engine and a whole-SoC total now
flow through `TelemetryRecord`, the SQLite schema (with an `ADD COLUMN`
migration), the aggregator, `TelemetrySession`, eval `TurnTrace`/`QueryTrace`,
and bench metadata, alongside an `energy_basis` marker (`"soc"` on Apple
Silicon, `"gpu"` elsewhere) so downstream repeats the monitor's choice instead
of guessing. This matters because AFM runs predominantly on the ANE: measured
on an M1 Pro, one generation drew 0.98 J on the ANE against 0.014 J on the
GPU rail — 70x — where an MLX matmul on the same machine drew 8.99 J on the
GPU and nothing on the ANE.

**Vision input for `jarvis ask`** — attach images to a query with
`-i`/`--image` (repeatable) or capture the current screen with
`-S`/`--screen`, for vision-capable models such as `gemma3:4b`. Images flow
through `Message.images` into Ollama's `/api/chat` `images` field; text-only
requests are unaffected. A privacy guard warns before any image is sent to a
non-local engine, and the security guardrail now preserves images when it
sanitizes a flagged prompt. Screen capture uses the built-in Windows .NET
stack with `mss`/`Pillow` fallbacks on other platforms. Adds the
`JARVIS_NUM_CTX` environment variable to tune the Ollama context window
(default `16384`).

### Fixed

**Apple Silicon energy was never measured, only modelled.**
`telemetry/energy_apple.py` imported `AppleSiliconMonitor` from
`zeus.device.soc.apple`; no such class has ever existed there. The import
raised on every machine, so the CPU-time fallback -- `wall_clock x TDP x 0.60`
split by four hardcoded ratios -- was the only path that ever ran. It read no
counters and no utilization, so a ten-second sleep and a ten-second generation
produced identical joules, and every Apple Silicon figure in the telemetry DB,
eval traces and `jarvis bench` came from it. Renaming the import would not
have helped: `zeus.device.soc` landed on zeus master after the last zeus
release, so no published `zeus-ml` contains it, and `zeus-ml` has no `apple`
extra either. `energy-apple` now installs `zeus-apple-silicon`, the IOReport
extension zeus itself wraps, which needs no root. Measured on an M1 Pro:
8.24 W under load against 3.72 W idle, where the previous code could not tell
the two windows apart.

`AppleEnergyMonitor.available()` now reports `False` when nothing is
measurable, instead of `True` on any Apple Silicon host, so the factory falls
through rather than letting a model masquerade as a measurement. The estimate
remains reachable through the new `telemetry.allow_energy_estimates` setting
and still reports `energy_method = "tdp_estimate"`.

`snapshot()` is implemented for the first time, so `TelemetrySession`'s
background sampler -- the path agentic evals use -- records real readings
rather than the ABC's empty default. Relatedly, `TelemetrySample` hardcoded
`cpu_power_w = 0.0`, which zeroed CPU power in every eval trace on every
platform.

**`apple_fm` shim reported zero token counts.** It hardcoded zeros with a note
that the SDK did not expose counts; SDK 0.2.1 added `token_count`. Zeroed
`completion_tokens` zeroes throughput, `energy_per_output_token_joules` and
`tokens_per_joule` for everything served through the shim. Streaming responses
now also carry `usage` on the final chunk. The install hint no longer tells
users to clone from GitHub -- `apple-fm-sdk` is on PyPI. System messages become
the session's `instructions` rather than being prefixed onto the prompt as
`[System] ...`, which discarded a distinction the SDK draws and inflated the
prompt-token count.

**`scripts/setup-energy-monitor.sh` did not exist**, though
`jarvis bench --setup-energy` built a path to it and offered to run it -- so
the offer silently did nothing.

### Security

**WebSocket API keys no longer appear in request URLs.** Browser clients now
send a marked, base64url-encoded credential through
`Sec-WebSocket-Protocol`; programmatic clients can continue to use an
`Authorization: Bearer <key>` handshake header. The encoding only makes the
credential safe for WebSocket protocol syntax and does not encrypt it, so use
`wss://` for remote connections.

The former `?token=<key>` WebSocket authentication path is no longer accepted.
Custom browser clients must migrate to the `openjarvis.auth.v1` subprotocol
format documented in the API server guide.

## [1.0.2] - 2026-05-24

A patch release that fixes a packaging bug which broke the v1.0.1
wheel on PyPI, silences a noisy startup warning, restores a working
install path while `openjarvis.ai` is down, improves desktop
first-boot diagnostics on Windows, and ships the RAM-detection fix
for Windows that missed the v1.0.1 cutoff.

### Fixed

**`openjarvis/traces/` missing from the v1.0.1 PyPI wheel** (#372).
The `.gitignore` carried an unanchored `traces/` pattern, which
hatchling honored at wheel-build time and matched the runtime module
`src/openjarvis/traces/` — silently dropping the whole package. Every
fresh `pip install openjarvis==1.0.1` then failed at import with
`ModuleNotFoundError: No module named 'openjarvis.traces'` on the
first `jarvis ask`, learning, or server call. Anchored the pattern to
`/traces/`. Verified: a clean `uv build` now produces a wheel
containing all four `traces/` files.

**`pynvml` deprecation `FutureWarning` on every command** (#389).
Switched the dependency from the legacy `pynvml` package to NVIDIA's
official `nvidia-ml-py` (same `pynvml` module name, no warning shim),
and added defensive `warnings.filterwarnings` at every `import pynvml`
site to suppress the warning even when `pynvml` is pulled in
transitively.

**Windows RAM detection returning `0.0 GB`** (#373). The Windows
branch of `_total_ram_gb()` (via `GlobalMemoryStatusEx`) landed after
the v1.0.1 cutoff, so v1.0.1 users still saw `0.0 GB` from `jarvis
init`. Now shipping in the wheel. A new `windows-latest` CI job runs
the real `GlobalMemoryStatusEx` path on every PR as a regression
guard.

**Desktop first-boot hung on "did not become healthy in time"**
(#331). The Tauri boot path ran `uv sync` with stderr discarded and
the exit code ignored, so a failed dependency install surfaced only
as a generic 600-second health-check timeout. Now captures stderr,
checks the exit status, and surfaces the actual `uv sync` error
(with the diagnostic tail) before the long wait. The error-formatting
logic is covered by unit tests.

### Changed

**Install URL moved to GitHub Pages** (#337, #352). The documented
`openjarvis.ai/install.sh` URL was failing with `sslv3 alert
handshake failure` (the domain is community-operated and had a broken
TLS config). The canonical installer is now served from the
project-controlled GitHub Pages site at
`https://open-jarvis.github.io/OpenJarvis/install.sh`, generated from
the same `scripts/install/install.sh` at docs-build time. The README
also documents the WSL2 path for Windows and the `uv` prerequisite
for the desktop binary, and the installer bails early with a clear
message when run under Git Bash / MSYS2 / Cygwin.

## [1.0.1] - 2026-05-17

A patch release that closes the auto-update gap so the analytics
module added in #351 actually reaches users on the desktop, adds
runtime opt-out for that analytics, fixes the misleading upgrade
hint the CLI was printing, and lands the ACE optimizer alongside
DSPy and GEPA.

### Added

**ACE agent optimizer** (`learning/agents/ace_optimizer.py`). Adds
[ACE](https://github.com/ace-agent/ace) as a third agent-learning
policy alongside DSPy and GEPA. Where DSPy bootstraps few-shot
examples and GEPA evolves prompt populations, ACE evolves a textual
*playbook* of strategies the agent reads at inference time, updated
by a Generator / Reflector / Curator triad. Pick via
`[learning.agent] policy = "ace"`. Setup is manual (ACE isn't on
PyPI and isn't a properly-packaged Python project as of v1.0.1) —
see `docs/learning/ace.md` for the install path and trace-adapter
behavior.

**`jarvis self-update`** subcommand. Detects how OpenJarvis was
installed (pip, uv tool, editable git checkout) by inspecting
`openjarvis.__file__`, then runs the right upgrade command. Supports
`--check` (print the command without running) and `-y` (skip the
confirmation prompt). The post-command "new version available" hint
now points users at this command instead of guessing at the right
flow.

**Desktop auto-update endpoint wired to the rolling
`desktop-latest` GitHub release.** The Tauri updater plugin was
configured on the build side (`createUpdaterArtifacts: true`,
`includeUpdaterJson: true`, signing key in `TAURI_SIGNING_PRIVATE_KEY`)
but inert on the runtime side (`active: false`, `endpoints: []`). The
installed desktop app would never check. Both are now fixed; the app
polls `releases/download/desktop-latest/latest.json` every 30 minutes
and signature-verifies downloads against the minisign pubkey baked
into the app. Full flow, key-rotation runbook, and dev escape hatch
(`OPENJARVIS_NO_UPDATER=1`) documented in `docs/desktop-auto-update.md`.

**Analytics env-var opt-out** (`DO_NOT_TRACK`, `OPENJARVIS_NO_ANALYTICS`).
Tanvir's analytics module (#351) only respected the
`[analytics] enabled` config-file setting. Both env vars are now
honored in `is_analytics_enabled()` and in the install.sh beacon
script. Any truthy value (`1`, `true`, `yes`, `on`) disables for
that process; env opt-out takes precedence over the config file.
Documented under a new "Opting out" section in `docs/telemetry.md`.

### Changed

**Version-check trigger widened.** The "new version available" hint
in `_version_check.py` used to fire only on `{ask, chat, serve}` and
hardcoded the wrong upgrade command (`git pull && uv sync` — only
correct for editable installs). Now fires on every interactive
command (`doctor`, `init`, `quickstart`, `model`, `agents`, `skill`,
`memory`, `bench`, `telemetry`, `config`, `eval`, `optimize`, plus
the original three) and uses install-detection to print the right
upgrade command. Honors `JARVIS_NO_UPDATE_CHECK=1` and `CI=true` to
stay silent in automation.

**Desktop app version bumped 0.1.0 → 1.0.1** across
`tauri.conf.json`, `frontend/package.json`, and
`frontend/src-tauri/Cargo.toml` so the Python and desktop release
streams are aligned and the auto-updater has a real version to
compare against.

### Migration from 1.0.0

- **Importing `is_analytics_enabled`?** Same signature; behavior now
  short-circuits on env opt-out before checking the config. Callers
  that want the raw "is the config flag set" semantic should read
  `cfg.enabled` directly.
- **Editable-git users running `jarvis self-update`** get the
  detected `git pull && uv sync` command pointed at their actual
  checkout, not `~/OpenJarvis`. If you'd come to rely on the
  hardcoded path, update your muscle memory.

## [1.0.0] - 2026-05-15

The five-primitive architecture (Intelligence, Engine, Agents,
Tools & Memory, Learning) is now stable, with efficiency and
on-device learning as first-class capabilities alongside accuracy.
Companion blog post:
[From Minions to OpenJarvis: A Retrospective on Two Years in Local AI](https://hazyresearch.stanford.edu/blog/2026-05-19-minions-to-openjarvis-retrospective).

### Highlights

**Five composable primitives.** Intelligence, Engine, Agents, Tools & Memory,
and Learning each sit behind a single typed interface — any slot is
substitutable without touching the rest. The composition layer is
`JarvisSystem` in `src/openjarvis/system.py`, driven by a TOML config.

**Built-in agents across three execution modes.** Eight agents spanning a
single-turn chat baseline, a deep-research agent with inline citations,
a CodeAct-style coder, and a continuous monitor with memory compression
for long-horizon workflows. Execution modes cover on-demand, scheduled,
and continuous.

**Starter presets.** Eight preset configs installable via
`jarvis init --preset <name>` bundle an agent with a hardware-appropriate
engine, connectors, and tools. Variants cover Apple Silicon, Linux GPU
servers, and CPU-only laptops, plus a quickstart for LLM-guided spec search.

**Inference engines.** Four first-class local engines (Ollama, vLLM, SGLang,
llama.cpp) and five cloud providers (OpenAI, Anthropic, Google Gemini,
OpenRouter, MiniMax) sit behind a single `Engine` interface. Discovery
in `engine/_discovery.py` picks a sensible default per host.

### Added — hybrid local-cloud capabilities

**Per-query routing via a query-complexity analyzer**
(`src/openjarvis/learning/routing/complexity.py`). Produces a 0.0–1.0
complexity score with code/math/reasoning signals and a suggested token
budget, populating `RoutingContext` so easy queries stay local and only
queries that need frontier capability escalate.

**LLM-guided spec search** (`src/openjarvis/learning/spec_search/`).
`SpecSearchOrchestrator` wires diagnose → plan → execute → gate into a
single learning session: a frontier model reads traces, proposes
coordinated edits across all five primitives, and a held-out benchmark
gate (`gate/benchmark_gate.py`, `gate/regression.py`, `gate/cold_start.py`)
accepts only non-regressing edits. Ships with the `spec-search-quickstart`
preset and a runnable tutorial at `examples/openjarvis/spec_search_quickstart.py`.

**Six hybrid coordination paradigms** in `src/openjarvis/agents/hybrid/`.
Each paradigm pairs a local student with a frontier cloud teacher under
a different orchestration shape, as `LocalCloudAgent` subclasses:

- `minions` — reactive single-local + single-cloud loop
- `conductor` — static DAG planner
- `advisors` — executor ↔ advisor loop
- `archon` — generate → rank → fuse
- `skillorchestra` — per-query router across local skills
- `toolorchestra` — RL'd local model with a tool pool

A runner CLI (`python -m openjarvis.agents.hybrid.runner --cell <name>`)
and a 35-cell experiment registry (one TOML per method × benchmark ×
model triple) let researchers run, score, and compare these on equal
footing. Includes a Modal-backed SWE-bench-Verified harness scorer
(`evals/scorers/swebench_harness.py`).

### Added — efficiency as a first-class constraint

**Hardware-agnostic energy telemetry at 50ms resolution** across NVIDIA
(`telemetry/energy_nvidia.py`), AMD (`telemetry/energy_amd.py`), Apple
Silicon (`telemetry/energy_apple.py`), and Intel RAPL
(`telemetry/energy_rapl.py`). Energy, dollar cost, FLOPs, and latency
are treated as evaluation targets alongside accuracy.

**Instrumentation for FLOPs, batch, steady-state, ITL, phase energy, and
vLLM-specific metrics.** Joined per-query by the aggregator
(`telemetry/aggregator.py`) so traces carry accuracy + efficiency together.

### Added — local learning loop

**Closed-loop optimization across the stack** — model weights via SFT
(`learning/intelligence/sft_trainer.py`) and GRPO
(`learning/intelligence/grpo_trainer.py` plus an orchestrator-specific
variant under `learning/intelligence/orchestrator/`), prompts via DSPy
(`learning/agents/dspy_optimizer.py`), agent logic via GEPA
(`learning/agents/gepa_optimizer.py`), and engine + stack configuration
via LLM-guided spec search. `LearningOrchestrator` coordinates triggers
and applies optimizer overlays at discovery time so improvements compound
across primitives.

### Added — cross-framework evaluation

**External agentic-framework evaluation via subprocess.** The
`evals/backends/external/` subpackage wraps Hermes Agent and OpenClaw as
one-shot subprocess backends behind the existing `InferenceBackend` ABC.
The `evals/comparison/` toolkit provides path + commit-pin enforcement
(`third_party.py`), config templating (`make_configs.py`), and LaTeX
table generation (`table_gen.py`).

Ships with a new optional extra `framework-comparison` (depends on
`polars`), a `live_external` pytest marker for integration tests
requiring real foreign-framework installations, and a `ToolOrchestra`
evaluation dataset (`evals/datasets/toolorchestra.py`) alongside the
existing 30+ benchmark suite.

### Added — Skills System (Plans 1, 2A, 2B)

- **Skills core** — every skill is a tool. Skills appear in a system prompt catalog, agents invoke them on demand, content (pipeline results, markdown instructions, or both) gets injected into context.
  - `SkillManifest` + `SkillStep` types with tags, depends, invocation flags, markdown content
  - `SkillManager` — discovery, precedence resolution, catalog XML generation, tool wrapping
  - `SkillTool(BaseTool)` — auto-extracts parameters from step argument templates
  - `SkillExecutor` — sequential pipeline execution with sub-skill delegation
  - Dependency graph with cycle detection, max depth enforcement, capability unions
  - Security: four trust tiers (bundled/indexed/unreviewed/workspace), capability-gated enforcement
  - Skill index module for git-backed registry search

- **agentskills.io spec adoption** — canonical `SKILL.md` format with YAML frontmatter following the [agentskills.io](https://agentskills.io/specification) open standard.
  - `SkillParser` with strict spec validation + tolerant field mapping via `FIELD_MAPPING` table
  - `ToolTranslator` for external tool name translation (Bash -> shell_exec, Read -> file_read, etc.)
  - Source resolvers: `HermesResolver`, `OpenClawResolver`, `GitHubResolver`
  - `SkillImporter` with provenance tracking (`.source` metadata files), optional script import
  - Sourced subdirectory layout (`~/.openjarvis/skills/<source>/<name>/`)

- **Skills learning loop** — trace tagging, pattern discovery, DSPy/GEPA optimization.
  - Trace metadata tagging: `skill`, `skill_source`, `skill_kind` flow through ToolExecutor -> TraceCollector -> TraceStep
  - `SkillDiscovery` wired into `SkillManager.discover_from_traces()` with kebab name normalization
  - `SkillOptimizer` — per-skill DSPy/GEPA wrapper that buckets traces and writes sidecar overlays
  - `SkillOverlay` — sidecar storage at `~/.openjarvis/learning/skills/<name>/optimized.toml`
  - `SkillManager._load_overlays()` applies optimized descriptions + few-shot examples at discovery time
  - `LearningOrchestrator._maybe_optimize_skills()` — opt-in auto-trigger

- **Skills benchmark harness** — 4-condition PinchBench evaluation.
  - I3 fix: `skill_few_shot_examples` wired through SystemBuilder -> `_run_agent` -> `ToolUsingAgent` -> `native_react.REACT_SYSTEM_PROMPT`
  - `SkillBenchmarkRunner` — 4-condition x N-seed x M-task sweep with markdown report
  - `JarvisAgentBackend` accepts `skills_enabled` and `overlay_dir` kwargs
  - Conditions: `no_skills`, `skills_on`, `skills_optimized_dspy`, `skills_optimized_gepa`

- **CLI commands:**
  - `jarvis skill list` / `info` / `run` / `install` / `sync` / `sources` / `update` / `remove` / `search`
  - `jarvis skill discover` — mine traces for recurring tool patterns
  - `jarvis skill show-overlay` — inspect optimization output
  - `jarvis optimize skills` — run DSPy/GEPA per-skill optimization
  - `jarvis bench skills` — run the PinchBench skills benchmark

- **Agent prompt improvement:**
  - `native_react.REACT_SYSTEM_PROMPT` now includes "Using Skills" guidance that teaches agents to distinguish executable vs. instructional skill responses
  - `{skill_examples}` placeholder for optimized few-shot example injection

- **Configuration:**
  - `[skills]` section: `enabled`, `skills_dir`, `active`, `auto_discover`, `auto_sync`, `max_depth`, `sandbox_dangerous`
  - `[[skills.sources]]` section: `source`, `url`, `filter`, `auto_update`
  - `[learning.skills]` section: `auto_optimize`, `optimizer`, `min_traces_per_skill`, `optimization_interval_seconds`, `overlay_dir`
  - `SkillSourceConfig` and `SkillsLearningConfig` dataclasses

- **Documentation:**
  - `docs/user-guide/skills.md` — comprehensive user guide
  - `docs/architecture/skills.md` — technical deep-dive
  - `docs/tutorials/skills-workflow.md` — end-to-end tutorial
  - `docs/getting-started/configuration.md` — expanded with skills config sections
  - `CLAUDE.md` — updated architecture section

### Examples & Tutorials

- `examples/openjarvis/spec_search_quickstart.py` — runnable end-to-end
  LLM-guided spec search session.
- `docs/user-guide/llm-guided-spec-search.md` — paper-aligned user guide.
- `docs/architecture/learning.md` — Learning primitive deep-dive covering
  routing, spec search, optimizers, and the orchestrator.
- `docs/tutorials/` — code-companion, deep-research, messaging-hub,
  scheduled-ops, and skills-workflow walkthroughs.
- `src/openjarvis/agents/hybrid/registry/*.toml` — 35-cell registry of
  paradigm × benchmark × model experiments.

### Migration from 0.x

- **`learning/distillation/` is now `learning/spec_search/`.** The
  subsystem was renamed to match the LLM-guided spec search semantics
  documented in the companion paper. Update any imports
  (`from openjarvis.learning.distillation.*` →
  `from openjarvis.learning.spec_search.*`). The `jarvis distillation`
  CLI command is removed; use `spec_search`-prefixed config keys instead.
- **`_third_party.toml` no longer ships default paths.** Set
  `HERMES_AGENT_PATH` and `OPENCLAW_PATH` env vars to point at your
  local checkouts before running the framework-comparison harness;
  missing or empty paths now raise `ThirdPartyNotFoundError` with an
  actionable hint.
- **Engine `generate_full` return shape extended.**
  `JarvisAgentBackend.generate_full` and `JarvisDirectBackend.generate_full`
  now return the spec §6.2 extended fields (`energy_joules`,
  `peak_power_w`, `tool_calls`, `turn_count`, `framework`,
  `framework_commit`, `error`). Existing callers that didn't read these
  fields are unaffected; new callers can rely on cross-framework parity.

### Fixed

- **Trace metadata flow** — `ToolResult.metadata` now propagates through `TOOL_CALL_END` event to `TraceStep.metadata` (was silently dropped at the event-bus boundary).
- **TaintSet JSON serialization** — `ToolExecutor._json_safe_metadata()` filters non-JSON-serializable values (like `TaintSet`) from event payloads before they reach `TraceStore`.
- **Non-dict YAML frontmatter** — source resolvers handle `yaml.safe_load()` returning a string instead of a dict (discovered on real OpenClaw imports).
- **OpenClaw category/name queries** — `jarvis skill install openclaw:owner/slug` now correctly splits into category + name match.
- **SkillDiscovery trace compatibility** — `_extract_tool_sequence` reads from `step.input["tool"]` (the actual `TraceStep` format), not the nonexistent `step.tool_name` attribute.
- **LearningOrchestrator skill trigger** — `_maybe_optimize_skills` runs BEFORE the SFT-data short-circuit (skills are tagged via trace metadata, not mined as SFT pairs).
- **PinchBenchScorer constructor** — `SkillBenchmarkRunner` constructs `PinchBenchScorer(judge_backend, model)` instead of no-args.
- **EvalRunner results access** — reads per-task data from `eval_runner.results` property, not nonexistent `summary.results`.
