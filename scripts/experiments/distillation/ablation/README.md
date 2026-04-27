# M2 ablation sweep

Separate from the linear M1 pipeline (steps 1–7 in the parent directory).
This sub-pipeline ablates *axes* of distillation: teacher choice, gate
threshold, student size, autonomy mode, iterative variants, and transfer.

Two scripts:

* **`generate_configs.py`** — emits TOMLs for 7 ablation groups
  (`exp1a-teacher`, `exp1b-budget`, `exp1c-student`, `exp2a-gate`,
  `exp2b-autonomy`, `exp3a-iterative`, `exp3b-transfer`) into
  `src/openjarvis/evals/configs/distillation/<group>/`.
* **`run_ablations.sh`** — runs those TOMLs and writes results under
  `results/neurips-2026/agent-optimization/distillation/`.

```bash
# Generate / regenerate the matrix
python scripts/experiments/distillation/ablation/generate_configs.py

# Run everything
bash scripts/experiments/distillation/ablation/run_ablations.sh

# Run a single ablation group
bash scripts/experiments/distillation/ablation/run_ablations.sh exp1a

# Run a single config within a group
bash scripts/experiments/distillation/ablation/run_ablations.sh exp1a opus
```

## Prerequisites

* Ollama running with `qwen3.5:{2b,9b,27b}`
* `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` set
* For the Qwen-397B teacher: vLLM serving on port 8010 (8×H100)
* Traces seeded with feedback (run step 2 of the M1 pipeline first)
* `jarvis learning init` already run
