# Agent Optimization (Step 2a) — Experiment Design & Instructions

## Overview

Optimize OpenJarvis agent performance **without changing model weights**.
Three optimizer approaches (GEPA, DSPy, LLM-driven), three data access
configurations, run per (model, benchmark) pair.

## GEPA vs DSPy — Key Differences

| | GEPA | DSPy |
|---|---|---|
| **Mechanism** | Evolutionary: population → evaluate → reflection LM analyzes failures → propose mutations | Compiler: bootstrap demos from teacher runs → select best few-shot subset |
| **Optimizes** | Free-form text fields (system prompt, tool descriptions, skill catalog) + structured params jointly via `dict[str, str]` | Few-shot demonstrations (BootstrapFewShot) + instructions (MIPROv2) |
| **Core strength** | Guided text evolution — reflection LM reads diagnostics and targets specific fields | Finds optimal in-context examples from successful traces |
| **Evaluator** | `evaluator(candidate, example) → score` — must run agent live | `metric(example, prediction, trace) → score` — must run program live |
| **Config** | `GEPAConfig(engine=EngineConfig(max_metric_calls=N), reflection=ReflectionConfig(reflection_lm=...))` | `BootstrapFewShotWithRandomSearch(metric=..., max_bootstrapped_demos=4, num_candidate_programs=16)` or `MIPROv2(metric=..., prompt_model=..., task_model=...)` |

Both require a **live evaluator** that actually runs the agent and scores output.
Static/cached feedback is meaningless.

## Config Surface Being Optimized

Model weights are frozen. Everything else is fair game:

```python
seed_candidate = {
    # --- Intelligence (generation parameters) ---
    "system_prompt":        "...",         # Agent instructions (text — primary target)
    "temperature":          "0.3",         # Sampling temperature (continuous 0.0-1.0)
    "max_tokens":           "4096",        # Generation budget (int 256-8192)
    "top_p":                "0.9",         # Nucleus sampling (continuous 0.0-1.0)
    "repetition_penalty":   "1.0",         # Token repetition penalty (continuous 0.5-2.0)
    "stop_sequences":       "",            # Early stop tokens (text, comma-separated)

    # --- Agent (architecture & behavior) ---
    "agent_type":           "monitor_operative",  # Architecture (categorical)
    "max_turns":            "25",                  # Reasoning iterations (int 1-30)

    # --- Tools (availability & presentation) ---
    "tool_set":             "think, calculator, code_interpreter, ...",
    "tool_descriptions":    "...",         # How each tool is described to agent (text)
    "tool_choice":          "auto",        # Tool selection mode (auto|required|none)

    # --- Skills (composable workflows) ---
    "skills_enabled":       "true",        # Enable skill system (bool)
    "active_skills":        "*",           # Glob pattern for active skills
    "skill_catalog":        "...",         # XML catalog text agent sees (text)
    "skill_few_shot":       "...",         # Skill usage examples (text)

    # --- Memory/Context (retrieval injection) ---
    "context_from_memory":  "true",        # Inject memory context (bool)
    "context_top_k":        "5",           # Number of memory results (int 1-50)
    "context_max_tokens":   "2048",        # Max memory tokens injected (int)

    # --- Prompt Assembly (prompt engineering knobs) ---
    "soul_max_chars":       "4000",        # Persona section budget (int)
    "skill_desc_max_chars": "60",          # Per-skill description truncation (int)
    "truncation_strategy":  "head_tail",   # Truncation method (categorical)

    # --- Loop Guard (execution safety) ---
    "max_identical_calls":  "3",           # Max repeated tool calls before abort (int)
    "ping_pong_window":     "6",           # A-B-A-B loop detection window (int)
}
```

GEPA treats all fields as named text strings and evolves them jointly.
DSPy wraps the agent as a Module and optimizes few-shot demos + instructions.

## Data Access Configurations

Three configurations for fair ablation. **Test set answers are never visible.**

| Config | Test queries | Test answers | External data | Evaluator |
|--------|-------------|-------------|---------------|-----------|
| **C1: Zero test data** | Hidden | Hidden | GeneralThought-430K, agent-data-collection | LLM judge on external tasks |
| **C2: Queries only** | Visible | Hidden | None | LLM judge on benchmark queries |
| **C3: Queries + external** | Visible | Hidden | GeneralThought-430K, agent-data-collection | LLM judge on benchmark queries |

- C1 tests whether **general agentic ability** transfers to benchmarks
- C2 tests whether **seeing the task distribution** helps (without answer leakage)
- C3 tests **best of both** — task distribution + external training signal

## Train/Test Split

