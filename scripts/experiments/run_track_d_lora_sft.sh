#!/usr/bin/env bash
# =============================================================================
# Track D: LoRA / SFT Intelligence Optimization
# NeurIPS 2026 — Intelligence Optimization Experiments
#
# Runs LoRA and SFT fine-tuning across:
#   LoRA models: Qwen-2B, Qwen-9B, Qwen-27B
#   SFT models:  Qwen-2B, Qwen-9B
#
# After training, runs fast-benchmark eval on every checkpoint.
#
# Usage:
#   bash scripts/experiments/run_track_d_lora_sft.sh
#   bash scripts/experiments/run_track_d_lora_sft.sh --method lora
#   bash scripts/experiments/run_track_d_lora_sft.sh --method sft --model qwen-2b
#   bash scripts/experiments/run_track_d_lora_sft.sh --skip-eval
#
# Expected runtime per run:
#   Qwen-2B LoRA  (~4-8 h,   1x H100, GPU 0)
#   Qwen-9B LoRA  (~8-16 h,  1x H100, GPU 1)
#   Qwen-27B LoRA (~16-24 h, 2x H100, GPUs 2-3)
#   Qwen-2B SFT   (~8-16 h,  1x H100, GPU 4)
#   Qwen-9B SFT   (~16-24 h, 2x H100, GPUs 5-6)
#
# Total wall-clock (all in parallel): ~24 h on a 7-8x H100 node
# Total GPU-hours: ~100-200 H100-hours
#
# =============================================================================
# GPU Allocation — recommended for a single 8x H100 node
# =============================================================================
#
# Run D1 (Qwen-2B LoRA)   on GPU 0:
#   CUDA_VISIBLE_DEVICES=0 bash scripts/experiments/run_track_d_lora_sft.sh \
#       --method lora --model qwen-2b &
#
# Run D2 (Qwen-9B LoRA)   on GPU 1:
#   CUDA_VISIBLE_DEVICES=1 bash scripts/experiments/run_track_d_lora_sft.sh \
#       --method lora --model qwen-9b &
#
# Run D3 (Qwen-27B LoRA)  on GPUs 2-3:
#   CUDA_VISIBLE_DEVICES=2,3 bash scripts/experiments/run_track_d_lora_sft.sh \
#       --method lora --model qwen-27b &
#
# Run D4 (Qwen-2B SFT)    on GPU 4:
#   CUDA_VISIBLE_DEVICES=4 bash scripts/experiments/run_track_d_lora_sft.sh \
#       --method sft --model qwen-2b &
#
# Run D5 (Qwen-9B SFT)    on GPUs 5-6:
#   CUDA_VISIBLE_DEVICES=5,6 bash scripts/experiments/run_track_d_lora_sft.sh \
#       --method sft --model qwen-9b &
#
# =============================================================================
# Training datasets (downloaded automatically if HF_TOKEN is set)
# =============================================================================
#
#   Primary agentic traces:
#     - neulab/agent-data-collection
#     - GAIR/AgentInstruct
#
#   Supplementary reasoning:
#     - GeneralThought-430K-filtered
#     - GLM-4.7-flash SFT traces (168K + 57K)
#
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESULTS_BASE="${REPO_ROOT}/results/neurips-2026/intelligence-optimization"
LOG_DIR="${REPO_ROOT}/results/neurips-2026/logs"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Default: run all methods and models
ALL_LORA_MODELS=(qwen-2b qwen-9b qwen-27b)
ALL_SFT_MODELS=(qwen-2b qwen-9b)
FAST_BENCHMARKS=(toolcall15 pinchbench taubench)

# CLI overrides
FILTER_METHOD=""
FILTER_MODEL=""
SKIP_EVAL=false

# Training hyperparameters (override per model below)
LORA_RANK=64
LORA_ALPHA=128
LORA_DROPOUT=0.05
LORA_EPOCHS=3
LORA_LR=2e-4
LORA_BATCH_SIZE=8
LORA_GRAD_ACCUM=4

SFT_EPOCHS=3
SFT_LR=1e-5
SFT_BATCH_SIZE=4
SFT_GRAD_ACCUM=8

MAX_SEQ_LEN=8192

