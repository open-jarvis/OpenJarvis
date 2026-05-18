# Evaluations

The OpenJarvis evaluation framework (`openjarvis-evals`) measures model **correctness and accuracy** on academic datasets. It is a separate package from the main OpenJarvis library and is designed specifically for research workflows where you need reproducible, dataset-driven quality assessments.

!!! info "Evals vs. Benchmarks"
    OpenJarvis has two distinct measurement systems that complement each other:

    | System | Package | Measures | Entry Point |
    |--------|---------|----------|-------------|
    | **Evaluations** | `openjarvis-evals` | Correctness on academic datasets (accuracy, pass rate) | `openjarvis-eval` |
    | **Benchmarks** | `openjarvis` | Engine performance (latency, throughput) | `jarvis bench` |

    Use evaluations to answer "does this model get the right answer?" and benchmarks to answer "how fast does this model respond?". See the [Benchmarks guide](benchmarks.md) for the performance measurement system.

---

> **Tip:** LLM-guided spec search uses this same eval infrastructure to gate edits against your personal benchmark. See [LLM-guided spec search](llm-guided-spec-search.md).

## Installation

The evaluation framework is a standalone package in the `evals/` directory. Install it alongside OpenJarvis:

```bash
uv sync --extra eval
```

This installs the `openjarvis-eval` CLI entry point and all required dependencies (`datasets`, `huggingface-hub`, `tqdm`, `rich`).

!!! note "Python version requirement"
    Python 3.10 requires the `tomli` package for TOML config parsing. The `evals/pyproject.toml` includes this as a conditional dependency, so it is installed automatically.

---

## Datasets

The framework ships with **30+ datasets** covering academic reasoning, agentic tasks, retrieval, conversation quality, and practical use-case benchmarks. Datasets are grouped by category below.

### Use-Case Benchmarks

These benchmarks evaluate models on practical tasks that mirror real OpenJarvis use cases.

| Dataset | Key | Description |
|---------|-----|-------------|
| **CodingAssistant** | `coding_assistant` | Bug-fix coding assistant (test-based) |
| **SecurityScanner** | `security_scanner` | Security vulnerability scanner |
| **DailyDigest** | `daily_digest` | Daily briefing generation |
| **DocQA** | `doc_qa` | Document-grounded QA with citations |
| **BrowserAssistant** | `browser_assistant` | Web research with fact verification |
| **EmailTriage** | `email_triage` | Email triage classification + draft |
| **MorningBrief** | `morning_brief` | Morning briefing generation |
| **ResearchMining** | `research_mining` | Research synthesis + accuracy |
| **KnowledgeBase** | `knowledge_base` | Document-grounded retrieval QA |
| **CodingTask** | `coding_task` | Function-level code generation |

### Academic Benchmarks

These benchmarks measure reasoning and knowledge on established academic datasets.

| Dataset | Key | Category | Description |
|---------|-----|----------|-------------|
| **SuperGPQA** | `supergpqa` | reasoning | Graduate-level multiple-choice across scientific disciplines |
| **GPQA** | `gpqa` | reasoning | Graduate-level MCQ (Diamond, Extended, Main variants) |
| **MMLU-Pro** | `mmlu-pro` | reasoning | Enhanced MMLU multiple-choice |
| **MATH-500** | `math500` | reasoning | Competition-level math problems |
| **NaturalReasoning** | `natural-reasoning` | reasoning | Natural language reasoning |
| **HLE** | `hle` | reasoning | Humanity's Last Exam hard challenges |
| **SimpleQA** | `simpleqa` | chat | Short-form factual question answering |
| **IPW** | `ipw` | chat | Intelligence Per Watt mixed benchmark |

### Agent Benchmarks

These benchmarks test multi-step agent capabilities including tool use, code generation, and long-horizon planning.

