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

## Models (12 priority + 3 cloud baselines)

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
| nemotron-nano-4b-fp8 | Nemotron-3-Nano-4B-FP8 | 4B | vLLM | 1x GPU |
| gemma-4-e4b | Gemma 4 E4B IT | 4B | vLLM/Ollama | 1x GPU |
| qwen-4b | Qwen3.5-4B | 4B | vLLM/Ollama | 1x GPU |

## Benchmarks (7)

| ID | Benchmark | Tasks | Fast Subset | Status |
|----|-----------|-------|-------------|--------|
| pinchbench | PinchBench | 23 | 23 (all) | Implemented |
| taubench | TauBench V2 | 60+40 | 20 A+R | Implemented |
| gaia | GAIA | 50 | 20 | Implemented |
| terminalbench | TerminalBench | varies | 20 | Implemented |
| toolcall15 | ToolCall-15 | 15 | 15 (all) | Implemented |
| livecodebench | LiveCodeBench | ~100 | 20 | Implemented |
| liveresearchbench | LiveResearchBench | 100 | 10 | Implemented |

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

### Phase 1a: Implement missing benchmarks
- [ ] ToolCall-15 integration
- [ ] LiveCodeBench integration
- [ ] LiveResearchBench integration
- [ ] Wire telemetry capture to all eval runs

### Phase 1b: Run cloud baselines (no GPU needed)
- [x] Claude Opus 4.6
  - [ ] PinchBench
  - [ ] TauBench
  - [ ] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [ ] LiveCodeBench
  - [ ] LiveResearchBench
- [x] GPT-5.4
  - [ ] PinchBench
  - [ ] TauBench
  - [ ] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [ ] LiveCodeBench
  - [ ] LiveResearchBench
- [x] Gemini 3.1 Pro
  - [ ] PinchBench
  - [ ] TauBench
  - [ ] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [ ] LiveCodeBench
  - [ ] LiveResearchBench

### Phase 1c: Run local models (GPU required)
- [ ] Qwen-397B
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [x] LiveResearchBench
  - [x] DeepResearch
- [ ] Qwen-27B
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [ ] LiveResearchBench
  - [ ] DeepResearch
- [ ] Qwen-9B 
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [ ] LiveResearchBench
  - [x] DeepResearch
- [ ] Qwen-2B
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [x] LiveResearchBench
  - [x] DeepResearch
- [ ] Qwen-4B
  - [ ] PinchBench
  - [ ] TauBench
  - [ ] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [ ] LiveCodeBench
  - [ ] LiveResearchBench
  - [ ] DeepResearch
- [ ] Trinity-Large
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [x] LiveResearchBench
  - [x] DeepResearch
- [ ] Nemotron-Nano-30B
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [x] LiveResearchBench
  - [x] DeepResearch
- [ ] Nemotron-Nano-4B-FP8
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [x] LiveResearchBench
  - [x] DeepResearch
- [ ] Kimi-K2.5
  - [ ] PinchBench
  - [ ] TauBench
  - [ ] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [ ] LiveCodeBench
  - [ ] LiveResearchBench
  - [ ] DeepResearch
- [ ] MiniMax-M2.5
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [x] LiveResearchBench
  - [x] DeepResearch
- [ ] LFM-1.2B
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [x] LiveCodeBench
  - [ ] LiveResearchBench
  - [x] DeepResearch
- [ ] Gemma-4-E4B (has consistency issues in tool calls)
  - [x] PinchBench
  - [x] TauBench
  - [x] GAIA
  - [ ] TerminalBench
  - [x] ToolCall-15
  - [x] LiveCodeBench
  - [x] LiveResearchBench
  - [x] DeepResearch
- [ ] Qwen-122B - m
  - [ ] PinchBench
  - [ ] TauBench
  - [ ] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [ ] LiveCodeBench
  - [ ] LiveResearchBench
  - [ ] DeepResearch
- [ ] Qwen-35B - m
  - [ ] PinchBench
  - [ ] TauBench
  - [ ] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [ ] LiveCodeBench
  - [ ] LiveResearchBench
  - [ ] DeepResearch
- [ ] Nemotron-Super - m
  - [ ] PinchBench
  - [ ] TauBench
  - [ ] GAIA
  - [ ] TerminalBench
  - [ ] ToolCall-15
  - [ ] LiveCodeBench
  - [ ] LiveResearchBench
  - [ ] DeepResearch

### Phase 1d: Compile baseline results
- [ ] Generate Pareto frontier plots (quality vs cost, vs energy, vs FLOPs)
- [ ] Generate scaling curves (accuracy vs active params per benchmark)
- [ ] Compute IPW/IPJ for every (model, benchmark) pair

---

## Step 2: Optimization

### Phase 2a: Agent optimization
- [ ] GEPA: evolve system prompts for monitor_operative on fast benchmarks
- [ ] GEPA: evolve system prompts for native_openhands on fast benchmarks
- [ ] DSPy BootstrapFewShot: optimize few-shot examples per benchmark
- [ ] DSPy MIPROv2: optimize full prompt pipeline
- [ ] Agent architecture search: test new agent configs
- [ ] Tool selection optimization: find minimal effective tool sets
- [ ] Evaluate optimized agents on all 9 models × fast benchmarks

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

## Current Progress

### Completed
- PinchBench harness: fixed and validated (PR #124, #139, #140)
- TauBench V2 native integration (PR #162)
- tool_choice + SQLite fixes (PR #163)
- Gemini thought_signature support
- Nemotron SGLang serving

### In Progress
- Telemetry wiring: TODO

### Blocked
- Qwen 397B telecom + GAIA: needs 8 GPUs
- Trinity-Large: not yet served
- Small models (2B, 9B): configs not yet created
- GGUF models (Kimi, MiniMax): need llama.cpp/Ollama serving setup