# Fast-eval settings
EVAL_MAX_SAMPLES=20

# ---------------------------------------------------------------------------
# HuggingFace model IDs
# ---------------------------------------------------------------------------
model_hf_id() {
    case "$1" in
        qwen-2b)  echo "Qwen/Qwen2.5-1.5B-Instruct" ;;
        qwen-9b)  echo "Qwen/Qwen2.5-7B-Instruct"   ;;
        qwen-27b) echo "Qwen/Qwen2.5-32B-Instruct"  ;;
        *)
            echo "ERROR: unknown model $1" >&2
            exit 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Parse CLI flags
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --method)
            FILTER_METHOD="$2"; shift 2 ;;
        --model)
            FILTER_MODEL="$2"; shift 2 ;;
        --skip-eval)
            SKIP_EVAL=true; shift ;;
        --lora-rank)
            LORA_RANK="$2"; shift 2 ;;
        --lora-epochs)
            LORA_EPOCHS="$2"; shift 2 ;;
        --sft-epochs)
            SFT_EPOCHS="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,35p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *)
            echo "Unknown flag: $1"; exit 1 ;;
    esac
done

# Apply model filter
if [[ -n "$FILTER_MODEL" ]]; then
    ALL_LORA_MODELS=("$FILTER_MODEL")
    ALL_SFT_MODELS=("$FILTER_MODEL")
fi

# Apply method filter
RUN_LORA=true
RUN_SFT=true
if [[ "$FILTER_METHOD" == "lora" ]]; then
    RUN_SFT=false
elif [[ "$FILTER_METHOD" == "sft" ]]; then
    RUN_LORA=false
fi

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/track_d_${TIMESTAMP}.log"

log() {
    local level="$1"; shift
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE"
}

log_info()  { log "INFO " "$@"; }
log_ok()    { log "OK   " "$@"; }
log_warn()  { log "WARN " "$@"; }
log_error() { log "ERROR" "$@"; }

# ---------------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------------
setup_env() {
    log_info "=== Track D: LoRA/SFT Training ==="
    log_info "Repo:    $REPO_ROOT"
    log_info "Log:     $LOG_FILE"
    log_info "Results: $RESULTS_BASE"
    echo ""

    # Check we are in the repo root
    if [[ ! -f "${REPO_ROOT}/pyproject.toml" ]]; then
        log_error "pyproject.toml not found — is REPO_ROOT set correctly? ($REPO_ROOT)"
        exit 1
    fi

    # Install/sync dependencies
    log_info "Running uv sync..."
    cd "$REPO_ROOT"
    uv sync --extra dev 2>&1 | tail -5
    log_ok "uv sync complete"

    # HuggingFace token — required to download gated Qwen models
    if [[ -z "${HF_TOKEN:-}" ]]; then
        log_warn "HF_TOKEN is not set."
        log_warn "  If Qwen models are gated, set: export HF_TOKEN=hf_..."
        log_warn "  Or pre-download them with: huggingface-cli download <model>"
    else
        log_ok "HF_TOKEN is set"
        # Log in so huggingface_hub uses the token
        uv run python -c "
import huggingface_hub
huggingface_hub.login(token='${HF_TOKEN}', add_to_git_credential=False)
print('Logged in to HuggingFace Hub')
" 2>&1 | tee -a "$LOG_FILE"
    fi

    # Check for GPU
    if ! command -v nvidia-smi &>/dev/null; then
        log_warn "nvidia-smi not found — ensure CUDA is available for training."
    else
        log_info "GPU status:"
        nvidia-smi --query-gpu=index,name,memory.total,memory.free \
            --format=csv,noheader 2>&1 | while IFS= read -r line; do
            log_info "  $line"
        done
    fi

    # Check for trl / peft / transformers (training stack)
    uv run python -c "
import importlib, sys
missing = []
for pkg in ['transformers', 'peft', 'trl', 'datasets', 'accelerate', 'bitsandbytes']:
    if importlib.util.find_spec(pkg) is None:
        missing.append(pkg)
if missing:
    print('MISSING packages:', missing)
    sys.exit(1)
else:
    print('Training stack OK: transformers, peft, trl, datasets, accelerate, bitsandbytes')
" 2>&1 | tee -a "$LOG_FILE" || {
        log_error "Some training packages are missing. Install with:"
        log_error "  uv add transformers peft trl datasets accelerate bitsandbytes"
        exit 1
    }

    echo ""
}

