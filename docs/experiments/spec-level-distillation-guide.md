# Spec-Level Distillation: Experiment Guide & Findings

## What is spec-level distillation?

A frontier "teacher" model (e.g., Claude Opus/Sonnet) examines the runtime behavior of a smaller "student" model (e.g., Qwen3.5 2B/9B/27B) inside OpenJarvis and proposes **config-level edits** — changes to agent parameters, tool selection, temperature, and routing — that improve the student without changing its weights.

"Spec-level" = we edit the **system specification** (OpenJarvis config), not the model.

---

## The short answer — does it work?

**Yes, but only when structured as an empirical hill-climb per (student, benchmark, agent) cell.** Global consensus aggregation (M1/M2) produces approximately null effects on agent benchmarks. Per-cell hill-climbing with a real feedback loop produces +15 to +25 points on cells where the model has baseline capability.

**Summary of measured results (vs reproducible-today baselines):**

| Method | Mean Δ on healthy cells | Mean Δ on floored cells | Total cells tested |
|---|---:|---:|---:|
| M1 consensus applied globally (M2) | ≈ 0 | ≈ 0 | 24 |
| Test 3: one-shot rich-context edits applied | 0 | — | 1 |
| **M3: per-cell hill-climb (this method)** | **+19.0** | +0.7 | 4 so far |

*"Healthy"* = baseline accuracy in the working range (roughly 20-90%, where the model has capability but not ceiling). *"Floored"* = baseline ≈ 0-10%, where the model fundamentally can't do the tasks.

---

## Milestones timeline

### M1 — trace-only teacher ablation (complete, ~$94)

135 experiments across 7 axes (teacher, budget, student, data-config, gate, autonomy, iterative-sessions). The teacher read student traces from `~/.openjarvis/traces.db` and proposed edits. **Orchestrator used MagicMock for student runner + judge** → no actual outcome feedback.

**Finding:** Opus beats GPT-5.4 beats Gemini on edit quality. Minimal teacher budget beats exhaustive ($0.29 vs $1.83, same edit quality). No diminishing returns through 5 iterative sessions.

### M2 — apply consensus edits, measure impact (complete, ~$100 API)

Extracted the M1 consensus edits (`temperature=0.2`, `max_turns=15`, `remove shell_exec + http_request`) and applied them as a global config. Ran 24 cells (3 students × 8 benchmarks).

**Findings:**
- **Direct benchmarks (TC15 spot-check reproducible to exact match):**
  - TauBench family catastrophic: −60 to −75 points. `temperature=0.2` breaks Qwen3.5 tool-calling reliability on multi-turn customer-service tasks.
  - LCB, LRB mostly neutral.
- **Agent benchmarks — baseline reproducibility is partial:**
  - Step 1 baselines for agent benchmarks (GAIA, DRB, PB) don't reproduce today. Systematic drift of −30 to −60 points. Root cause unknown (vLLM version? agent code? tool-calling format change?).
  - When compared against **reproducible-today** baselines, M2 distilled effects are essentially null (mean Δ ≈ −0.65).
- **One clear win:** 27B-PinchBench +26.5 (65.2 → 91.7%). `max_turns=15` on `native_openhands` + removing broken tools helped.

### M3 — per-cell hill-climb with empirical verification (in progress, ~$25 so far)

Replaced M1's global consensus aggregation with a per-cell optimization loop:

```
For each target (student, benchmark, agent):
    baseline_score = measure_today(baseline_config, k_final)
    current_config = baseline_config
    for round in 1..N:
        edit = teacher.propose_one(
            current_config,
            edit_history_with_measured_deltas,  # ← the key thing M1 lacked
            benchmark_metadata,
        )
        score_new = eval_subsample(apply(edit, current_config), k=15)
        if score_new > current_score: accept
    final_score = eval_full(current_config, k_final)
```

Every proposal is empirically tested before the next is proposed. The teacher sees measured deltas (not just traces) when picking its next edit.

**Results so far** (4 cells, each ~$5, ~1.5h):

| Cell | Baseline-today | M3 final | Δ | Dominant edits | Regime |
|---|---:|---:|---:|---|---|
| 9B-DRB | 32.0% | **56.7%** | **+24.7** | `add_tool browser_navigate + pdf_extract` | ✅ healthy |
| 9B-GAIA | 6.0% | 6.7% | +0.7 | — (teacher tried temp/tools/turns, nothing moved) | ⚠️ floor |
| 2B-PB | 6.7% | **21.7%** | **+15.0** | `set_temperature=0.1` | ✅ healthy |
| 27B-PB | 60.9% | **78.3%** | **+17.4** | `set_temperature=0.2 + set_max_turns=15` | ✅ healthy |

Mean Δ on healthy-baseline cells: **+19.0**.