| Dataset | Key | Category | Description |
|---------|-----|----------|-------------|
| **GAIA** | `gaia` | agentic | Multi-step tasks with file I/O, calculations, web lookup |
| **SWE-bench** | `swebench` | agentic | Real-world GitHub code patches |
| **SWEfficiency** | `swefficiency` | agentic | Software optimization tasks |
| **TerminalBench** | `terminalbench` | agentic | Terminal-based task completion |
| **TerminalBench Native** | `terminalbench-native` | agentic | TerminalBench with native Docker execution |
| **TerminalBench V2.1** | `terminalbench-v2.1` | agentic | TB v2.1 Harbor-style Docker tasks |
| **LifelongAgent** | `lifelong-agent` | agentic | Sequential task learning across sessions |
| **PaperArena** | `paperarena` | agentic | Scientific paper analysis |
| **DeepPlanning** | `deepplanning` | agentic | Shopping constraint planning |
| **LogHub** | `loghub` | agentic | Log anomaly detection |
| **AMA-Bench** | `ama-bench` | agentic | Agent memory assessment |
| **WebChoreArena** | `webchorearena` | agentic | Web chore tasks |
| **WorkArena** | `workarena` | agentic | WorkArena++ enterprise workflows |

### Retrieval Benchmarks

| Dataset | Key | Category | Description |
|---------|-----|----------|-------------|
| **FRAMES** | `frames` | rag | Multi-hop factual retrieval across Wikipedia articles |

### Conversation Benchmarks

| Dataset | Key | Category | Description |
|---------|-----|----------|-------------|
| **WildChat** | `wildchat` | chat | Real user conversation quality (pairwise LLM judge) |

---

### Dataset Details

**SuperGPQA** is a large-scale multiple-choice benchmark spanning graduate-level questions across scientific disciplines. Each sample has a question, a set of lettered options, and a reference answer letter.

**GAIA** is an agentic benchmark requiring models to complete multi-step tasks that may involve file reading, calculations, and web lookup. Questions are drawn from the 2023 GAIA challenge set.

**FRAMES** tests multi-hop factual retrieval. Each question requires synthesizing information across multiple Wikipedia articles, making it a strong probe of retrieval-augmented generation capability.

**WildChat** uses real user conversations filtered to English single-turn exchanges. The reference answer is the original assistant response from the dataset; the model under evaluation is compared against it by an LLM judge.

!!! tip "GAIA dataset access"
    The GAIA dataset requires a HuggingFace account and acceptance of the dataset's terms of use. The loader downloads the full dataset snapshot on first use and caches it at `~/.cache/gaia_benchmark/`. Subsequent runs use the local cache.

---

## Use-Case Eval Configs

The framework includes two pre-built configs for evaluating models on the five core use-case benchmarks (coding_assistant, security_scanner, daily_digest, doc_qa, browser_assistant).

### Cloud models

```bash
uv run python -m openjarvis.evals --config src/openjarvis/evals/configs/use_case_v2_cloud.toml
```

This config evaluates **6 cloud models** (Claude Opus 4.6, Claude Haiku 4.5, Gemini 3.1 Pro, Gemini 3.1 Flash Lite, GPT-5.4, GPT-5 Mini) against all 5 use-case benchmarks with 30 samples each, producing a 6x5 = 30-run matrix. Results are written to `results/use-cases-v2-cloud/`.

### Local models

```bash
uv run python -m openjarvis.evals --config src/openjarvis/evals/configs/use_case_v2_local.toml
```

This config evaluates **5 local models** via Ollama (Qwen3.5 122B-A10B, GPT-OSS 120B, GLM4, Qwen3.5 35B-A3B, GLM-4.7-Flash) against the same 5 benchmarks, producing a 5x5 = 25-run matrix. Uses 2 workers (suitable for single-GPU setups). Results are written to `results/use-cases-v2-local/`.

!!! tip "Customizing use-case evals"
    Copy one of the `use_case_v2_*.toml` configs and modify the `[[models]]` entries to evaluate your own models. The five use-case benchmarks use synthetic datasets (no HuggingFace download required) and run quickly with 30 samples each.

---

## Inference Backends

Every evaluation run routes model calls through one of two backends:

| Backend | Key | Description |
|---------|-----|-------------|
| **jarvis-direct** | `jarvis-direct` | Engine-level inference via `SystemBuilder`. Works for local (Ollama, vLLM, llama.cpp) and cloud models. |
| **jarvis-agent** | `jarvis-agent` | Agent-level inference with tool calling. Uses `JarvisSystem.ask()` with the specified agent and tools. |