Stratified by benchmark. Each optimizer runs separately per benchmark:
- Optimize for PinchBench → test on held-out PinchBench tasks
- Optimize for ToolCall-15 → test on held-out ToolCall-15 tasks
- etc.

Within each benchmark:
- **Optimization set**: Subset of tasks used during optimization (optimizer sees queries, evaluator scores agent output via LLM judge)
- **Held-out test set**: Never used during optimization. Final eval only.

For benchmarks with enough tasks (GAIA=50, LRB=50), use 70/30 split.
For small benchmarks (PinchBench=23, TC15=15), use leave-one-out or full set
for optimization + report on the same set (note this in the paper).

## Prerequisites

```bash
# Clone and install
git clone https://github.com/open-jarvis/OpenJarvis.git && cd OpenJarvis
uv sync --extra dev --extra learning-gepa --extra learning-dspy

# Verify
uv run python -c "import gepa; import dspy; print('OK')"

# API keys (needed for reflection LM + LLM judge)
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export TAVILY_API_KEY="..."
export HF_TOKEN="..."
```

## Step 1: Serve Models (vLLM)

```bash
export HF_TOKEN="..."

# Qwen-9B on GPU 0
VLLM_ATTENTION_BACKEND=FLASH_ATTN CUDA_VISIBLE_DEVICES=0 \
    vllm serve Qwen/Qwen3.5-9B --port 8001 \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder \
    --enforce-eager --max-model-len 32768 --gdn-prefill-backend triton &

# Qwen-27B on GPUs 1-2
VLLM_ATTENTION_BACKEND=FLASH_ATTN CUDA_VISIBLE_DEVICES=1,2 \
    vllm serve Qwen/Qwen3.5-27B-FP8 --port 8002 \
    --tensor-parallel-size 2 --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder --enforce-eager \
    --max-model-len 32768 --gdn-prefill-backend triton &
```

Note: Use `VLLM_ATTENTION_BACKEND=FLASH_ATTN` and `--gdn-prefill-backend triton`
to avoid flashinfer JIT compilation issues on vLLM 0.19+.

## Step 2: Collect External Data (for C1 and C3)

```bash
# Download GeneralThought-430K (reasoning traces)
uv run python -c "
from datasets import load_dataset
ds = load_dataset('GeneralThought/GeneralThought-430K', split='train[:5000]')
ds.to_json('data/external/general_thought_5k.jsonl')
print(f'Saved {len(ds)} examples')
"

# Download agent-data-collection (agentic traces)
uv run python -c "
from datasets import load_dataset
ds = load_dataset('neulab/agent-data-collection', split='train[:5000]')
ds.to_json('data/external/agent_data_5k.jsonl')
print(f'Saved {len(ds)} examples')
"
```

## Step 3: Build the Live Evaluator

The evaluator instantiates the OpenJarvis agent with a candidate config,
runs it on a set of tasks, and scores via LLM judge. This is the critical
piece — without it, optimization is meaningless.

```python
# evaluator.py — shared by both GEPA and DSPy
from openjarvis.evals.cli import _build_backend, _build_dataset, _build_judge_backend, _build_scorer
from openjarvis.evals.core.runner import EvalRunner
from openjarvis.evals.core.types import RunConfig

def evaluate_candidate(candidate: dict, benchmark: str, model: str,
                       max_samples: int = 15, engine_key: str = "vllm") -> float:
    """Run the agent with candidate config and return accuracy score."""
    run_config = RunConfig(
        benchmark=benchmark,
        backend="jarvis-agent",
        model=model,
        max_samples=max_samples,
        temperature=float(candidate.get("temperature", 0.3)),
        max_tokens=int(candidate.get("max_tokens", 4096)),
        judge_model="gpt-5-mini-2025-08-07",
        engine_key=engine_key,
        agent_name=candidate.get("agent_type", "monitor_operative"),
        tools=candidate.get("tool_set", "").split(", "),
        system_prompt=candidate.get("system_prompt", ""),
        max_turns=int(candidate.get("max_turns", 25)),
        output_path=f"/tmp/eval_{benchmark}_{hash(str(candidate)) % 10000}.jsonl",
    )

    dataset = _build_dataset(benchmark)
    backend = _build_backend(run_config.backend, run_config.engine_key,
                             run_config.agent_name, run_config.tools,
                             model=model, max_turns=run_config.max_turns)
    judge = _build_judge_backend(run_config.judge_model)
    scorer = _build_scorer(benchmark, judge, run_config.judge_model)

    try:
        runner = EvalRunner(run_config, dataset, backend, scorer)
        summary = runner.run()
        return summary.accuracy
    finally:
        backend.close()
        judge.close()
```

## Step 4: Run GEPA Optimization