---

## Key findings (ordered by importance for the paper)

### 1. Hill-climbing works reliably when the baseline has capability

Across 3 healthy-baseline cells spanning 3 student sizes (2B, 9B, 27B) and 2 agents (`native_openhands`, `monitor_operative`), M3 gained +15 to +25 points. This is the distillation effect we set out to measure.

### 2. Different cells need completely different edits

The proposer's accepted edits varied entirely by cell:

| Cell | Winning edit type | Why |
|---|---|---|
| 9B-DRB | `add_tool` (browser_navigate, pdf_extract) | Research tasks need document access; baseline tool list was missing the primary ones |
| 2B-PB | `set_temperature=0.1` | Small model benefits from determinism on multi-step tool chains |
| 27B-PB | `set_temperature=0.2 + set_max_turns=15` | Large model benefits from more turns when it's not temperature-limited |

**M1 global consensus got ONE of these right per cell at best.** The consensus prescription (`temp=0.2 + max_turns=15 + remove shell_exec`) was simultaneously the right answer for 27B-PB and the wrong answer for 9B-DRB.

### 3. Capability floors are real and detectable

At 6% baseline, 9B-GAIA did not respond to any of 4 tried edits. The teacher even chose to accept `temperature=0.1` because subsample gave 6.7% vs 6.0% — noise. **Configs cannot unlock capabilities the model doesn't have.** For cells in the 0-10% range, spec-level distillation is not a useful intervention; one needs weight training or a bigger model.

### 4. The feedback loop self-corrects

On 9B-DRB round 3, the teacher proposed `add_tool http_request`. Subsample dropped from 87.5% to 12.5%. The loop reverted, and round 4 the teacher proposed `noop` and stopped. **Without empirical verification, the bad edit would have shipped in the config.** This self-correction is the mechanism that makes per-cell optimization safer than single-shot proposal.

### 5. The teacher has proposal blind spots

On 27B-PB, M3 reached 78.3% but M2's bundled config (which included `remove_tool shell_exec + http_request`) reached 91.7%. M3 never proposed tool removal on this cell. **The proposer defaults to tuning numeric hyperparameters before exploring the tool list.** Addressed by explicit exploration nudge in the prompt (Track B test pending).

### 6. Reproducible baselines are mandatory

Jon's Step 1 agent-benchmark baselines dropped 30-60 points when we re-ran them today. Without measuring baselines in the same setup as distilled runs, every delta is confounded by infrastructure drift. M3 auto-measures baseline at k_final before hill-climb; `--trust-baseline` is an opt-out.

### 7. Trace-only teachers over-generalize; rich-context + empirical verification fixes it

M1 consensus (text only) converged on uniform edits regardless of benchmark context. Test 3 gave the teacher benchmark metadata + real student execution; its proposals diversified per cell but didn't consistently converge on correct values (1 of 4 cells proposed the right max_turns). M3 adds the critical missing ingredient: measured deltas drive the next proposal. Combined, the teacher produces cell-specific edits that empirical evaluation confirms.

---

## Models & benchmarks

### Students (vLLM, one per H100)
| Model | HF ID | Port |
|---|---|---:|
| Qwen3.5-2B | `Qwen/Qwen3.5-2B` | 8000 |
| Qwen3.5-9B | `Qwen/Qwen3.5-9B` | 8001 |
| Qwen3.5-27B-FP8 | `Qwen/Qwen3.5-27B-FP8` | 8002 |

vLLM must start with `--gdn-prefill-backend triton --trust-remote-code`.

### Teachers
| Role | Model | Where |
|---|---|---|
| Hill-climb proposer | `claude-sonnet-4-6` | M3 proposer |
| Diagnose-session teacher (M1) | `claude-opus-4-6` | best quality per M1 ablation |
| Judge | `gpt-5-mini-2025-08-07` or `claude-opus-4-5` (per benchmark) | scoring |

### Benchmarks
| Benchmark | CLI | Backend | Agent |
|---|---|---|---|
| ToolCall-15 | `toolcall15` | jarvis-direct | — |
| PinchBench | `pinchbench` | jarvis-agent | `native_openhands` |
| TauBench V2 | `taubench` (split=airline,retail) | jarvis-direct | — |
| TauBench V2 Telecom | `taubench` (split=telecom) | jarvis-direct | — |
| GAIA | `gaia` | jarvis-agent | `monitor_operative` |
| DeepResearchBench | `liveresearch` / `deepresearch` | jarvis-agent | `monitor_operative` |
| LiveResearchBench (Salesforce) | `liveresearchbench` | jarvis-direct | — |
| LiveCodeBench | `livecodebench` | jarvis-direct | — |

---

## How to run M3 on a new cell

