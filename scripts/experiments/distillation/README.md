# Distillation pipeline

Five small scripts. One config file. Each step is callable on its own.

```
plan.json files                                                     baseline summaries
       │                                                                   │
       ▼                                                                   ▼
gather_consensus_edits.py ──► consensus_edits.json                 ┌──────────────┐
                                       │                            │              │
                                       ▼                            │              │
                              apply_consensus_edits.py              │              │
                                       │                            │              │
                                       ▼                            │              │
                              distilled TOML configs ──► run_evals.py ──► distilled summaries
                                                                     │              │
                                                                     ▼              ▼
                                                              compare_results.py ◄──┘
                                                                     │
                                                                     ▼
                                                             comparison.json
```

## The matrix

`pipeline_matrix.toml` is the single source of truth. It lists:

* `[[applications]]` — student models (size, slug, hf_name, vllm_port).
* `[[experiments]]` — benchmarks (name, backend, baseline_temp, tools, etc.).
* `[paths]` and `[runner]` — where things live.

To add a model, append an `[[applications]]` block. To add a benchmark, append
an `[[experiments]]` block. **Nothing else needs to change.**

## The five scripts

### 1. `gather_consensus_edits.py`

Walks `~/.openjarvis/learning/sessions/*/plan.json`, counts votes per
`(op, target, payload-value)` tuple, applies a majority threshold, writes
`consensus_edits.json`.

```bash
python gather_consensus_edits.py --min-votes 10 --min-majority 0.5
```

If you don't have access to the sessions directory (e.g. running on a
different machine), pass the snapshot we ship in `data/`:

```bash
python gather_consensus_edits.py --tallies-file data/m1_vote_tallies.json
```

### 2. `apply_consensus_edits.py`

Reads the matrix and the consensus edits, writes one distilled TOML per
`(application × experiment)` cell to `paths.distilled_configs_dir`.

```bash
python apply_consensus_edits.py
```

Experiments marked `is_control = true` get a TOML, but with the consensus
edits *not* applied (so direct/coding/reasoning benchmarks act as controls).
Non-agent experiments also bypass the consensus edits, since the agent layer
is where the edits land.

### 3. `run_evals.py`

Same script runs both baseline and distilled — it just picks a different
config dir + results dir based on `--mode`.

```bash
python run_evals.py --mode baseline                         # all baselines
python run_evals.py --mode distilled                        # all distilled
python run_evals.py --mode distilled --apps 9b              # one app
python run_evals.py --mode distilled --experiments gaia,pinchbench
python run_evals.py --mode distilled --force                # rerun completed
python run_evals.py --mode distilled --dry-run              # print plan only
```

It is resumable (skips cells whose `summary.json` reports
`scored_samples > 0`), checks vLLM health for the apps in the plan, and runs
in `priority` order from the matrix (agent benchmarks first by default).

### 4. `compare_results.py`

Reads `*.summary.json` from both result trees and writes
`comparison.json` plus a per-cell + per-kind table to stdout. **No baseline
numbers are hard-coded** — both sides come from disk.

```bash
python compare_results.py
```

### 5. `run_pipeline.sh`

Thin orchestrator that runs steps 1→5 in order. Useful for end-to-end runs;
not required for normal day-to-day work where you'll typically iterate on one
step at a time.

```bash
bash run_pipeline.sh                                  # full pipeline
bash run_pipeline.sh --skip-baseline                  # baseline already run
bash run_pipeline.sh --tallies-file data/m1_vote_tallies.json
```

## Replaces

| Old                                  | New                                                         |
|--------------------------------------|-------------------------------------------------------------|
| `m2_create_distilled_configs.py`     | `gather_consensus_edits.py` + `apply_consensus_edits.py`    |
| `m2_run_distilled_evals.sh`          | `run_evals.py` (Python; same logic, no duplicated bash)     |
| `m2_collect_results.py`              | `compare_results.py` (no hard-coded Step 1 baseline numbers)|
| (none — analysis was off-tree)       | `gather_consensus_edits.py`                                 |