Use `jarvis-direct` for most evaluations. Use `jarvis-agent` when the benchmark requires tool use — for example, GAIA tasks that reference files that must be read with `file_read`, or arithmetic tasks that benefit from `calculator`.

---

## CLI Usage

### List available benchmarks and backends

```bash
openjarvis-eval list
```

Output:

```
Benchmarks:
  supergpqa    [reasoning  ] SuperGPQA multiple-choice
  gaia         [agentic    ] GAIA agentic benchmark
  frames       [rag        ] FRAMES multi-hop RAG
  wildchat     [chat       ] WildChat conversation quality

Backends:
  jarvis-direct    Engine-level inference (local or cloud)
  jarvis-agent     Agent-level inference with tool calling
```

### Run a single benchmark

```bash
# Evaluate qwen3:8b on SuperGPQA (engine-level, 10 samples default)
openjarvis-eval run -b supergpqa -m qwen3:8b

# Evaluate GPT-4o on GAIA using the agent backend with tools
openjarvis-eval run -b gaia -m gpt-4o --backend jarvis-agent \
    --agent orchestrator --tools calculator,file_read -n 50

# Run FRAMES with vLLM engine, write output to a file
openjarvis-eval run -b frames -m llama3:70b -e vllm \
    -o results/frames_llama70b.jsonl

# Run WildChat with a higher temperature for chat quality
openjarvis-eval run -b wildchat -m qwen3:8b --temperature 0.7 -n 100
```

#### Full option reference

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--config` | `-c` | path | — | TOML config file; when provided, `-b` and `-m` are not required |
| `--benchmark` | `-b` | choice | required* | `supergpqa`, `gaia`, `frames`, or `wildchat` |
| `--backend` | | choice | `jarvis-direct` | `jarvis-direct` or `jarvis-agent` |
| `--model` | `-m` | str | required* | Model identifier (e.g., `qwen3:8b`, `gpt-4o`) |
| `--engine` | `-e` | str | auto | Engine key (`ollama`, `vllm`, `cloud`, ...) |
| `--agent` | | str | `orchestrator` | Agent name for `jarvis-agent` backend |
| `--tools` | | str | `""` | Comma-separated tool names (e.g., `calculator,file_read`) |
| `--max-samples` | `-n` | int | all | Limit the number of samples evaluated |
| `--max-workers` | `-w` | int | `4` | Parallel evaluation workers |
| `--judge-model` | | str | `gpt-4o` | LLM used for judge-based scoring |
| `--output` | `-o` | path | auto-generated | Output JSONL file path |
| `--seed` | | int | `42` | Random seed for dataset shuffling |
| `--split` | | str | dataset default | Override the dataset split |
| `--temperature` | | float | `0.0` | Generation temperature |
| `--max-tokens` | | int | `2048` | Maximum output tokens |
| `--verbose` | `-v` | flag | off | Enable debug logging |

*Required when `--config` is not provided.

### Run all benchmarks at once

The `run-all` command evaluates a single model against all four benchmarks sequentially and writes results to an output directory:

```bash
openjarvis-eval run-all -m qwen3:8b

# With options
openjarvis-eval run-all -m gpt-4o -n 100 --output-dir results/gpt4o/
```

Output files are written as `{output_dir}/{benchmark}_{model-slug}.jsonl`. The model slug replaces `/` and `:` with `-`, so `qwen3:8b` becomes `qwen3-8b`.

### Summarize results

After a run, inspect a JSONL results file:

```bash
openjarvis-eval summarize results/supergpqa_qwen3-8b.jsonl
```

Output:

```
File:      results/supergpqa_qwen3-8b.jsonl
Benchmark: supergpqa
Model:     qwen3:8b
Total:     200
Scored:    198
Correct:   143
Accuracy:  0.7222
Errors:    2
```

---

## TOML Config System

For research workflows that compare multiple models across multiple benchmarks, use a TOML config file to define the evaluation as a **models x benchmarks matrix**. This is the recommended approach for systematic evaluations.

### Running from a config

```bash
openjarvis-eval run --config src/openjarvis/evals/configs/full-suite.toml
```

When `--config` is provided, the `-b`/`--benchmark` and `-m`/`--model` options are not required. All settings come from the config file. The CLI expands the matrix, prints a progress table, and writes results to the configured `output_dir`.

### Config file format

A config file has six sections: `[meta]`, `[defaults]`, `[judge]`, `[run]`, `[[models]]`, and `[[benchmarks]]`. Only `[[models]]` and `[[benchmarks]]` are required — all other sections are optional and fall back to built-in defaults.

```toml title="evals/configs/full-suite.toml"
# Suite-level metadata (optional)
[meta]
name = "full-suite-v1"
description = "Evaluate all benchmarks against production models"

