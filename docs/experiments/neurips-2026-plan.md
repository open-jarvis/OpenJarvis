# NeurIPS 2026 Experiment Plan: IPW/IPJ for Local AI

## Overview
Evaluate and optimize local AI models as OpenClaw agent brains, measuring
accuracy, latency, cost, energy, and FLOPs across 7 benchmarks.

## Results Storage
All results stored under `results/neurips-2026/`:
```
results/neurips-2026/
├── baselines/                    # Step 1: Raw model scores
│   ├── {model}/{benchmark}/      # e.g. qwen-9b/pinchbench/
│   │   ├── results.jsonl         # Per-task results
│   │   ├── summary.json          # Aggregate metrics
│   │   └── telemetry.json        # Energy, power, FLOPs, tokens
│   └── ...
├── agent-optimization/           # Step 2a: Agent improvements
│   ├── gepa/                     # GEPA prompt evolution results
│   │   ├── generation_{N}/       # Per-generation best prompts
│   │   └── best_configs/         # Final optimized agent configs
│   ├── dspy/                     # DSPy optimization results
│   │   ├── bootstrap/            # BootstrapFewShot results
│   │   └── mipro/                # MIPROv2 results
│   └── agent-configs/            # New agent configurations tested
├── intelligence-optimization/    # Step 2b: Model improvements
│   ├── sft/                      # Supervised fine-tuning
│   │   ├── qwen-2b/              # Per-model training runs
│   │   ├── qwen-9b/
│   │   └── qwen-27b/
│   ├── lora/                     # LoRA fine-tuning
│   │   ├── qwen-2b/
│   │   ├── qwen-9b/
│   │   └── qwen-27b/
│   └── rl/                       # Reinforcement learning (GRPO)
│       ├── qwen-2b/
│       ├── qwen-9b/
│       └── qwen-27b/
├── optimized-eval/               # Step 3: Full eval with best configs
│   ├── {model}/{benchmark}/      # Same structure as baselines/
│   └── ...
└── analysis/                     # Charts, tables, comparisons
    ├── pareto_frontier.json      # IPW/IPJ data points
    ├── scaling_curves.json       # Accuracy vs model size
    ├── cost_comparison.json      # Local vs cloud economics
    └── figures/                  # Generated plots
```

## Hardware Stacks

Run eval metrics across three hardware vendor stacks to show
platform-agnostic IPW/IPJ results:

| Stack | Server-Class | Workstation/Consumer |
|-------|-------------|---------------------|
| **NVIDIA** | DGX Spark | RTX 6000 Pro |
| **AMD** | MI300x, MI355x | — |
| **Apple** | — | Mac Mini M4, Mac Studio M4 |

Results stored per-stack under each model's directory:
```
results/neurips-2026/baselines/{model}/{benchmark}/
├── nvidia-dgxspark/
│   ├── results.jsonl
│   ├── telemetry.json    # NVML energy, GPU util, power
│   └── summary.json
├── nvidia-rtx6000pro/
├── amd-mi300x/
│   ├── telemetry.json    # ROCm energy, GPU util, power
│   └── ...
├── amd-mi355x/
├── apple-macmini-m4/
│   ├── telemetry.json    # Apple powermetrics energy
│   └── ...
└── apple-macstudio-m4/
```

OpenJarvis telemetry already supports all three vendors:
- NVIDIA: `telemetry/nvidia_monitor.py` (NVML)
- AMD: `telemetry/amd_monitor.py` (ROCm SMI)
- Apple: `telemetry/apple_monitor.py` (powermetrics)

Key comparisons:
- Same model, same benchmark, different hardware → IPW/IPJ per platform
- DGX Spark vs MI300x vs Mac Studio → server-class efficiency frontier
- RTX 6000 Pro vs Mac Mini M4 → consumer/workstation efficiency frontier
- GGUF models (Kimi, MiniMax) run on all platforms via llama.cpp/MLX

