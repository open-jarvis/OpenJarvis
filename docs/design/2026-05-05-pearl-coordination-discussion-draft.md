# Pearl coordination thread — draft

**For:** Posting on `pearl-research-labs/pearl` GitHub Discussions (Category: General / Q&A).
**By:** OpenJarvis team (Stanford Hazy Research); contact: [user fills in].
**Status:** Draft — review and edit before posting.

---

## Suggested title

> Apple Silicon support for Pearl mining — coordination & confirmation

## Suggested body

Hi Pearl team — we're [OpenJarvis](https://github.com/open-jarvis/OpenJarvis), a local-first personal AI agent framework from Stanford Hazy Research. We're working on a `mining` subsystem that lets OJ users mine Pearl through the agent framework. The first integration is the `vllm-miner`-on-H100/H200 path, which is straightforward. The second is Apple Silicon, where the situation is more interesting and we'd like to confirm a few things before we ship.

We have a v1 architecture that ships **today** using only your published Python packages (`py-pearl-mining`, `miner-base`, `pearl-gateway`) without any new code in your tree, plus an aspirational v2/v3 path that does involve potentially upstream contributions. Three asks below, plus a heads-up.

### What we built and verified locally (no protocol changes; all upstream code paths)

We read the Pearl source carefully — particularly:

- `zk-pow/src/api/verify.rs` — the validator
- `zk-pow/src/ffi/mine.rs` — the pure-Rust `mine()` function
- `zk-pow/src/circuit/pearl_noise.rs` — noise generation
- `py-pearl-mining/` — the PyO3 bindings exposing the above to Python
- `miner/miner-base/src/miner_base/noisy_gemm.py` — the PyTorch NoisyGEMM reference

…and then we built `py-pearl-mining` from source on an Apple Silicon M2 Max (macOS 26.4, Python 3.12, Rust 1.94). It produced `py_pearl_mining-0.1.0-cp312-abi3-macosx_11_0_arm64.whl` in ~56 seconds. We installed it and ran the `mine()` + `verify_plain_proof()` cycle from `tests/test_python_api.py`:

```
running mine(m=256, n=128, k=1024, rank=32) on Apple Silicon CPU…
  mine() returned a proof in 0.078s
  verify_plain_proof: ok=True, msg='Mining solution verified successfully'
```

So our v1 plan is: ship a CPU-mining mode for OJ users on Apple Silicon (and potentially other non-CUDA platforms) that wraps `pearl_mining.mine()` and your `pearl-gateway` as a subprocess. **We're not modifying anything in Pearl's tree for v1.** Just consuming what you've already published.

### Three asks

**1. Protocol acceptance confirmation.**

Reading the validator path, we believe `verify_block` and `verify_plain_proof` accept any `PlainProof` produced by a correct implementation, regardless of which hardware produced it. The plonky2 STARK and the difficulty check don't reference hardware.

**Could you confirm in writing that blocks mined via the pure-Rust `mine()` path (from a non-CUDA host like Apple Silicon) will be accepted by Pearl validators on testnet and mainnet?** We don't expect surprises here, but it's load-bearing for our spec and we want to record your sign-off before we ship.

**2. Heads-up: your `Taskfile.yml` restricts `build:miner` to `[linux, windows]`.**

That makes total sense for the GPU miner (CUDA + vLLM is Linux-only). But the `py-pearl-mining` and `miner-base` packages don't actually need that restriction — they install fine on macOS. We're working around the gate by installing the individual packages directly. Two questions:

   - Is the `[linux, windows]` restriction load-bearing in some way we don't see (e.g., do you intend `py-pearl-mining` to remain a CUDA-bound dependency long-term)?
   - Would you be open to a small PR that splits `build:miner-cpu` (cross-platform) from `build:miner-gpu` (Linux + CUDA)? It would help downstream consumers like us — and any hobbyist who wants to experiment with `pearl_mining.mine()` on whatever hardware they own.

**3. PyPI publication of `py-pearl-mining` / `miner-base` / `pearl-gateway`.**

Do you have a roadmap for publishing these as PyPI wheels (`pip install py-pearl-mining` etc.)? Today we'd vendor a pinned commit and `maturin build` locally, which works but is brittle. If a 2026 PyPI publication is plausible, we'd defer the local-build code path; if it's not on the roadmap, we'll plan for the long-term local-build path.

### Aspirational (v2 / v3) — context only, no asks yet

Once v1 ships, we'd like to explore Apple-native acceleration:

- **v2:** Use PyTorch MPS to GPU-accelerate `miner-base.NoisyGemm` on Apple Silicon. Could potentially become a plugin into `mlx-lm` or `llama-cpp-python` so a Mac user's *inference* matmuls do mining work — same "useful work" framing as your vllm-miner. We don't need anything from Pearl for this; we'd build it on top of your existing PyTorch reference.
- **v3 (only if v2 isn't enough):** A native Metal Shading Language port of NoisyGEMM, paralleling `pearl-gemm/`. That would be a real upstream contribution candidate (`pearl/miner/pearl-gemm-metal/`), and we'd want to coordinate with you before starting kernel work to avoid duplicate effort.

If you're already building Apple Silicon support internally (or have someone planning it), please tell us — we'd rather coordinate than duplicate.

### Logistics

- License compatibility: Pearl is ISC; OpenJarvis is Apache-2.0. We don't see any conflict for either consumption (v1) or contribution (v3), but please flag if you do.
- CLA: do you require one for upstream contributions? Not blocking v1 — just want to know for v3.
- Preferred coordination channel: this Discussion thread, a Discord, an email? We're happy to use whatever works for you.

Thanks for building this — Proof-of-Useful-Work via matmul is genuinely interesting and we're excited to bring more (slower!) hardware to the network.

— [user name], on behalf of OpenJarvis

---

## Notes for the user before posting

- Replace `[user fills in]` with your contact info, `[user name]` with your name.
- The architecture/perf claims are all backed by code + an actual local build; you can stand behind them.
- "Heads-up" framing on the `Taskfile.yml` is intentional — we're not asking them to *change* it, just flagging the friction point in case they want to.
- Don't post until OJ Spec A is at least branch-pushed (which it is, PR #310) — it gives Pearl a way to see the broader integration we're building.
- When their reply lands, update Spec B §10 (open questions 1, 5, 7) and §11 (cross-references → coordination thread URL).

## Possible Pearl responses to anticipate

- **Best case:** "Confirmed, looks great, we don't have an Apple Silicon plan, please do it." — proceed with §13.
- **Middle case:** "Confirmed, but we have a Metal port in flight." — coordinate, share Spec B §6.1, decide upstream-vs-fork. v1 (CPU) is unaffected.
- **Worst case:** "We'd prefer downstream non-CUDA mining stay disabled for now." — unlikely given their `pearl-gateway` README explicitly anticipates "plugins for other LLM inference libraries", but if it happens, this becomes a much harder problem and we'd need to revisit.
