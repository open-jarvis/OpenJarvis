# Distillation pipeline

Four numbered scripts. One config file. Each step is callable on its own.

```
plan.json files                                                     baseline summaries
       │                                                                   │
       ▼                                                                   ▼
1_gather_consensus_edits.py ──► consensus_edits.json               ┌──────────────┐
                                       │                            │              │
                                       ▼                            │              │
                              2_apply_consensus_edits.py            │              │
                                       │                            │              │
                                       ▼                            │              │
                              distilled TOML configs ──► 3_run_evals.py ──► distilled summaries
                                                                     │              │
                                                                     ▼              ▼
                                                           4_compare_results.py ◄──┘
                                                                     │
                                                                     ▼
                                                             comparison.json
```

Filename prefix = run order. `1_` runs first, `4_` runs last. Step 3 runs
twice (once for `--mode baseline`, once for `--mode distilled`).

## The matrix

`pipeline_matrix.toml` is the single source of truth. It lists:

* `[[applications]]` — student models (size, slug, hf_name, vllm_port).
* `[[experiments]]` — benchmarks (name, backend, baseline_temp, tools, etc.).
* `[paths]` and `[runner]` — where things live.

To add a model, append an `[[applications]]` block. To add a benchmark, append
an `[[experiments]]` block. **Nothing else needs to change.**

## The four scripts

### 1. `1_gather_consensus_edits.py`

Walks `~/.openjarvis/learning/sessions/*/plan.json`, counts votes per
`(op, target, payload-value)` tuple, applies a plurality threshold, writes
`consensus_edits.json`.

```bash
python 1_gather_consensus_edits.py --min-votes 5 --min-majority 0.4
```

If you don't have access to the sessions directory (e.g. running on a
different machine), pass the snapshot we ship in `data/`:

```bash
python 1_gather_consensus_edits.py --tallies-file data/m1_vote_tallies.json
```

### 2. `2_apply_consensus_edits.py`

Reads the matrix and the consensus edits, writes one distilled TOML per
`(application × experiment)` cell to `paths.distilled_configs_dir`.

```bash
python 2_apply_consensus_edits.py
```

Experiments marked `is_control = true` get a TOML, but with the consensus
edits *not* applied (so direct/coding/reasoning benchmarks act as controls).
Non-agent experiments also bypass the consensus edits, since the agent layer
is where the edits land.

### 3. `3_run_evals.py`

Same script runs both baseline and distilled — it just picks a different
config dir + results dir based on `--mode`.

```bash
python 3_run_evals.py --mode baseline                         # all baselines
python 3_run_evals.py --mode distilled                        # all distilled
python 3_run_evals.py --mode distilled --apps 9b              # one app
python 3_run_evals.py --mode distilled --experiments gaia,pinchbench
python 3_run_evals.py --mode distilled --force                # rerun completed
python 3_run_evals.py --mode distilled --dry-run              # print plan only
```

It is resumable (skips cells whose `summary.json` reports
`scored_samples > 0`), checks vLLM health for the apps in the plan, and runs
in `priority` order from the matrix (agent benchmarks first by default).

### 4. `4_compare_results.py`

Reads `*.summary.json` from both result trees and writes
`comparison.json` plus a per-cell + per-kind table to stdout. **No baseline
numbers are hard-coded** — both sides come from disk.

```bash
python 4_compare_results.py
```

### `run_pipeline.sh` (orchestrator)

Thin wrapper that runs steps 1→4 in order. Useful for end-to-end runs;
not required for normal day-to-day work where you'll typically iterate on one
step at a time.

```bash
bash run_pipeline.sh                                  # full pipeline
bash run_pipeline.sh --skip-baseline                  # baseline already run
bash run_pipeline.sh --tallies-file data/m1_vote_tallies.json
```

## Replaces

| Old                                  | New                                                              |
|--------------------------------------|------------------------------------------------------------------|
| `m2_create_distilled_configs.py`     | `1_gather_consensus_edits.py` + `2_apply_consensus_edits.py`     |
| `m2_run_distilled_evals.sh`          | `3_run_evals.py` (Python; same logic, no duplicated bash)        |
| `m2_collect_results.py`              | `4_compare_results.py` (no hard-coded Step 1 baseline numbers)   |
| (none — analysis was off-tree)       | `1_gather_consensus_edits.py`                                    |
