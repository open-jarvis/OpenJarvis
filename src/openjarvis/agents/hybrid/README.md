# Hybrid local+cloud paradigm agents

Six paradigms ported from
[`/matx/u/aspark/hybrid-local-cloud-compute`](../../../../../) — each is
registered as a standard OpenJarvis agent so the rest of the platform
(SDK, CLI, distillation, evals) can use them like any other agent.

| Agent             | Plan shape      | Trains what?         | Workers                   |
|-------------------|-----------------|----------------------|---------------------------|
| `minions`         | reactive loop   | nothing              | 1 local + 1 cloud         |
| `conductor`       | static DAG      | (paper: 7B planner)  | up to 5 frontier+open     |
| `archon`          | static recipe   | nothing (search)     | K local + cloud rank/fuse |
| `advisors`        | reactive loop   | (paper: local model) | 1 local + 1 cloud         |
| `skillorchestra`  | per-query pick  | (paper: profiler)    | 1 local + 1 cloud         |
| `toolorchestra`   | reactive loop   | (paper: 8B RL)       | local + tools + LLM pool  |

Items in parentheses are what the *paper* trains. These OpenJarvis ports
are **inference-only** — none modify weights. The trained variants (advisor
RL, Orchestrator-8B, SkillOrchestra learn-phase) stay TODOs; the prompted
lower-bounds get you 80-90% of the headline accuracy at zero training cost.

## What's where

```
src/openjarvis/agents/hybrid/
├── _base.py          LocalCloudAgent ABC + SDK helpers
├── _prices.py        cloud-model pricing + temp-strip quirks
├── _prompts.py       GAIA / SWE-bench answer-format instructions
├── advisors.py       executor ↔ advisor ↔ executor (3-step)
├── conductor.py      static DAG planner
├── minions.py        HazyResearch Minions wrapper
├── archon.py         Archon (generator → ranker → fuser)
├── skillorchestra.py skill-aware router
├── toolorchestra.py  prompted multi-turn tool dispatcher
├── runner.py         CLI: python -m ...hybrid.runner --cell NAME
├── registry/         <method>.toml — one cell per (bench, local, cloud, N)
└── scripts/
    └── new_experiment.sh   scaffold a new cell, run instructions
```

The Modal-backed SWE-bench-Verified scorer is in
`src/openjarvis/evals/scorers/swebench_harness.py` (next to the existing
structural scorer).

## Quickstart

```bash
cd /matx/u/aspark/OpenJarvis
source .env                                           # API keys

# 1. Start vLLM in another shell (see CLAUDE.md for the full recipe)
#    CUDA_VISIBLE_DEVICES=0 .venv/bin/python -m vllm.entrypoints.openai.api_server \
#       --model Qwen/Qwen3.5-27B-FP8 --port 8001 ...

# 2. (Optional) for Minions: install the upstream library
.venv/bin/uv pip install -e /matx/u/aspark/hybrid-local-cloud-compute/external/minions

# 3. Run a smoke cell
.venv/bin/python -m openjarvis.agents.hybrid.runner \
    --cell minions-gaia-qwen27b-opus-3
```

Outputs land in
`$OPENJARVIS_HYBRID_EXPERIMENTS_DIR/<cell>/{results.jsonl,summary.json,config.json,logs/}`
(defaults to `~/.openjarvis-hybrid/experiments/`). The schema matches the
hybrid harness so the existing rescore / dashboard scripts work
unmodified.

## Adding a cell

```bash
src/openjarvis/agents/hybrid/scripts/new_experiment.sh \
    --method conductor --bench gaia \
    --local qwen3.5-27b --cloud claude-opus-4-7 --n 30
```

That appends a `[cells.<name>]` block to
`registry/conductor.toml` and prints the runner invocation.

## How good is each paradigm?

Numbers from the upstream hybrid harness
(`/matx/u/aspark/hybrid-local-cloud-compute/docs/results.md`) at full N —
GAIA val n=165, SWE-bench-Verified n=500. Local = Qwen-3.5-27B-FP8, cloud
= Opus 4.7. Cloud-only baseline: GAIA 0.570 / $1.09, SWE 0.238 / $0.95.

| paradigm           | shape                | GAIA acc / $    | SWE acc / $     | verdict                                          |
|--------------------|----------------------|-----------------|-----------------|--------------------------------------------------|
| **minions**        | reactive 1L+1C loop  | 0.576 / $0.67   | 0.276 / $0.09   | **keep** — matches cloud, ~10× cheaper on SWE    |
| **skillorchestra** | per-query router     | 0.570 / $0.02   | 0.298 / $0.05   | **keep** — cloud-tier acc at 1/50× cost          |
| conductor          | static DAG planner   | 0.503 / $0.03   | 0.296 / $0.07   | mixed — wins SWE, −7pp on GAIA                   |
| advisors           | exec ↔ advisor loop  | 0.497 / $0.02   | 0.302 / $0.07   | mixed — wins SWE, −7pp on GAIA                   |
| archon             | gen → rank → fuse    | 0.376 / $0.14   | 0.288 / $0.17   | dominated on GAIA (−19pp); only mid on SWE       |
| toolorchestra      | RL'd 8B + tool pool  | —               | —               | port lands but untested at full N (heavy infra)  |

Cell configs in `registry/` are copies of the hybrid harness's
`experiments/registry/` — same models, same N, same `method_cfg` — so
these OpenJarvis cells should reproduce the harness numbers within
noise. Until that's validated, the harness stays the authoritative
reference.