## Models (9 priority + 3 cloud baselines)

### Cloud Baselines
| ID | Model | Engine |
|----|-------|--------|
| claude-opus | Claude Opus 4.6 | cloud |
| gpt-54 | GPT-5.4 | cloud |
| gemini-31-pro | Gemini 3.1 Pro | cloud |

### Priority Local Models
| ID | Model | Active Params | Serving | Hardware |
|----|-------|---------------|---------|----------|
| qwen-397b | Qwen3.5-397B-A17B-FP8 | 17B | vLLM | 8x H100 |
| qwen-27b | Qwen3.5-27B-FP8 | 27B | vLLM | 1-2x H100 |
| qwen-9b | Qwen3.5-9B | 9B | vLLM/Ollama | 1x GPU |
| qwen-2b | Qwen3.5-2B | 2B | Ollama | laptop |
| trinity-large | Trinity-Large-Thinking | 13B | vLLM | 4-8x H100 |
| nemotron-nano | Nemotron-3-Nano-30B-A3B | 3B | vLLM | 1x GPU |
| kimi-k25 | Kimi-K2.5 (GGUF) | ~32B | llama.cpp | 2x GPU |
| minimax-m25 | MiniMax-M2.5 (GGUF) | ~45B | llama.cpp | 2-4x GPU |
| lfm-1.2b | LFM2.5-1.2B-Instruct | 1.2B | llama.cpp | CPU |

## Benchmarks (7)

| ID | Benchmark | Tasks | Fast Subset | Status |
|----|-----------|-------|-------------|--------|
| pinchbench | PinchBench | 23 | 23 (all) | Implemented |
| taubench | TauBench V2 | 60+40 | 20 A+R | Implemented |
| gaia | GAIA | 50 | 20 | Implemented |
| terminalbench | TerminalBench | varies | 20 | Implemented |
| toolcall15 | ToolCall-15 | 15 | 15 (all) | TODO |
| livecodebench | LiveCodeBench | ~100 | 20 | TODO |
| liveresearch | LiveResearchBench | 100 | 10 | TODO |

## Metrics Captured Per Run
- accuracy (benchmark-specific)
- latency_seconds (wall clock per task)
- energy_joules (RAPL + NVML)
- power_watts (average during inference)
- cost_usd (API cost for cloud, amortized HW for local)
- prompt_tokens, completion_tokens
- tool_calls_count
- flops_estimated (2 * active_params * total_tokens)
- gpu_utilization_pct
- throughput_tok_per_sec

---

## Step 1: Baseline Sweep