# Default generation parameters (optional)
[defaults]
temperature = 0.0
max_tokens = 2048

# LLM judge configuration (optional)
[judge]
model = "gpt-4o"
temperature = 0.0
max_tokens = 1024

# Execution settings (optional)
[run]
max_workers = 4
output_dir = "results/"
seed = 42

# --- Models (one [[models]] block per model) ---

[[models]]
name = "qwen3:8b"
engine = "ollama"
temperature = 0.3    # overrides [defaults] for this model
max_tokens = 4096

[[models]]
name = "gpt-4o"
provider = "openai"  # uses cloud engine

[[models]]
name = "llama3:70b"
engine = "vllm"
temperature = 0.1

# --- Benchmarks (one [[benchmarks]] block per benchmark) ---

[[benchmarks]]
name = "supergpqa"
backend = "jarvis-direct"
max_samples = 200
split = "train"

[[benchmarks]]
name = "gaia"
backend = "jarvis-agent"
agent = "orchestrator"
tools = ["file_read", "calculator"]
max_samples = 50
judge_model = "claude-sonnet-4-20250514"  # override judge for this benchmark

[[benchmarks]]
name = "frames"
backend = "jarvis-direct"
max_samples = 100

[[benchmarks]]
name = "wildchat"
backend = "jarvis-direct"
max_samples = 150
temperature = 0.7   # override temperature for this benchmark
```

This config produces 3 models x 4 benchmarks = **12 evaluation runs**.

### Merge precedence

Settings are resolved with the following precedence, from highest to lowest:

```
benchmark-level  >  model-level  >  [defaults]  >  built-in defaults
```

For example, `temperature` is resolved as: use `[defaults].temperature` (0.0), then apply `[[models]].temperature` if set (0.3 for qwen3:8b), then override with `[[benchmarks]].temperature` if set (0.7 for wildchat). The WildChat run with qwen3:8b therefore runs at `temperature = 0.7`.

### Minimal config

A config requires only one `[[models]]` and one `[[benchmarks]]` entry:

```toml title="evals/configs/minimal.toml"
[[models]]
name = "qwen3:8b"

[[benchmarks]]
name = "supergpqa"
```

This runs SuperGPQA against qwen3:8b with all default settings. Use this as a starting point when iterating on a single model or dataset.

### Single-run config with full options

```toml title="evals/configs/single-run.toml"
[meta]
name = "single-run-example"
description = "Evaluate SuperGPQA with a single model and full configuration"

[defaults]
temperature = 0.0
max_tokens = 2048

[judge]
model = "gpt-4o"
temperature = 0.0
max_tokens = 1024

[run]
max_workers = 4
output_dir = "results/"
seed = 42

[[models]]
name = "qwen3:8b"
engine = "ollama"
temperature = 0.3
max_tokens = 4096