# ---------------------------------------------------------------------------
# Download / verify training dataset
# ---------------------------------------------------------------------------
prepare_dataset() {
    local method="$1"
    local model="$2"
    local data_dir="${REPO_ROOT}/results/neurips-2026/training-data"
    mkdir -p "$data_dir"

    log_info "Preparing training dataset for $method/$model..."

    uv run python - <<PYEOF 2>&1 | tee -a "$LOG_FILE"
from datasets import load_dataset
import json
from pathlib import Path

data_dir = Path("${data_dir}")
output_path = data_dir / "${method}_${model}_train.jsonl"

if output_path.exists():
    lines = output_path.read_text().count('\n')
    print(f"Dataset already exists: {output_path} ({lines} examples)")
else:
    print("Downloading neulab/agent-data-collection...")
    ds = load_dataset("neulab/agent-data-collection", split="train")
    print(f"Raw dataset size: {len(ds)}")

    # Filter to reasonable-length examples for agentic fine-tuning
    examples = []
    for ex in ds:
        messages = ex.get("messages") or ex.get("conversations") or []
        if not messages:
            continue
        total_len = sum(len(str(m)) for m in messages)
        if 200 <= total_len <= 16000:
            examples.append({"messages": messages})

    print(f"Filtered dataset size: {len(examples)}")

    with output_path.open("w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")
    print(f"Saved to {output_path}")
PYEOF

    echo "${data_dir}/${method}_${model}_train.jsonl"
}