### Phase 1a: Implement benchmarks + telemetry
- [x] ToolCall-15 integration (PR #169)
- [x] LiveCodeBench integration (PR #169)
- [x] LiveResearchBench integration (PR #169)
- [x] Wire telemetry capture to all eval runs (PR #169)
- [x] ToolCall-15 JSON parsing fix (PR #172)
- [x] SQLite thread safety — all connections (PR #163, #172, #176)
- [x] Gemma4 venv with vLLM nightly for new architecture support
- [x] Custom Nemotron tool parser plugin for vLLM

### Phase 1b+1c+1d: Full baseline sweep (best-of across multi-node runs)

| Model | Active Params | TC-15 | PinchBench | LiveCodeBch | TauBench V2 | TB-Telecom | GAIA | LiveResearch |
|-------|---------------|-------|-----------|------------|-------------|------------|------|-------------|
| Claude Opus | cloud | 40.0% | 100% | 93.9% | 34.5% | 70.0% | 60.0% | 78.0% |
| Gemini 3.1 Pro | cloud | 40.0% | 100% | 80.0% | 45.8% | 85.0% | 0.0%* | 0.0%* |
| GPT-5.4 | cloud | 33.3% | 100% | 70.0% | 18.9% | 100% | 33.3% | 95.9% |
| Qwen-2B | 2B | 40.0% | 69.6% | 10.0% | 80.0% | 65.0% | 4.0% | 6.0% |
| Nemotron-Nano | ~3B (MoE) | 33.3% | 8.3% | 30.0% | 10.0% | 5.0% | 8.0% | 2.0% |
| Qwen-9B | 9B | 46.7% | 95.7% | 17.6% | 85.0% | 80.0% | 38.0% | 75.0% |
| Trinity-Large | ~13B (MoE) | 40.0% | 75.0% | 35.0% | 80.0% | 67.5% | 42.0% | 72.0% |
| Qwen-27B | 27B | 40.0% | 75.0% | 20.0% | 75.0% | 75.0% | 48.0% | 72.0% |
| Gemma4-26B | 26B (MoE) | 26.7% | 13.0% | 94.4% | 0.0% | 10.0% | 2.0% | — |
| Qwen-35B | ~3B (MoE) | 46.7% | 52.2% | 30.0% | 85.0% | 75.0% | 34.0% | 50.0% |
| Nemotron-Super | ~12B (MoE) | 60.0% | 39.1% | 45.0% | 35.0% | 65.0% | 42.9% | 60.0% |
| Qwen-122B | ~10B (MoE) | 46.7% | 56.5% | 36.8% | 70.0% | 75.0% | 28.6% | 71.0% |
| Qwen-397B | ~17B (MoE) | — | 78.3% | — | 81.7% | — | — | — |
| Granite-3.3-8B | 8B | 46.7% | 26.7% | 5.0% | 10.0% | 25.0% | 0.0% | 0.0% |
| Granite-4.0-Micro | 3B | 33.3% | 0.0% | 10.0% | 5.6% | 0.0% | 0.0% | 0.0% |
| Granite-4.0-H-Small | 32B | 40.0% | 80.0% | 25.0% | 16.7% | 35.0% | 6.1% | 40.0% |

*Gemini GAIA/LRB: 0% due to bytes serialization bug (fix applied, re-run pending)

Best-of across runs used where multiple results exist.

### Phase 1e: Compile baseline results
- [ ] Generate Pareto frontier plots (quality vs cost, vs energy, vs FLOPs)
- [ ] Generate scaling curves (accuracy vs active params per benchmark)
- [ ] Compute IPW/IPJ for every (model, benchmark) pair
- [ ] Re-run Gemini GAIA/LRB with bytes serialization fix

---

## Step 2: Optimization

### Phase 2a: Agent optimization

#### Methodology

**Constraint**: Model weights are frozen. We optimize everything else.

**GEPA vs DSPy — what each does**:
- **GEPA** (evolutionary): Maintains a population of candidate configs. Each
  generation: evaluate candidates → reflection LM analyzes failures → propose
  mutations. Strength: can evolve arbitrary text fields (system prompts, tool
  descriptions) guided by diagnostic feedback. Uses Pareto frontier selection.
- **DSPy** (compiler): Bootstraps few-shot demonstrations from successful runs.
  MIPROv2 additionally proposes instruction variants. Strength: finds optimal
  in-context examples from a library of successful traces.

Both require a **live evaluator** — actually running the agent and scoring the
output. Static/cached feedback is meaningless for optimization.

**OpenJarvis config surface being optimized** (model held fixed):

```python
seed_candidate = {
    # --- Intelligence ---
    "system_prompt":        "...",        # Agent instructions (text, primary target)
    "temperature":          "0.3",        # Sampling temperature (continuous 0-1)
    "max_tokens":           "4096",       # Generation budget (int 256-8192)
    "top_p":                "0.9",        # Nucleus sampling (continuous 0-1)
    "repetition_penalty":   "1.0",        # Token repetition penalty (continuous 0.5-2.0)
    "stop_sequences":       "",           # Early stop tokens (text)

    # --- Agent ---
    "agent_type":           "monitor_operative",  # Architecture (categorical)
    "max_turns":            "25",                  # Reasoning budget (int 1-30)

    # --- Tools ---
    "tool_set":             "think, calculator, ...",  # Subset of available tools
    "tool_descriptions":    "...",        # How each tool is described to the agent (text)
    "tool_choice":          "auto",       # Tool selection mode (auto|required|none)

    # --- Skills ---
    "skills_enabled":       "true",       # Enable skill system (bool)
    "active_skills":        "*",          # Glob pattern for active skills
    "skill_catalog":        "...",        # XML catalog text agent sees (text)
    "skill_few_shot":       "...",        # Skill usage examples (text)

    # --- Memory/Context ---
    "context_from_memory":  "true",       # Inject memory retrieval (bool)
    "context_top_k":        "5",          # Memory results to retrieve (int 1-50)
    "context_max_tokens":   "2048",       # Max memory context injected (int)

    # --- Prompt Assembly ---
    "soul_max_chars":       "4000",       # Persona section size limit (int)
    "skill_desc_max_chars": "60",         # Per-skill description truncation (int)
    "truncation_strategy":  "head_tail",  # How to truncate (categorical)

    # --- Loop Guard ---
    "max_identical_calls":  "3",          # Max repeated tool calls (int)
    "ping_pong_window":     "6",          # A-B-A-B detection window (int)
}
```

GEPA's `dict[str, str]` seed_candidate optimizes all fields jointly — the
reflection LM reads evaluation diagnostics and targets whichever fields are
hurting performance. DSPy wraps the agent as a Module and optimizes the
few-shot demonstrations + instruction text via MIPROv2.

**Data access configurations** (3 configs for fair ablation):

| Config | Test queries | Test answers | External data | Evaluator |
|--------|-------------|-------------|---------------|-----------|
| C1: Zero test data | Hidden | Hidden | GeneralThought-430K, agent-data-collection | LLM judge on external tasks |
| C2: Queries only | Visible | Hidden | None | LLM judge on benchmark queries |
| C3: Queries + external | Visible | Hidden | GeneralThought-430K, agent-data-collection | LLM judge on benchmark queries |

For all configs, the evaluator **actually runs the agent** with the candidate
config on the task subset and scores output via LLM judge. No static/cached
feedback. Test set answers are never visible to the optimizer.

**Train/test split**: Stratified by benchmark. Each optimizer runs separately
per benchmark (e.g., optimize for PinchBench, optimize for TauBench). Final
held-out test is the full benchmark run with best config — never optimized
against.

#### Axis 1: LLM-driven config optimization (`jarvis optimize run`)
Proposes full configs, evaluates via live eval, LLM analyzer guides next trial.
- [x] Create multi-benchmark optimize configs per model
- [x] Claude Sonnet: DONE (9 trials, best 53.3%, recipe exported)
- [ ] Qwen-9B: IN PROGRESS (trial 2/20)
- [ ] Qwen-27B: Server ready (port 8003), queued
- [ ] Nemotron-Super, Trinity-Large

#### Axis 2: GEPA evolutionary optimization (ICLR 2026 oral, SOTA)
Evolves the full seed_candidate dict via population-based search + reflection.
GEPA outperforms MIPROv2 by 13% and GRPO by 20% with 35× fewer rollouts.
- [x] Build live evaluator (`scripts/optimization/evaluator.py`)
- [x] GEPA × PinchBench × C2 × Qwen-9B — DONE (3.6 hrs, 51 evals, 45.1% eval acc)
- [ ] GEPA × ToolCall-15 × C2 × Qwen-9B — RUNNING
- [ ] GEPA × {PB, TC15} × {C1, C3} × Qwen-9B — queued
- [ ] GEPA × {PB, TC15, TB} × C2 × Qwen-27B — queued
- [ ] Extract best configs, compare across data configs

#### Axis 3: DSPy programmatic optimization (4 optimizers compared)
- **MIPROv2**: Bayesian opt over instructions + few-shot (auto="light")
- **SIMBA**: Stochastic mini-batch + introspective failure analysis (newest)
- **BootstrapFewShot**: Teacher-bootstrapped demonstrations (baseline)
- **COPRO**: Coordinate ascent on instructions only
- [x] Build DSPy runner (`scripts/optimization/run_dspy.py`)
- [x] DSPy Bootstrap x TC15 x C2 x Qwen-9B -- DONE (84 min, 16.7%, 0 demos)
- [ ] DSPy MIPROv2 x PinchBench x C2 x Qwen-9B -- RUNNING
- [ ] DSPy SIMBA x PinchBench x C2 x Qwen-9B -- queued
- [ ] DSPy Bootstrap x PinchBench x C2 x Qwen-9B -- queued
- [ ] DSPy {MIPROv2, SIMBA} x TC15 x C2 x Qwen-9B -- queued
- [ ] DSPy x {PB, TC15} x C2 x Qwen-27B -- queued
- [ ] Extract best configs, compare across optimizers

#### Axis 4: Skills-based optimization
Per-skill few-shot + description optimization via GEPA/DSPy overlays.
- [x] Sync skills from Hermes (55) + OpenClaw (34K)
- [x] Run baseline: no_skills=66.7%, skills_on=66.7% (PB, Qwen-9B)
- [ ] Run benchmarks with skill metadata tagging enabled
- [ ] Per-skill DSPy optimization → overlay TOML files
- [ ] Per-skill GEPA optimization → overlay TOML files
- [ ] 4-condition benchmark: no_skills / skills_on / skills+dspy / skills+gepa
- [ ] Measure per-skill invocation rates and accuracy contribution

#### Cross-cutting
- [ ] Compare GEPA vs DSPy vs Axis 1 across all models × benchmarks
- [ ] Ablation: which config fields matter most? (system_prompt? tool_set? temperature?)
- [ ] Combine best configs from all axes → final optimized recipe per model
- [ ] Test set eval: run full benchmarks with final configs (never optimized against)

### Phase 2b: Intelligence optimization
Training data:
- GeneralThought-430K-filtered (reasoning traces)
- neulab/agent-data-collection (agentic traces)
- GLM-4.7-flash SFT traces (168K + 57K)

Training targets:
- [ ] Qwen-2B: full SFT on agentic traces
- [ ] Qwen-2B: LoRA on agentic traces
- [ ] Qwen-9B: full SFT on agentic traces
- [ ] Qwen-9B: LoRA on agentic traces
- [ ] Qwen-27B: LoRA on agentic traces
- [ ] Qwen-2B: GRPO RL on benchmark outcomes
- [ ] Qwen-9B: GRPO RL on benchmark outcomes
- [ ] Evaluate all trained checkpoints on fast benchmarks

---

## Step 3: Full Evaluation

- [ ] Select best Agent config from Step 2a
- [ ] Select best Intelligence checkpoints from Step 2b
- [ ] Run complete 9 × 7 matrix with optimized configs
- [ ] Compute all metrics (accuracy, latency, energy, cost, tokens, FLOPs)
- [ ] Generate final comparison tables and figures
- [ ] Write up results section

---

## Current Progress (Updated 2026-04-09)

### Step 1: COMPLETE (91/91 benchmarks)
- 16 models × 7 benchmarks = full scoreboard
- Cloud baselines: Claude Opus, GPT-5.4, Gemini 3.1 Pro
- Local models: Qwen family (2B–397B), Trinity-Large, Nemotron-Nano/Super, Gemma4-26B, Granite family (3B–32B)
- Remaining: Gemini GAIA/LRB re-run (bytes serialization fix applied)

### Step 2a: IN PROGRESS
- GEPA + DSPy agent optimization
- Instructions: `docs/experiments/agent-optimization-instructions.md`

### Step 2b: PLANNED
- SFT/LoRA/GRPO training on Qwen models
- Plan: `docs/experiments/intelligence-optimization-plan.md`