```bash
source /data/home/jonsaadfalcon/jonsf/OpenJarvis/.env
.venv/bin/python scripts/experiments/m3_hill_climb.py \
    --student 9b --benchmark pinchbench \
    --rounds 4 --k-subsample 15 --k-final 23
```

The script:
1. Auto-measures today's baseline at `k_final` (prevents anchoring to unreproducible Step 1 numbers)
2. Hill-climbs `rounds` proposals, each verified at `k_subsample`
3. Runs final eval at `k_final` with the best config
4. Writes state to `results/neurips-2026/distillation-m3/<student>-<benchmark>/state.json` (resumable)

---

## Open research questions

### 1. Why are agent-benchmark baselines not reproducible?
PB, GAIA, DRB baselines dropped 30-60 points between Jon's Step 1 and today. TC15 (direct backend) reproduces exactly. Root cause unknown — likely vLLM tool-calling format change, or agent code drift. **Investigating this could double our measured improvements** (if we can restore the missing 30-60 points through environment fixes).

### 2. Does iterative M3 (hill-climbing on the hill-climb) help?
Each M3 run gives a good local config. Does running M3 again from that config find more? Current max_rounds=4 is arbitrary — may be leaving gains on the table.

### 3. Can we apply the blocked edit types?
M1 proposed 202 system-prompt rewrites, 331 tool-description edits, 127 few-shot-exemplar edits. None propagate to the eval pipeline (all hardcoded in Python). **Unlocking these would enable proposals that move far more than max_turns/temperature could.** Estimated effort: ~1 day to add runtime loading from `$OPENJARVIS_HOME` to the `monitor_operative` and `native_openhands` agent classes.

### 4. Does multi-objective hill-climbing help?
Current M3 optimizes accuracy only. Distillation's deployment value is `small model + edits ≈ large model raw` on cost/latency. A Pareto-front optimizer could find configs that are slightly worse on accuracy but dramatically cheaper.

### 5. Composing per-cell configs at inference time
M3 produces a different config per (student, benchmark) pair. In deployment, queries don't carry a "benchmark" label. A router that classifies the query and dispatches to the right config could capture per-cell gains at eval time without knowing the benchmark a priori.

---

## Key scripts

| Path | What |
|---|---|
| `scripts/experiments/m3_hill_climb.py` | **M3 per-cell hill-climb optimizer.** Main artifact. |
| `scripts/experiments/m2_extract_consensus.py` | M1 consensus extraction (legacy, shows why global aggregation fails) |
| `scripts/experiments/m2_create_distilled_configs.py` | Generate M2 distilled configs from M1 consensus |
| `scripts/experiments/m2_collect_results.py` | Aggregate M2 results into comparison table |
| `scripts/experiments/m2_test3_rich_context.py` | One-shot rich-context distillation (Test 3 baseline) |
| `scripts/experiments/run_distillation_experiments.sh` | M1 135-experiment runner |

## Results locations

| Path | What |
|---|---|
| `results/neurips-2026/agent-optimization/distillation/` | M1 session artifacts (135 configs × plan.json + diagnosis) |
| `results/neurips-2026/distilled/` | M2 full matrix (24 cells) |
| `results/neurips-2026/distillation-m2/baseline-repro/` | M2 reproducibility checks (the drift discovery) |
| `results/neurips-2026/distillation-m3/` | M3 hill-climb state + final configs per cell |
| `/scratch/user/jonsaadfalcon/openjarvis-m1/` | Isolated M1 home (traces.db with A1 feedback) |
| `/scratch/user/jonsaadfalcon/openjarvis-m2/` | M2 per-model global configs |

## Baselines (for quick reference)

**Reproducible today (same vLLM + agent setup as distilled runs):**

| Student | TC15 | PB | DRB | GAIA |
|---|---:|---:|---:|---:|
| qwen-2b | 33.3% | 6.7% | *pending* | *pending* |
| qwen-9b | 46.7% | *pending* | 32.0% | 6.0% |
| qwen-27b | 40.0% | 60.9% | 4.0% | 12.0% |

**Step 1 (Jon's earlier setup, not reproducible for agent benchmarks):**

| Student | TC15 | PB | LCB | TauB | TBTel | GAIA | DRB | LRB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| qwen-2b | 33.3% | 69.6% | 5.6% | 70.0% | 0.0% | 0.0% | 0.0% | 52.0% |
| qwen-9b | 46.7% | 95.7% | 17.6% | 85.0% | 80.0% | 38.0% | 75.0% | 46.0% |
| qwen-27b | 40.0% | 65.2% | 20.0% | 75.0% | 75.0% | 48.0% | 66.7% | 48.0% |

Treat direct-backend cells (TC15, LCB, LRB) as reproducible. Treat agent-backend cells as *historical reference only* — measure baseline in your current setup before comparing.