```python
from gepa.optimize_anything import optimize_anything, GEPAConfig
from evaluator import evaluate_candidate

# Seed candidate — starting config
seed = {
    "system_prompt":      "You are a precise AI agent...",
    "temperature":        "0.3",
    "max_tokens":         "4096",
    "top_p":              "0.9",
    "repetition_penalty": "1.0",
    "agent_type":         "monitor_operative",
    "max_turns":          "25",
    "tool_set":           "think, calculator, code_interpreter, web_search, file_read, file_write, shell_exec, http_request, apply_patch, llm",
    "tool_descriptions":  "",     # Empty = use defaults
    "tool_choice":        "auto",
    "context_top_k":      "5",
    "max_identical_calls": "3",
}

# Load benchmark queries (C2: queries only, no answers)
dataset = [{"query": q} for q in load_benchmark_queries("pinchbench")]
valset = dataset[:5]
trainset = dataset[5:]

# GEPA evaluator — runs the agent live
def gepa_evaluator(candidate, example):
    """Score a candidate config by running the agent on the example query."""
    return evaluate_candidate(
        candidate=candidate,
        benchmark="pinchbench",
        model="Qwen/Qwen3.5-9B",
        max_samples=1,  # Single task per eval call
    )

config = GEPAConfig()
config.engine.max_metric_calls = 100      # Budget: 100 agent runs
config.engine.display_progress_bar = True
config.reflection.reflection_lm = "anthropic/claude-sonnet-4-6"

result = optimize_anything(
    seed_candidate=seed,
    evaluator=gepa_evaluator,
    dataset=trainset,
    valset=valset,
    objective="Maximize task accuracy on agentic benchmarks (file manipulation, tool calling, web search, customer service). The agent uses tools to complete tasks.",
    background="OpenJarvis local AI agent framework. Config fields control: system_prompt (agent instructions), temperature/top_p (sampling), agent_type (architecture), max_turns (reasoning budget), tool_set (available tools), tool_choice (auto/required/none).",
    config=config,
)
```

### GEPA Batch Script

```bash
#!/bin/bash
for model in qwen-9b qwen-27b; do
    for bench in pinchbench toolcall15 taubench; do
        for data_config in C1 C2 C3; do
            echo "=== GEPA: $model × $bench × $data_config ==="
            uv run python scripts/run_gepa.py \
                --model "$model" \
                --benchmark "$bench" \
                --data-config "$data_config" \
                --max-metric-calls 100 \
                --output-dir "results/neurips-2026/agent-optimization/gepa/${model}/${bench}/${data_config}/"
        done
    done
done
```

## Step 5: Run DSPy Optimization

```python
import dspy
from evaluator import evaluate_candidate

# Configure DSPy LM (the model being optimized)
task_lm = dspy.LM("openai/Qwen/Qwen3.5-9B",
                   api_base="http://localhost:8001/v1", api_key="dummy")
# Teacher LM (for bootstrapping demos)
teacher_lm = dspy.LM("anthropic/claude-sonnet-4-6")
dspy.configure(lm=task_lm)

# Wrap OpenJarvis agent as a DSPy Module
class JarvisAgentModule(dspy.Module):
    def __init__(self):
        super().__init__()
        self.agent = dspy.ChainOfThought("task_description -> final_answer")

    def forward(self, task_description):
        return self.agent(task_description=task_description)

program = JarvisAgentModule()

# Metric: run live evaluation
def metric(example, prediction, trace=None):
    return evaluate_candidate(
        candidate={"system_prompt": "...", "agent_type": "monitor_operative", ...},
        benchmark="pinchbench",
        model="Qwen/Qwen3.5-9B",
        max_samples=1,
    )

# Option A: BootstrapFewShotWithRandomSearch
optimizer = dspy.BootstrapFewShotWithRandomSearch(
    metric=metric,
    max_bootstrapped_demos=4,
    max_labeled_demos=4,
    num_candidate_programs=10,
)
optimized = optimizer.compile(program, trainset=train_examples)

# Option B: MIPROv2 (also optimizes instructions)
optimizer = dspy.MIPROv2(
    metric=metric,
    prompt_model=teacher_lm,
    task_model=task_lm,
    max_bootstrapped_demos=4,
    max_labeled_demos=4,
    num_candidates=7,
)
optimized = optimizer.compile(program, trainset=train_examples)
```

### DSPy Batch Script

```bash
#!/bin/bash
for model in qwen-9b qwen-27b; do
    for bench in pinchbench toolcall15 taubench; do
        for data_config in C1 C2 C3; do
            for dspy_method in bootstrap mipro; do
                echo "=== DSPy $dspy_method: $model × $bench × $data_config ==="
                uv run python scripts/run_dspy.py \
                    --model "$model" \
                    --benchmark "$bench" \
                    --data-config "$data_config" \
                    --method "$dspy_method" \
                    --output-dir "results/neurips-2026/agent-optimization/dspy/${dspy_method}/${model}/${bench}/${data_config}/"
            done
        done
    done
done
```

