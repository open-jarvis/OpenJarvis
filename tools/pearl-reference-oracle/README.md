# Pearl reference oracle (OpenJarvis Phase 0 deliverable)

Phase 0-B of [Spec B](../../docs/design/2026-05-05-apple-silicon-pearl-mining-design.md)
called for "build a Python reference oracle for NoisyGEMM, validate against the
Pearl CUDA reference."

**Phase 0 found the oracle already exists upstream**, in two complementary forms:

| Layer | Upstream location | What it covers |
|---|---|---|
| Pure-Rust mining algorithm exposed to Python | `pearl/py-pearl-mining` | The complete `mine()` + `verify_plain_proof()` cycle. CPU-only. Hardware-portable. |
| PyTorch reference of production NoisyGEMM | `pearl/miner/miner-base/src/miner_base/noisy_gemm.py` | The same NoisyGEMM that vllm-miner accelerates with H100 CUDA. Bit-exact denoising verified by upstream test (`tests/test_noisy_gemm.py:92`). |

So this directory contains:

1. `smoke_test.py` — a runnable script that **actually mines a block on this machine** using the upstream Rust path, demonstrating the v1 architecture works on Apple Silicon (or any platform where `py-pearl-mining` builds).
2. This README documenting where the reference math lives.

## What this is *not*

This is **not a reimplementation** of NoisyGEMM. The original Spec B planned for that;
Phase 0 made it unnecessary. If you're tempted to write `noisy_gemm.py` here, stop —
read `pearl/miner/miner-base/src/miner_base/noisy_gemm.py` instead.

## Setup

You need:

- macOS arm64 (M1/M2/M3/M4) **or** Linux x86_64 / aarch64
- Python 3.12 (`uv venv --python 3.12 .venv` is the easiest)
- Rust 1.78+ (any recent toolchain — verified with 1.94 on macOS arm64)
- The Pearl source tree somewhere on disk

Build the wheel and install it (one-time, ~60 s on a fast Mac, ~5 min on first build):

```bash
# from the Pearl repo root
cd py-pearl-mining
uv pip install maturin
maturin build --release --interpreter "$(which python)"

# install the resulting wheel
uv pip install target/wheels/py_pearl_mining-*.whl
```

Or if Pearl publishes to PyPI in the future:

```bash
uv pip install py-pearl-mining
```

## Run the smoke test

```bash
python smoke_test.py
```

Actual output on Apple Silicon M2 Max (numbers will vary by hardware and run):

```
host: macOS-26.4.1-arm64-arm-64bit (arm64)
python: 3.12.1
[ok] pearl_mining loaded from <site-packages>/pearl_mining/__init__.py
[ok] PUBLICDATA_SIZE=164  MERKLE_LEAF_SIZE=1024
[ok] mine(m=256, n=128, k=1024, rank=32) returned a proof in 0.119 s
       proof.m=256 proof.n=128 proof.k=1024  noise_rank=32
       a.row_indices=[177, 185, 241, 249]  bt.row_indices=[80, 81, 88, 89, 112, 113, 120, 121]
[ok] verify_plain_proof: ok=True ('Mining solution verified successfully', 0.2 ms)

[ok] all checks passed — Pearl mining works on this host
```

The `a.row_indices` and `bt.row_indices` values above are not constants — they're
`(offset + ROWS_PATTERN)` and `(offset + COLS_PATTERN)` for whichever offset the
miner happened to find a jackpot at. The smoke test verifies the *deltas* match
the configured `PeriodicPattern`, not the absolute values.

If it succeeds, this host can mine Pearl using the OpenJarvis `cpu-pearl` provider
(see Spec B §13). If it fails, the `[fail]` line tells you which step broke.

## What this proves (and what it doesn't)

**Proves:**

- The Pearl mining algorithm executes correctly on this host's CPU.
- Generated proofs verify under `verify_plain_proof`. (This is the same check
  validators run on the inputs to the ZK proof.)
- The whole stack — `pearl-blake3`, `zk-pow`, `py-pearl-mining` — builds and
  loads as a native CPython extension.

**Does NOT prove:**

- Network-difficulty hashrate. The smoke test uses
  `nbits=0x1D2FFFFF` (test difficulty), much easier than mainnet. Real mining
  expected hashrate on Apple Silicon CPU is several orders of magnitude lower
  per share — see Spec B §1.5.6.
- ZK proof generation throughput. The smoke test calls `verify_plain_proof`,
  not `generate_proof`. Plonky2 STARK proving takes seconds-to-minutes of CPU
  per block (Spec B Open Q10).
- That this host can keep up with the network's block production rate.

## When to update this

- When Pearl bumps `py-pearl-mining` API: re-run the smoke test against the
  new ref pinned in `OpenJarvis/src/openjarvis/mining/_constants.py`.
- When Pearl publishes a Mac wheel to PyPI: simplify the install instructions
  above, drop the local `maturin build` step.
- When Spec B v2 adds the PyTorch-MPS reference path: extend `smoke_test.py`
  with an MPS path comparison. The `miner-base` reference is already in
  PyTorch, so the v2 smoke test would be a different test invoking
  `miner_base.NoisyGemm` and comparing CPU vs MPS outputs for parity.
