# Distillation pipeline

End-to-end pipeline that takes a raw student model, runs a baseline eval,
seeds feedback, lets the M1 teacher propose edits, aggregates them across
sessions, applies them to fresh configs, re-evaluates, and compares.

Seven numbered scripts. One config file. Each step is callable on its own.

```
                                  ┌───────────────────┐
                                  │  pipeline_matrix  │
                                  │      .toml        │
                                  └─────────┬─────────┘
                                            │ (read by every step)
                                            ▼
1_run_baseline_eval.py ──► baseline summary.json + traces.db
            │
            ▼
2_seed_feedback.py     ──► traces.db (with judge feedback)
            │
            ▼
3_run_teacher.py       ──► ~/.openjarvis/learning/sessions/*/plan.json
            │
            ▼
4_gather_consensus_edits.py ──► consensus_edits.json
            │
            ▼
5_apply_consensus_edits.py  ──► distilled TOML configs
            │
            ▼
6_run_distilled_eval.py     ──► distilled summary.json + traces.db
            │
            ▼
7_compare_results.py        ──► comparison.json
```

Filename prefix = run order. `1_` first, `7_` last. Steps 1 and 6 are thin
wrappers around the shared `_eval_runner.py`.

## Prerequisite (one-time)

```bash
jarvis learning init
```

This sets up the checkpoint repo and `~/.openjarvis/learning/` layout the
teacher writes into.

## The matrix

`pipeline_matrix.toml` is the single source of truth. It lists:

* `[[applications]]` — student models (size, slug, hf_name, vllm_port).
* `[[experiments]]` — benchmarks (name, backend, baseline_temp, tools, etc.).
* `[paths]` and `[runner]` — where things live.

To add a model, append an `[[applications]]` block. To add a benchmark,
append an `[[experiments]]` block. **Nothing else needs to change.**

## The seven scripts

### 1. `1_run_baseline_eval.py`

Runs every (application × experiment) cell in the matrix at baseline
settings. Writes `summary.json` and `traces.db` per cell under
`paths.baseline_results_dir`. Resumable (skips cells whose summary already
reports `scored_samples > 0`).

```bash
python 1_run_baseline_eval.py
python 1_run_baseline_eval.py --apps 9b
python 1_run_baseline_eval.py --apps 9b --experiments gaia,pinchbench
python 1_run_baseline_eval.py --force                 # rerun completed
python 1_run_baseline_eval.py --dry-run               # print plan only
```

### 2. `2_seed_feedback.py`

Walks every unscored trace in the local `traces.db` and judges it with
Sonnet 4.6 using the calibration-validated prompt. Parallelized via
ThreadPoolExecutor (8 workers); idempotent (skips traces that already have
feedback). Writes a JSONL audit log alongside the db.

```bash
python 2_seed_feedback.py
```

The teacher (step 3) needs feedback to know which traces to learn from.

### 3. `3_run_teacher.py`

Triggers an on-demand learning session — the M1 teacher reads scored
traces, runs the planner, and writes one `plan.json` per session under
`~/.openjarvis/learning/sessions/<session_id>/`.

```bash
python 3_run_teacher.py
python 3_run_teacher.py --autonomy auto               # forwarded to CLI
python 3_run_teacher.py --dry-run
```

Currently shells out to `jarvis learning run`. The CLI is a stub today;
full orchestration is tracked in M1. The script's docstring also documents
the programmatic path (`DistillationOrchestrator.run(OnDemandTrigger())`).

### 4. `4_gather_consensus_edits.py`

Walks `~/.openjarvis/learning/sessions/*/plan.json`, counts votes per
`(op, target, payload-value)` tuple, applies a plurality threshold, writes
`consensus_edits.json`.

```bash
python 4_gather_consensus_edits.py --min-votes 5 --min-majority 0.4
```

If you don't have access to the sessions directory (e.g. running on a
different machine), pass the snapshot we ship in `data/`:

```bash
python 4_gather_consensus_edits.py --tallies-file data/m1_vote_tallies.json
```

### 5. `5_apply_consensus_edits.py`

Reads the matrix and the consensus edits, writes one distilled TOML per
`(application × experiment)` cell to `paths.distilled_configs_dir`.

```bash
python 5_apply_consensus_edits.py
```

Experiments marked `is_control = true` get a TOML, but with the consensus
edits *not* applied (so direct/coding/reasoning benchmarks act as
controls). Non-agent experiments also bypass the consensus edits, since
the agent layer is where the edits land.

### 6. `6_run_distilled_eval.py`

Same shape as step 1, with `--mode distilled`. Reads the distilled TOMLs
written in step 5; writes `summary.json` + `traces.db` per cell under
`paths.distilled_results_dir`.

```bash
python 6_run_distilled_eval.py
python 6_run_distilled_eval.py --apps 9b --experiments gaia
```

### 7. `7_compare_results.py`

Reads `*.summary.json` from both result trees and writes
`comparison.json` plus a per-cell + per-kind table to stdout. **No
baseline numbers are hard-coded** — both sides come from disk.

```bash
python 7_compare_results.py
```

### `run_pipeline.sh` (orchestrator)

Thin wrapper that runs steps 1→7 in order. Useful for end-to-end runs;
not required for normal day-to-day work where you'll typically iterate on
one step at a time.

```bash
bash run_pipeline.sh                                  # full pipeline
bash run_pipeline.sh --skip-baseline                  # baseline already run
bash run_pipeline.sh --skip-baseline --skip-teacher   # plan.json files exist
bash run_pipeline.sh --tallies-file data/m1_vote_tallies.json
```

## Other workflows in this directory

These live alongside the M1 pipeline but are **separate workflows** — not
part of the linear 1→7 flow.

* **`m3_hill_climb.py`** — M3: closed-loop hill climbing. Replaces M1's
  open-loop "aggregate consensus across sessions" with a per-edit
  empirical verification loop. See the script's docstring.
* **`ablation/`** — M2 ablation sweep across teachers, budgets, students,
  gates, autonomy modes, iterative variants, and transfer settings. See
  `ablation/README.md`.