[[benchmarks]]
name = "supergpqa"
backend = "jarvis-direct"
max_samples = 100
split = "train"
```

---

## Config Reference

### `[meta]`

Suite-level metadata. Neither field affects evaluation behavior; both are used in CLI output and summary files.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | `""` | Suite name shown in CLI output |
| `description` | str | `""` | Human-readable description |

### `[defaults]`

Default generation parameters applied to every run unless overridden at the model or benchmark level.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `temperature` | float | `0.0` | Sampling temperature |
| `max_tokens` | int | `2048` | Maximum output tokens |

### `[judge]`

Configuration for the LLM used as a judge in GAIA, FRAMES, and WildChat scoring.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | str | `"gpt-4o"` | Judge model identifier |
| `provider` | str | `None` | Provider override (e.g., `"openai"`) |
| `temperature` | float | `0.0` | Judge sampling temperature |
| `max_tokens` | int | `1024` | Maximum judge output tokens |

!!! warning "Judge model costs"
    Every sample that requires LLM-based scoring makes a separate call to the judge model. For large runs with hundreds of samples, judge costs can exceed evaluation costs. GAIA, FRAMES, and WildChat all require a judge; SuperGPQA uses an LLM to extract the answer letter, then compares it against the reference without a separate judge call.

### `[run]`

Execution settings that apply to the entire suite.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_workers` | int | `4` | Number of parallel evaluation threads |
| `output_dir` | str | `"results/"` | Directory where JSONL and summary files are written |
| `seed` | int | `42` | Random seed for dataset shuffling |
| `telemetry` | bool | `false` | Enable GPU telemetry capture (energy, power, utilization, throughput) |
| `gpu_metrics` | bool | `false` | Enable GPU metric polling via `pynvml` (requires `pynvml` or `nvidia-ml-py`) |

### `[[models]]`

One block per model. The `name` field is required.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | required | Model identifier (e.g., `"qwen3:8b"`, `"gpt-4o"`) |
| `engine` | str | `None` | Engine key to use (`"ollama"`, `"vllm"`, `"cloud"`, ...) |
| `provider` | str | `None` | Provider override for cloud models (e.g., `"openai"`) |
| `temperature` | float | `None` | Override `[defaults].temperature` for this model |
| `max_tokens` | int | `None` | Override `[defaults].max_tokens` for this model |
| `param_count_b` | float | `0.0` | Total model parameter count in billions (for MFU/MBU computation) |
| `active_params_b` | float | `None` | Active parameters per token in billions (for MoE models; defaults to `param_count_b`) |
| `gpu_peak_tflops` | float | `0.0` | GPU peak FP16 TFLOPS (e.g., 312.0 for A100 SXM) |
| `gpu_peak_bandwidth_gb_s` | float | `0.0` | GPU peak memory bandwidth in GB/s (e.g., 2039.0 for A100 SXM) |
| `num_gpus` | int | `1` | Number of GPUs used (for tensor-parallel inference) |

### `[[benchmarks]]`

One block per benchmark. The `name` field is required.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | str | required | Benchmark key: `supergpqa`, `gaia`, `frames`, or `wildchat` |
| `backend` | str | `"jarvis-direct"` | Inference backend: `jarvis-direct` or `jarvis-agent` |
| `max_samples` | int | `None` | Limit number of samples; `None` evaluates the full dataset |
| `split` | str | `None` | Override the default dataset split |
| `agent` | str | `None` | Agent name for `jarvis-agent` backend (e.g., `"orchestrator"`) |
| `tools` | list[str] | `[]` | Tool names for `jarvis-agent` backend |
| `judge_model` | str | `None` | Override `[judge].model` for this benchmark only |
| `temperature` | float | `None` | Override temperature for this benchmark (highest precedence) |
| `max_tokens` | int | `None` | Override max tokens for this benchmark (highest precedence) |

---

## Output Format

### JSONL results file

Each completed sample is appended to the output JSONL file immediately after scoring. The file path is either specified with `-o`/`--output`, or auto-generated as `{output_dir}/{benchmark}_{model-slug}.jsonl`.

Each line is a JSON object with the following fields:

```json title="results/supergpqa_qwen3-8b.jsonl (one line per sample)"
{
  "record_id": "supergpqa-42",
  "benchmark": "supergpqa",
  "model": "qwen3:8b",
  "backend": "jarvis-direct",
  "model_answer": "The answer is C because...",
  "is_correct": true,
  "score": 1.0,
  "latency_seconds": 1.34,
  "prompt_tokens": 187,
  "completion_tokens": 12,
  "cost_usd": 0.0,
  "error": null,
  "scoring_metadata": {"reference_letter": "C", "candidate_letter": "C"},
  "ttft": 0.0,
  "energy_joules": 140792.95,
  "power_watts": 893.0,
  "gpu_utilization_pct": 47.4,
  "throughput_tok_per_sec": 36.6,
  "mfu_pct": 0.0176,
  "mbu_pct": 26.89,
  "ipw": 0.00112,
  "ipj": 0.000007
}
```

