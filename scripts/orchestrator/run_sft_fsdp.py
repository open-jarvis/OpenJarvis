#!/usr/bin/env python
"""Full-parameter SFT for the orchestrator policy via FSDP (multi-GPU).

Launch with accelerate so the model + optimizer shard across GPUs (an 8-9B full
fine-tune won't fit one L40S otherwise):

    accelerate launch --config_file <fsdp.yaml> \
        scripts/orchestrator/run_sft_fsdp.py \
        --data data/orchestrator/sft/qwen_train_0707.jsonl [--data <more> ...] \
        --variant correct --model Qwen/Qwen3.5-9B \
        --out checkpoints/sft_correct --epochs 3 --batch-size 8 --grad-accum 8 \
        --wandb-project orchestrator-sft

--variant selects which trajectories to train on:
  all            -> every record
  correct        -> only records the verifier marked correct
  correct_routed -> only correct records that delegated to a model expert

By default (--require-clean) records explicitly marked clean=False by the clean
gate (bloated / garbled / unrouted) are also dropped; rows missing the flag
(legacy data) are kept. Pass --no-require-clean to skip this filter.

Reuses the conversation->tokens + assistant-only masking from sft_tokenize.py.
On these no-NVLink L40S, the accelerate/FSDP NCCL env (NCCL_P2P_DISABLE=1 etc.)
must be set by the launcher.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from pathlib import Path

# reuse the data builder from the LoRA launcher
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sft_tokenize import build_example  # noqa: E402

MODEL_EXPERTS = {
    "gpt_5_5",
    "claude_opus_4_8",
    "qwen3_5_9b",
    "qwen3_6_27b_fp8",
    "qwen3_5_122b_a10b_fp8",
    "qwen3_5_397b_a17b_fp8",
}


def record_is_correct(r: dict) -> bool:
    c = r.get("correct")
    if c is None:
        c = r.get("metrics", {}).get("correct")
    return bool(c)


def record_routed_to_expert(r: dict) -> bool:
    """True if the trajectory called a model expert (resolving anon labels)."""
    amap = r.get("metrics", {}).get("anon_map", {})
    names = re.findall(
        r'"name"\s*:\s*"([a-z0-9_]+)"', json.dumps(r.get("conversations", []))
    )
    for n in names:
        real = amap.get(n, n)
        if real in MODEL_EXPERTS:
            return True
    return False


def record_clean_flag(r: dict):
    """The record's `clean` flag: True/False, or None if absent (legacy data).

    None means the clean gate never ran on this row, so we can't judge it -> we
    keep it (legacy behavior) rather than silently dropping older datasets.
    """
    c = r.get("clean")
    if c is None:
        c = r.get("metrics", {}).get("clean")
    return c


def select(records, variant: str, require_clean: bool = True):
    """Filter by --variant, then (default) drop records explicitly marked unclean.

    require_clean drops rows whose `clean` flag is False. Rows missing the flag
    (legacy) are kept regardless, matching pre-clean-gate behavior.
    """
    if variant == "all":
        base = list(records)
    elif variant == "correct":
        base = [r for r in records if record_is_correct(r)]
    elif variant == "correct_routed":
        base = [
            r for r in records if record_is_correct(r) and record_routed_to_expert(r)
        ]
    else:
        raise ValueError(f"unknown variant {variant}")
    if not require_clean:
        return base
    return [r for r in base if record_clean_flag(r) is not False]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--data", action="append", required=True, help="JSONL(s) (repeatable)"
    )
    p.add_argument(
        "--val-data",
        default=None,
        help="Held-out JSONL for val-loss (excluded from --data). Eval'd per epoch.",
    )
    p.add_argument(
        "--variant", choices=["all", "correct", "correct_routed"], default="correct"
    )
    p.add_argument(
        "--require-clean",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Drop records whose `clean` flag is False (bloated / garbled / "
        "unrouted). Rows missing the flag (legacy data) are kept. "
        "Use --no-require-clean to disable.",
    )
    p.add_argument("--model", default="Qwen/Qwen3.5-9B")
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=float, default=3.0)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--grad-accum", type=int, default=8)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--max-seq", type=int, default=8192)
    p.add_argument(
        "--supervise-last-only",
        action="store_true",
        help="Legacy: supervise ONLY the final assistant turn. Default "
        "(off) supervises every assistant turn incl. routing.",
    )
    p.add_argument("--warmup-ratio", type=float, default=0.03)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--wandb-project", default="orchestrator-sft")
    p.add_argument("--wandb-name", default="")
    args = p.parse_args()

    import random
    from datetime import timedelta

    import torch
    from accelerate import Accelerator
    from accelerate.utils import InitProcessGroupKwargs, set_seed
    from torch.utils.data import DataLoader
    from transformers import AutoModelForCausalLM, AutoTokenizer

    set_seed(args.seed)
    # 30-min collective timeout: a slow first-step shard gather / graph build on a
    # contended node was tripping the default 10-min NCCL watchdog (job 3892 died
    # at step 1). This only delays a *real* hang's crash; it fixes spurious ones.
    pg_timeout_min = int(os.environ.get("SFT_PG_TIMEOUT_MIN", "30"))
    accelerator = Accelerator(
        gradient_accumulation_steps=args.grad_accum,
        kwargs_handlers=[
            InitProcessGroupKwargs(timeout=timedelta(minutes=pg_timeout_min))
        ],
    )
    is_main = accelerator.is_main_process

    def log(m):
        if is_main:
            print(f"[fsdp-sft] {time.strftime('%H:%M:%S')} {m}", flush=True)

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token

    # ---- data ----
    records = []
    for f in args.data:
        records += [json.loads(l) for l in open(f) if l.strip()]
    sel = select(records, args.variant, require_clean=args.require_clean)
    log(f"variant={args.variant}: {len(sel)}/{len(records)} records")
    if args.require_clean:
        pre_clean = select(records, args.variant, require_clean=False)
        n_unclean = len(pre_clean) - len(sel)
        log(
            f"require_clean=True: dropped {n_unclean} unclean rows "
            f"({len(pre_clean)}->{len(sel)}); use --no-require-clean to keep them"
        )
    else:
        log("require_clean=False: NOT filtering on `clean` flag")
    examples = []
    for r in sel:
        ex = build_example(
            tok,
            r.get("conversations", []),
            args.max_seq,
            supervise_all_turns=not args.supervise_last_only,
        )
        if ex:
            examples.append(ex)
    log(f"built {len(examples)} training examples")
    if not examples:
        log("no examples; abort")
        return 1
    random.Random(args.seed).shuffle(examples)

    def collate(batch):
        maxlen = max(len(b["input_ids"]) for b in batch)
        ii, lab, am = [], [], []
        for b in batch:
            pad = maxlen - len(b["input_ids"])
            ii.append(b["input_ids"] + [tok.pad_token_id] * pad)
            lab.append(b["labels"] + [-100] * pad)
            am.append([1] * len(b["input_ids"]) + [0] * pad)
        return (torch.tensor(ii), torch.tensor(lab), torch.tensor(am))

    dl = DataLoader(
        examples, batch_size=args.batch_size, shuffle=True, collate_fn=collate
    )

    # ---- held-out val set (leak-free; excluded from --data upstream) ----
    val_dl = None
    if args.val_data:
        vrecs = [json.loads(l) for l in open(args.val_data) if l.strip()]
        vex = []
        for r in vrecs:
            ex = build_example(
                tok,
                r.get("conversations", []),
                args.max_seq,
                supervise_all_turns=not args.supervise_last_only,
            )
            if ex:
                vex.append(ex)
        log(f"val: {len(vex)} examples from {args.val_data}")
        if vex:
            val_dl = DataLoader(
                vex, batch_size=args.batch_size, shuffle=False, collate_fn=collate
            )

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        dtype=torch.bfloat16,
        trust_remote_code=True,
        attn_implementation="sdpa",
    )
    if os.environ.get("SFT_NO_GRAD_CKPT") == "1":
        log("gradient checkpointing DISABLED (SFT_NO_GRAD_CKPT=1)")
    else:
        model.gradient_checkpointing_enable(
            gradient_checkpointing_kwargs={"use_reentrant": False}
        )
    model.config.use_cache = False
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)

    model, opt, dl = accelerator.prepare(model, opt, dl)
    if val_dl is not None:
        val_dl = accelerator.prepare(val_dl)

    @torch.no_grad()
    def evaluate():
        # Corpus-level mean token loss over the holdout. FSDP needs every rank to
        # run the forward collectively, so each rank evals its shard and we reduce
        # token-weighted sums (not a mean-of-batch-means, which would mis-weight).
        model.eval()
        tot_loss = torch.zeros((), device=accelerator.device)
        tot_tok = torch.zeros((), device=accelerator.device)
        for ii, lab, am in val_dl:
            out = model(input_ids=ii, attention_mask=am, labels=lab)
            ntok = (lab != -100).sum()
            tot_loss += out.loss.detach() * ntok
            tot_tok += ntok
        tot_loss = accelerator.reduce(tot_loss, reduction="sum")
        tot_tok = accelerator.reduce(tot_tok, reduction="sum")
        model.train()
        return (tot_loss / tot_tok.clamp(min=1)).item()

    steps_per_epoch = math.ceil(len(dl) / args.grad_accum)
    total_steps = max(1, int(steps_per_epoch * args.epochs))
    warmup = max(1, int(total_steps * args.warmup_ratio))

    def lr_at(s):
        if s < warmup:
            return s / warmup
        return 0.5 * (
            1 + math.cos(math.pi * (s - warmup) / max(1, total_steps - warmup))
        )

    use_wandb = False
    if is_main:
        try:
            import wandb

            base_name = (
                args.wandb_name or f"{Path(args.model).name}-{args.variant}-fsdp"
            )
            run_name = f"{base_name}-{time.strftime('%m%d-%H%M', time.gmtime())}"
            wandb.init(
                project=args.wandb_project,
                name=run_name,
                config=vars(args)
                | {"n_examples": len(examples), "total_steps": total_steps},
            )
            use_wandb = True
        except Exception as e:
            log(f"wandb off ({e})")

    log(f"total_steps={total_steps} steps/epoch={steps_per_epoch} warmup={warmup}")

    def _save_ckpt(out_path):
        # Full-model checkpoint (gathers FSDP shards to rank0). Called per-epoch
        # so a long run leaves usable partial models + lets us eval intermediate
        # checkpoints (e.g. epoch1/epoch2) for the data-scaling sweep.
        accelerator.wait_for_everyone()
        unwrapped = accelerator.unwrap_model(model)
        p = Path(out_path)
        if is_main:
            p.mkdir(parents=True, exist_ok=True)
            tok.save_pretrained(str(p))
        unwrapped.save_pretrained(
            str(p),
            is_main_process=is_main,
            save_function=accelerator.save,
            state_dict=accelerator.get_state_dict(model),
        )
        if is_main:
            log(f"checkpoint saved -> {p}")

    model.train()
    gstep = 0
    t0 = time.time()
    if val_dl is not None:
        vloss = evaluate()
        log(f"val/loss (baseline, step 0) = {vloss:.4f}")
        if use_wandb:
            wandb.log({"val/loss": vloss}, step=0)
    for epoch in range(math.ceil(args.epochs)):
        for ii, lab, am in dl:
            with accelerator.accumulate(model):
                out = model(input_ids=ii, attention_mask=am, labels=lab)
                accelerator.backward(out.loss)
                if accelerator.sync_gradients:
                    lr = args.lr * lr_at(gstep)
                    for g in opt.param_groups:
                        g["lr"] = lr
                    accelerator.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                opt.zero_grad()
            if accelerator.sync_gradients:
                gstep += 1
                # accelerator.gather() is a COLLECTIVE — EVERY rank must call it.
                # Guarding it behind `is_main` made only rank0 run the [1]-float
                # all-gather while ranks 1-3 marched on to the next step's FSDP
                # param all-gather, desyncing the process group and hanging the job
                # at the step1->step2 boundary (NCCL collective-shape mismatch).
                loss = accelerator.gather(out.loss.detach()).mean().item()
                if is_main:
                    log(f"step {gstep}/{total_steps} loss={loss:.4f} lr={lr:.2e}")
                    if use_wandb:
                        wandb.log({"train/loss": loss, "train/lr": lr}, step=gstep)
            if gstep >= total_steps:
                break
        _save_ckpt(Path(args.out) / f"epoch{epoch + 1}")
        if val_dl is not None:
            vloss = evaluate()
            log(f"val/loss (epoch {epoch + 1}) = {vloss:.4f}")
            if use_wandb:
                wandb.log({"val/loss": vloss, "epoch": epoch + 1}, step=gstep)
        if gstep >= total_steps:
            break

    accelerator.wait_for_everyone()
    log("saving full model...")
    unwrapped = accelerator.unwrap_model(model)
    out_dir = Path(args.out)
    if is_main:
        out_dir.mkdir(parents=True, exist_ok=True)
        tok.save_pretrained(str(out_dir))
    unwrapped.save_pretrained(
        str(out_dir),
        is_main_process=is_main,
        save_function=accelerator.save,
        state_dict=accelerator.get_state_dict(model),
    )
    if is_main:
        log(f"saved -> {out_dir}")
        if use_wandb:
            try:
                wandb.finish()
            except Exception:
                pass
        print(
            "FSDP_SFT_DONE "
            + json.dumps(
                {
                    "variant": args.variant,
                    "steps": gstep,
                    "wall_s": round(time.time() - t0, 1),
                    "out": str(out_dir),
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