## Step 6: Skills Optimization

```bash
# Import skills
jarvis skill sync hermes
jarvis skill sync openclaw

# Run 4-condition skill benchmark
jarvis bench skills -c all -m "Qwen/Qwen3.5-9B" -e vllm \
    -o results/neurips-2026/agent-optimization/skills/qwen-9b/

# After collecting skill-tagged traces, optimize per-skill
jarvis optimize skills --policy dspy --min-traces 5
jarvis optimize skills --policy gepa --min-traces 5

# Re-run benchmark with optimized overlays
jarvis bench skills -c skills_optimized_dspy -m "Qwen/Qwen3.5-9B" -e vllm
jarvis bench skills -c skills_optimized_gepa -m "Qwen/Qwen3.5-9B" -e vllm
```

## Step 7: Final Held-Out Test

Run full benchmarks with best config from each optimizer. **This is the
only time the full test set is evaluated — never optimized against.**

```bash
# Export best configs
uv run python scripts/export_best_configs.py \
    --gepa-dir results/neurips-2026/agent-optimization/gepa/ \
    --dspy-dir results/neurips-2026/agent-optimization/dspy/ \
    --output results/neurips-2026/agent-optimization/best_configs/

# Run final eval on full benchmarks
for config in results/neurips-2026/agent-optimization/best_configs/*.toml; do
    uv run python -m openjarvis.evals run -c "$config"
done
```

## Expected Output Structure

```
results/neurips-2026/agent-optimization/
├── gepa/
│   ├── qwen-9b/
│   │   ├── pinchbench/
│   │   │   ├── C1/                    # Zero test data
│   │   │   │   ├── generations/       # Per-generation candidates
│   │   │   │   ├── best_config.json   # Best candidate config
│   │   │   │   └── eval_log.jsonl     # Per-eval-call results
│   │   │   ├── C2/                    # Queries only
│   │   │   └── C3/                    # Queries + external
│   │   ├── toolcall15/{C1,C2,C3}/
│   │   └── taubench/{C1,C2,C3}/
│   └── qwen-27b/...
├── dspy/
│   ├── bootstrap/
│   │   ├── qwen-9b/
│   │   │   ├── pinchbench/{C1,C2,C3}/
│   │   │   │   ├── compiled_program/  # DSPy compiled module
│   │   │   │   ├── demos.json         # Selected few-shot demos
│   │   │   │   └── eval_log.jsonl
│   │   │   └── ...
│   │   └── qwen-27b/...
│   └── mipro/                         # MIPROv2 runs (same structure)
├── skills/
│   ├── qwen-9b/
│   │   ├── no_skills/
│   │   ├── skills_on/
│   │   ├── skills_optimized_dspy/
│   │   └── skills_optimized_gepa/
│   └── ...
├── best_configs/                       # Final merged configs
│   ├── qwen-9b-gepa-best.toml
│   ├── qwen-9b-dspy-best.toml
│   └── ...
└── final_eval/                         # Held-out test results
    ├── qwen-9b-gepa.jsonl
    ├── qwen-9b-dspy.jsonl
    └── ...
```

## Experiment Matrix

Per model, the full matrix is:

| Optimizer | Benchmarks | Data Configs | Variants | Total runs |
|-----------|-----------|-------------|----------|------------|
| GEPA | PB, TC15, TB | C1, C2, C3 | 1 | 9 |
| DSPy Bootstrap | PB, TC15, TB | C1, C2, C3 | 1 | 9 |
| DSPy MIPROv2 | PB, TC15, TB | C1, C2, C3 | 1 | 9 |
| Skills (4 cond.) | PB, TC15, TB | — | 4 | 12 |
| **Total per model** | | | | **39** |

× 2 models (Qwen-9B, Qwen-27B) = **78 optimization runs**

Each GEPA/DSPy run ≈ 100 live eval calls × ~2 min/call = ~3-4 hours.
Skills benchmark ≈ 30 min per condition.

## GPU Requirements

- **Per model**: 1 GPU for ≤35B params, 2 GPUs for 120B+ (TP=2)
- **Parallelism**: Run optimization for different models simultaneously on separate GPUs
- **GEPA/DSPy**: Model serving (vLLM) + API keys for reflection/teacher LM
- **Time estimate**: ~3-4 hours per (optimizer, model, benchmark, data_config) run
- **Total**: ~78 runs × 3.5 hours = ~273 GPU-hours, parallelizable to ~2 days on 8 GPUs