| Field | Type | Description |
|-------|------|-------------|
| `record_id` | str | Unique sample identifier |
| `benchmark` | str | Benchmark name |
| `model` | str | Model identifier |
| `backend` | str | Backend used |
| `model_answer` | str | Raw model output |
| `is_correct` | bool or null | Scoring result (`null` if unscored) |
| `score` | float or null | Numeric score (1.0 correct, 0.0 incorrect, `null` unscored) |
| `latency_seconds` | float | Inference latency |
| `prompt_tokens` | int | Input tokens consumed |
| `completion_tokens` | int | Output tokens generated |
| `cost_usd` | float | Estimated cost in USD |
| `error` | str or null | Error message if the sample failed |
| `scoring_metadata` | dict | Scorer-specific details (extracted letters, judge output, etc.) |
| `ttft` | float | Time to first token in seconds (0.0 if unavailable) |
| `energy_joules` | float | GPU energy consumed for this sample (joules) |
| `power_watts` | float | Average GPU power draw during inference (watts) |
| `gpu_utilization_pct` | float | Average GPU utilization percentage |
| `throughput_tok_per_sec` | float | Output token throughput (tokens/sec) |
| `mfu_pct` | float | Model FLOPs Utilization percentage (requires model hardware params) |
| `mbu_pct` | float | Memory Bandwidth Utilization percentage (requires model hardware params) |
| `ipw` | float | Intelligence Per Watt: `accuracy / power_watts` (0 if incorrect or no power data) |
| `ipj` | float | Intelligence Per Joule: `accuracy / energy_joules` (0 if incorrect or no energy data) |

### Summary JSON file

After all samples complete, a summary file is written alongside the JSONL at `{output_path}.summary.json`:

```json title="results/supergpqa_qwen3-8b.jsonl.summary.json"
{
  "benchmark": "supergpqa",
  "category": "reasoning",
  "backend": "jarvis-direct",
  "model": "qwen3:8b",
  "total_samples": 200,
  "scored_samples": 198,
  "correct": 143,
  "accuracy": 0.7222,
  "errors": 2,
  "mean_latency_seconds": 1.4821,
  "total_cost_usd": 0.0,
  "per_subject": {
    "chemistry": {"accuracy": 0.74, "total": 50.0, "scored": 50.0, "correct": 37.0},
    "mathematics": {"accuracy": 0.68, "total": 50.0, "scored": 49.0, "correct": 33.0}
  },
  "started_at": 1708789200.0,
  "ended_at": 1708789496.3,
  "accuracy_stats": {"mean": 0.72, "median": 1.0, "min": 0.0, "max": 1.0, "std": 0.45},
  "energy_stats": {"mean": 140792.95, "median": 135112.79, "min": 3926.17, "max": 1806568.12, "std": 156038.54},
  "power_stats": {"mean": 892.98, "median": 898.19, "min": 811.50, "max": 1104.90, "std": 42.65},
  "gpu_utilization_stats": {"mean": 47.41, "median": 47.45, "min": 42.38, "max": 56.23, "std": 2.72},
  "throughput_stats": {"mean": 36.55, "median": 37.22, "min": 26.22, "max": 45.03, "std": 5.00},
  "mfu_stats": {"mean": 0.0176, "median": 0.0179, "min": 0.0126, "max": 0.0216, "std": 0.0024},
  "mbu_stats": {"mean": 26.89, "median": 27.38, "min": 19.29, "max": 33.13, "std": 3.68},
  "ipw_stats": {"mean": 0.00113, "median": 0.00112, "min": 0.00100, "max": 0.00123, "std": 0.00005},
  "ipj_stats": {"mean": 0.00003, "median": 0.00001, "min": 0.000002, "max": 0.00021, "std": 0.00004},
  "total_energy_joules": 28158590.26
}
```

When `telemetry = true` and `gpu_metrics = true` are set in `[run]`, the summary includes `MetricStats` (mean, median, min, max, std) for every telemetry metric plus `total_energy_joules`. These stats are `null` when no values are available for that metric.

The `per_subject` breakdown groups results by the dataset's subject or category field, which varies per benchmark:

- **SuperGPQA**: `subfield`, `field`, or `discipline`
- **GAIA**: difficulty level (`level_1`, `level_2`, `level_3`)
- **FRAMES**: reasoning type(s) (e.g., `temporal`, `intersection`)
- **WildChat**: always `"conversation"`

---

## Scoring Methods

Each benchmark uses a scorer tuned to its answer format.

### SuperGPQA: LLM-assisted MCQ extraction

SuperGPQA responses are free-form text that must contain one of the valid option letters (A, B, C, D, ...). The scorer uses the judge LLM to extract the final answer letter from the model's response, then compares it against the reference letter with exact string matching.

The judge is prompted with the original problem and the model's response and asked to return only a single letter. This handles cases where the model reasons extensively before stating its final answer.

```
is_correct = extracted_letter == reference_letter
```

Scoring metadata includes: `reference_letter`, `candidate_letter`, and `valid_letters`.

### GAIA: Normalized exact match with LLM fallback

GAIA answers are typically numbers, short phrases, or comma-separated lists. The scorer applies a normalization pass before comparison:

- **Numbers**: strips `$`, `%`, `,` and converts to float for comparison
- **Lists**: splits on `,`/`;` and compares element-by-element (with per-element type detection)
- **Strings**: lowercases, strips whitespace and punctuation

If the normalized exact match fails, the scorer falls back to the judge LLM, which returns a structured response with `extracted_final_answer`, `reasoning`, and `correct: yes/no`. The LLM fallback handles cases like unit variations, alternative phrasings, and equivalent but differently-formatted answers.

### FRAMES: LLM-as-judge (factual correctness)

FRAMES uses an LLM judge that evaluates semantic equivalence between the model's answer and the ground truth. The judge receives the question, ground truth, and predicted answer, then responds with a structured verdict:

```
extracted_final_answer: <extracted answer>
reasoning: <brief explanation>
correct: yes / no
```

The scorer parses the `correct:` line and falls back to presence of `TRUE`/`FALSE` tokens if the structured format is missing.

### WildChat: Pairwise LLM comparison

WildChat does not have a single "correct" answer — it measures chat response quality. The scorer runs a **dual pairwise comparison**:

1. The judge evaluates (model answer as A, reference as B) and returns a verdict token such as `[[A>>B]]`, `[[A>B]]`, `[[A=B]]`, `[[B>A]]`, or `[[B>>A]]`.
2. The judge then evaluates (reference as A, model answer as B) and returns another verdict.

The model is considered to have passed (`is_correct = True`) if it wins or ties in either comparison. The dual comparison reduces positional bias in the judge.

The judge uses a multi-step rubric that distinguishes subjective queries (scored on correctness, helpfulness, relevance, conciseness, and creativity) from objective/technical queries (scored on correctness only).

!!! tip "Interpreting WildChat accuracy"
    A WildChat accuracy score of 0.50 means the model matched or beat the reference response in half of comparisons. Because the reference response comes from the original dataset (which may include responses from capable models), a score above 0.50 indicates strong chat quality for that sample set.

---

## Parallel Execution

The `EvalRunner` processes samples concurrently using a `ThreadPoolExecutor`. Results are flushed to the JSONL file incrementally as each sample completes, so you can inspect partial results during a long run.

```bash
# Use more workers for faster evaluation (if the engine supports concurrent requests)
openjarvis-eval run -b supergpqa -m qwen3:8b -w 8 -n 500
```

!!! warning "Worker count and engine load"
    Higher worker counts increase throughput only if the inference engine can handle concurrent requests. Local Ollama instances typically handle 1-2 concurrent requests. Cloud APIs (OpenAI, Anthropic) can handle higher concurrency. Set `-w` based on your engine's actual parallelism.

---

## See Also

- [Benchmarks](benchmarks.md) — Measure inference engine latency and throughput
- [Telemetry & Traces](telemetry.md) — Record and analyze inference metrics from production use
- [Agents](agents.md) — Configure the `OrchestratorAgent` used by `jarvis-agent` backend
- [Tools](tools.md) — Available tools for agent-backed evaluations
- [Python SDK](python-sdk.md) — Programmatic access to OpenJarvis inference and agents