# ---------------------------------------------------------------------------
# LoRA training for one model
# ---------------------------------------------------------------------------
run_lora() {
    local model="$1"
    local hf_id
    hf_id="$(model_hf_id "$model")"
    local out_dir="${RESULTS_BASE}/lora/${model}"
    local checkpoint_dir="${out_dir}/checkpoint"
    mkdir -p "$out_dir" "$checkpoint_dir"

    log_info "=========================================="
    log_info "LoRA training: $model ($hf_id)"
    log_info "  Output: $out_dir"
    log_info "  LoRA rank=$LORA_RANK  alpha=$LORA_ALPHA  dropout=$LORA_DROPOUT"
    log_info "  Epochs=$LORA_EPOCHS  LR=$LORA_LR  batch=$LORA_BATCH_SIZE  grad_accum=$LORA_GRAD_ACCUM"
    log_info "=========================================="

    local dataset_path
    dataset_path="$(prepare_dataset lora "$model")"

    local t0
    t0="$(date +%s)"

    # Number of GPUs visible
    local n_gpus
    n_gpus="$(python3 -c "import torch; print(torch.cuda.device_count())" 2>/dev/null || echo 1)"
    log_info "Training on $n_gpus GPU(s)"

    if [[ "$n_gpus" -gt 1 ]]; then
        LAUNCHER="uv run torchrun --nproc_per_node=$n_gpus"
    else
        LAUNCHER="uv run python"
    fi

    $LAUNCHER - <<PYEOF 2>&1 | tee -a "$LOG_FILE"
import json
import math
import os
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig, TaskType, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

hf_id   = "${hf_id}"
out_dir = "${out_dir}"
ckpt    = "${checkpoint_dir}"
data_path = "${dataset_path}"

# ---- Tokenizer ----
print(f"Loading tokenizer: {hf_id}")
tokenizer = AutoTokenizer.from_pretrained(hf_id, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# ---- Dataset ----
print(f"Loading dataset: {data_path}")
raw = load_dataset("json", data_files=data_path, split="train")
raw = raw.train_test_split(test_size=0.02, seed=42)

def tokenize(example):
    messages = example["messages"]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    enc = tokenizer(text, truncation=True, max_length=${MAX_SEQ_LEN})
    enc["labels"] = enc["input_ids"].copy()
    return enc

print("Tokenizing dataset...")
tok_ds = raw.map(tokenize, remove_columns=raw["train"].column_names, num_proc=4)
print(f"Train: {len(tok_ds['train'])}  Eval: {len(tok_ds['test'])}")

# ---- Model ----
print(f"Loading model: {hf_id}")
model = AutoModelForCausalLM.from_pretrained(
    hf_id,
    torch_dtype=torch.bfloat16,
    trust_remote_code=True,
    device_map="auto",
)

# ---- LoRA ----
lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=${LORA_RANK},
    lora_alpha=${LORA_ALPHA},
    lora_dropout=${LORA_DROPOUT},
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    bias="none",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# ---- Training args ----
steps_per_epoch = math.ceil(len(tok_ds["train"]) / (${LORA_BATCH_SIZE} * ${LORA_GRAD_ACCUM}))
total_steps = steps_per_epoch * ${LORA_EPOCHS}
save_steps = max(50, steps_per_epoch // 2)

args = TrainingArguments(
    output_dir=ckpt,
    num_train_epochs=${LORA_EPOCHS},
    per_device_train_batch_size=${LORA_BATCH_SIZE},
    gradient_accumulation_steps=${LORA_GRAD_ACCUM},
    learning_rate=${LORA_LR},
    warmup_ratio=0.05,
    lr_scheduler_type="cosine",
    logging_steps=10,
    save_steps=save_steps,
    eval_strategy="steps",
    eval_steps=save_steps,
    load_best_model_at_end=True,
    metric_for_best_model="eval_loss",
    bf16=True,
    gradient_checkpointing=True,
    dataloader_num_workers=4,
    report_to="none",
    save_total_limit=3,
)

# ---- Trainer ----
collator = DataCollatorForSeq2Seq(tokenizer, model=model, padding=True)
trainer = Trainer(
    model=model,
    args=args,
    train_dataset=tok_ds["train"],
    eval_dataset=tok_ds["test"],
    data_collator=collator,
)

print(f"Starting LoRA training: {total_steps} total steps")
trainer.train()

# Save final adapter
final_adapter = os.path.join(out_dir, "lora_adapter_final")
model.save_pretrained(final_adapter)
tokenizer.save_pretrained(final_adapter)
print(f"Final LoRA adapter saved to {final_adapter}")

# Save training metadata
meta = {
    "model": hf_id,
    "method": "lora",
    "lora_rank": ${LORA_RANK},
    "lora_alpha": ${LORA_ALPHA},
    "epochs": ${LORA_EPOCHS},
    "train_examples": len(tok_ds["train"]),
    "final_train_loss": trainer.state.log_history[-1].get("loss"),
}
with open(os.path.join(out_dir, "training_meta.json"), "w") as f:
    import json; json.dump(meta, f, indent=2)
print("Training metadata saved.")
PYEOF

    local exit_code=${PIPESTATUS[0]}
    local t1
    t1="$(date +%s)"
    local elapsed=$(( t1 - t0 ))

    if [[ $exit_code -eq 0 ]]; then
        log_ok "LoRA $model done in ${elapsed}s (~$(( elapsed / 3600 ))h $(( (elapsed % 3600) / 60 ))m)"
        return 0
    else
        log_error "LoRA $model FAILED (exit $exit_code) after ${elapsed}s"
        return $exit_code
    fi
}

# ---------------------------------------------------------------------------
# SFT (full fine-tuning) for one model
# ---------------------------------------------------------------------------
run_sft() {
    local model="$1"
    local hf_id
    hf_id="$(model_hf_id "$model")"
    local out_dir="${RESULTS_BASE}/sft/${model}"
    local checkpoint_dir="${out_dir}/checkpoint"
    mkdir -p "$out_dir" "$checkpoint_dir"

    log_info "=========================================="
    log_info "SFT training: $model ($hf_id)"
    log_info "  Output: $out_dir"
    log_info "  Epochs=$SFT_EPOCHS  LR=$SFT_LR  batch=$SFT_BATCH_SIZE  grad_accum=$SFT_GRAD_ACCUM"
    log_info "=========================================="

    local dataset_path
    dataset_path="$(prepare_dataset sft "$model")"

    local t0
    t0="$(date +%s)"

    local n_gpus
    n_gpus="$(python3 -c "import torch; print(torch.cuda.device_count())" 2>/dev/null || echo 1)"
    log_info "Training on $n_gpus GPU(s)"

    if [[ "$n_gpus" -gt 1 ]]; then
        LAUNCHER="uv run torchrun --nproc_per_node=$n_gpus"
    else
        LAUNCHER="uv run python"
    fi

    $LAUNCHER - <<PYEOF 2>&1 | tee -a "$LOG_FILE"
import json
import math
import os
from pathlib import Path

import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

hf_id   = "${hf_id}"
out_dir = "${out_dir}"
ckpt    = "${checkpoint_dir}"
data_path = "${dataset_path}"

# ---- Tokenizer ----
print(f"Loading tokenizer: {hf_id}")
tokenizer = AutoTokenizer.from_pretrained(hf_id, trust_remote_code=True)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# ---- Dataset ----
print(f"Loading dataset: {data_path}")
raw = load_dataset("json", data_files=data_path, split="train")
raw = raw.train_test_split(test_size=0.02, seed=42)

def tokenize(example):
    messages = example["messages"]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    enc = tokenizer(text, truncation=True, max_length=${MAX_SEQ_LEN})
    enc["labels"] = enc["input_ids"].copy()
    return enc

print("Tokenizing dataset...")
tok_ds = raw.map(tokenize, remove_columns=raw["train"].column_names, num_proc=4)
print(f"Train: {len(tok_ds['train'])}  Eval: {len(tok_ds['test'])}")

# ---- Model (4-bit quantized to fit on fewer GPUs) ----
print(f"Loading model: {hf_id}")
from transformers import BitsAndBytesConfig
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True,
)
model = AutoModelForCausalLM.from_pretrained(
    hf_id,
    quantization_config=bnb_config,
    trust_remote_code=True,
    device_map="auto",
)
model.config.use_cache = False

# ---- Training args ----
steps_per_epoch = math.ceil(len(tok_ds["train"]) / (${SFT_BATCH_SIZE} * ${SFT_GRAD_ACCUM}))
total_steps = steps_per_epoch * ${SFT_EPOCHS}
save_steps = max(50, steps_per_epoch // 2)

args = TrainingArguments(
    output_dir=ckpt,
    num_train_epochs=${SFT_EPOCHS},
    per_device_train_batch_size=${SFT_BATCH_SIZE},
    gradient_accumulation_steps=${SFT_GRAD_ACCUM},
    learning_rate=${SFT_LR},
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",
    logging_steps=10,
    save_steps=save_steps,
    eval_strategy="steps",
    eval_steps=save_steps,
    load_best_model_at_end=True,
    metric_for_best_model="eval_loss",
    bf16=True,
    gradient_checkpointing=True,
    dataloader_num_workers=4,
    report_to="none",
    save_total_limit=3,
)

# ---- Trainer ----
collator = DataCollatorForSeq2Seq(tokenizer, model=model, padding=True)
trainer = Trainer(
    model=model,
    args=args,
    train_dataset=tok_ds["train"],
    eval_dataset=tok_ds["test"],
    data_collator=collator,
)

print(f"Starting SFT training: {total_steps} total steps")
trainer.train()

# Save final model
final_model = os.path.join(out_dir, "sft_model_final")
model.save_pretrained(final_model)
tokenizer.save_pretrained(final_model)
print(f"Final SFT model saved to {final_model}")

# Save training metadata
meta = {
    "model": hf_id,
    "method": "sft",
    "epochs": ${SFT_EPOCHS},
    "train_examples": len(tok_ds["train"]),
    "final_train_loss": trainer.state.log_history[-1].get("loss"),
}
with open(os.path.join(out_dir, "training_meta.json"), "w") as f:
    import json; json.dump(meta, f, indent=2)
print("Training metadata saved.")
PYEOF

    local exit_code=${PIPESTATUS[0]}
    local t1
    t1="$(date +%s)"
    local elapsed=$(( t1 - t0 ))

    if [[ $exit_code -eq 0 ]]; then
        log_ok "SFT $model done in ${elapsed}s (~$(( elapsed / 3600 ))h $(( (elapsed % 3600) / 60 ))m)"
        return 0
    else
        log_error "SFT $model FAILED (exit $exit_code) after ${elapsed}s"
        return $exit_code
    fi
}

# ---------------------------------------------------------------------------
# Post-training eval: run fast benchmarks on a checkpoint
# ---------------------------------------------------------------------------
run_eval() {
    local method="$1"   # lora or sft
    local model="$2"
    local out_dir="${RESULTS_BASE}/${method}/${model}"

    if [[ "$SKIP_EVAL" == "true" ]]; then
        log_info "Skipping eval (--skip-eval)"
        return 0
    fi

    # Locate the final checkpoint / adapter
    local checkpoint=""
    if [[ "$method" == "lora" ]]; then
        checkpoint="${out_dir}/lora_adapter_final"
    else
        checkpoint="${out_dir}/sft_model_final"
    fi

    if [[ ! -d "$checkpoint" ]]; then
        log_warn "Checkpoint not found for $method/$model at $checkpoint — skipping eval"
        return 0
    fi

    log_info "--- Post-training eval: $method/$model ---"
    log_info "  Checkpoint: $checkpoint"

    for bench in "${FAST_BENCHMARKS[@]}"; do
        local eval_out="${out_dir}/eval/${bench}"
        mkdir -p "$eval_out"
        log_info "  Eval: $bench -> $eval_out"

        uv run python - <<PYEOF 2>&1 | tee -a "$LOG_FILE"
import subprocess, sys

cmd = [
    "uv", "run", "python", "-m", "openjarvis.evals", "run",
    "--model-path", "${checkpoint}",
    "--model-id", "${model}-${method}",
    "--benchmark", "${bench}",
    "--max-samples", "${EVAL_MAX_SAMPLES}",
    "--output", "${eval_out}",
]
print("Running:", " ".join(cmd))
result = subprocess.run(cmd, capture_output=False)
sys.exit(result.returncode)
PYEOF

        local eval_exit=${PIPESTATUS[0]}
        if [[ $eval_exit -eq 0 ]]; then
            log_ok "  Eval $method/$model/$bench OK"
        else
            log_warn "  Eval $method/$model/$bench returned exit $eval_exit (non-fatal)"
        fi
    done
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print_summary() {
    echo ""
    log_info "=== Track D Complete ==="
    log_info "Results written to:"

    if [[ "$RUN_LORA" == "true" ]]; then
        for model in "${ALL_LORA_MODELS[@]}"; do
            local out="${RESULTS_BASE}/lora/${model}"
            if [[ -d "$out" ]]; then
                log_ok "  lora/$model -> $out"
            else
                log_warn "  lora/$model -> MISSING ($out)"
            fi
        done
    fi

    if [[ "$RUN_SFT" == "true" ]]; then
        for model in "${ALL_SFT_MODELS[@]}"; do
            local out="${RESULTS_BASE}/sft/${model}"
            if [[ -d "$out" ]]; then
                log_ok "  sft/$model -> $out"
            else
                log_warn "  sft/$model -> MISSING ($out)"
            fi
        done
    fi

    log_info "Full log: $LOG_FILE"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    setup_env

    local failed=0

    # ---- LoRA runs ----
    if [[ "$RUN_LORA" == "true" ]]; then
        log_info "=========================================="
        log_info "Starting LoRA training runs"
        log_info "Models: ${ALL_LORA_MODELS[*]}"
        log_info "=========================================="
        for model in "${ALL_LORA_MODELS[@]}"; do
            run_lora "$model" || { failed=$(( failed + 1 )); log_error "LoRA $model failed, continuing..."; }
            run_eval lora "$model"
            echo ""
        done
    fi

    # ---- SFT runs ----
    if [[ "$RUN_SFT" == "true" ]]; then
        log_info "=========================================="
        log_info "Starting SFT training runs"
        log_info "Models: ${ALL_SFT_MODELS[*]}"
        log_info "=========================================="
        for model in "${ALL_SFT_MODELS[@]}"; do
            run_sft "$model" || { failed=$(( failed + 1 )); log_error "SFT $model failed, continuing..."; }
            run_eval sft "$model"
            echo ""
        done
    fi

    print_summary

    if [[ $failed -gt 0 ]]; then
        log_error "$failed training run(s) failed. Check log: $LOG_FILE"
        exit 1
    fi

    log_ok "All Track D runs completed successfully."
}

main "$@"
