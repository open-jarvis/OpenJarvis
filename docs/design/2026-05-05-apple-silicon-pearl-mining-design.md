# Spec B — Apple Silicon enablement for Pearl mining

| | |
|---|---|
| **Date** | 2026-05-05 |
| **Status** | Design — pending implementation plan |
| **Owner** | OpenJarvis team (parallel-agent friendly) |
| **Companion spec** | [Spec A — vLLM-Pearl mining integration (v1)](2026-05-05-vllm-pearl-mining-integration-design.md) |
| **Repos referenced** | `OpenJarvis`, `pearl-research-labs/pearl`, possibly upstream `ml-explore/mlx`, `ggerganov/llama.cpp` |

> **For agents picking this up cold:** read §1 ("Cold-start brief") first. Read §2 of Spec A to understand the registry pattern this spec slots into. The actual OJ-side work is small (§7); the long pole is GPU-kernel engineering (§5–§6).

## 1. Cold-start brief

**One-paragraph problem statement.** OpenJarvis is adding a `mining` subsystem (Spec A) that lets users mine the Pearl PoUW blockchain through their local LLM inference. Pearl's reference miner is CUDA-only and bound to NVIDIA Hopper (`sm_90a`, H100/H200) — most OpenJarvis users on Apple Silicon are locked out at the protocol level. **This spec is the plan to unblock them.** The OJ-side integration work is small (a new `MiningProvider` implementation that drops into the existing `MinerRegistry` from Spec A); the substantial work is a Metal port of Pearl's `NoisyGEMM` kernel and a matching plugin into an Apple-native inference backend (MLX or llama.cpp Metal). The Pearl validation path is plonky2-STARK-based and **already hardware-neutral** — see §3 for the evidence — so a correct Metal implementation produces blocks Pearl validators accept without any consensus changes.

**Three things to know before doing any work.**

1. The Pearl validator (`pearl/zk-pow/src/api/verify.rs::verify_block`) operates on a STARK proof and references no hardware. **The protocol does not care what GPU produced the work** as long as the math is correct and the proof verifies. CUDA-only is a performance choice, not a consensus choice.
2. Pearl's CUDA kernel (`pearl/miner/pearl-gemm/csrc/gemm/`) uses Hopper-only primitives (TMA, WGMMA, thread-block clusters, CUTLASS 3.x). A Metal port is **not a translation** — it's a from-scratch reimplementation against a different programming model. Plan effort accordingly.
3. The OJ integration boundary is the `MiningProvider` ABC defined in Spec A §4.4. **Do not modify Spec A.** Add a new provider file (`mining/mlx_pearl.py` or `mining/llamacpp_pearl_metal.py`), implement the ABC, register via `MinerRegistry`, ship a new optional extra. Everything else in Spec A — sidecar shape, config schema, telemetry adapter contract, v2 fee/pool seams — applies unchanged.

## 2. Why this is its own spec

Spec A's scope is the v1 integration that ships today on the only working configuration (vLLM + sm90). Apple Silicon enablement is a separate, parallelizable workstream because:

- **Different ownership boundary.** Spec A is Python integration of an existing Pearl Docker image. Spec B is GPU-kernel engineering with potential upstream contribution to Pearl. These need different reviewers, different CI surfaces (no H100 needed, but Apple Silicon required), and different release cadence.
- **Different timeline.** Spec A is weeks. Spec B is plausibly months for the kernel work alone.
- **Different blast radius.** Spec A ships zero risk to non-mining users; even mining users who edit the wrong config get a clear error. Spec B carries protocol-correctness risk — a bug in NoisyGEMM produces invalid blocks that get rejected by validators.
- **Parallel-agent ergonomics.** The user has explicitly asked for this spec to be picked up by a separate agent in parallel. Self-containment is a design goal.

## 3. Evidence: Apple Silicon support is possible

### 3.1 The validator is hardware-neutral

`pearl/zk-pow/src/api/verify.rs::verify_block`:

```rust
pub fn verify_block(public_params: &PublicProofParams, proof: &ZKProof, cache: &mut CircuitCache) -> Result<()> {
    let (params, pis) = prepare_verification(public_params, proof, None)?;
    PearlRecursion::compile_circuits(params, cache, false)?;
    verify_with_cache(params, cache, &pis, proof)
}
```

Verification is `PearlRecursion::verify(params, cache, pis, &proof.plonky2_proof)` — a recursive plonky2 STARK check. No GPU code path, no CUDA dependency. Validator nodes run pure Rust.

The mining work consists of three things, all of which are mathematical specifications — not implementation specifications:

1. A NoisyGEMM result whose noise pattern is derived from blake3 of a per-block key
2. A blake3 commitment hash over the noised matmul that meets a difficulty target
3. A plonky2 STARK proof that ties the result to the commitment

Any implementation that produces matching outputs is acceptable to the network. **This is the design intent of PoUW** — the work has to be replayable and verifiable, but not hardware-bound.

### 3.2 The Pearl team explicitly anticipates non-CUDA plugins

From `pearl/miner/README.md`:

> "Currently only mining via vLLM is supported, in the future we hope to supply plugins for other LLM inference libraries, like SGLang, TensorRT-LLM, Ollama, ..."

Apple is not in their list, but the framing — "supply plugins for other LLM inference libraries" — implies the boundary is at the inference backend, not at the consensus protocol. Confirms the architectural read.

### 3.3 Reference implementation exists in py-pearl-mining

`pearl/py-pearl-mining/` is a PyO3 crate exposing Pearl mining primitives in Python. **Read it before designing the Metal port** — it likely contains the protocol-relevant constants in a hardware-neutral form, suitable as a reference oracle for Phase 0 testing (§5).

## 4. Scope

### 4.1 In scope

- **Phase 0** (§5): protocol-acceptance verification + Pearl-team coordination + Python reference oracle
- **Phase 1** (§6.1): Metal NoisyGEMM kernel — the substantive engineering
- **Phase 2** (§6.2): inference-backend plugin — MLX or llama.cpp Metal
- **Phase 3** (§7): OJ provider integration — new `MiningProvider` impl, new optional extra, registry hookup
- **Phase 4** (§8): verification matrix across Apple Silicon variants and bringup on Pearl testnet
- Documentation deliverables and the upstream-contribution path

### 4.2 Out of scope

- Pool support and the 20% OJ fee (Spec A §8.5; that lives in a future v2 pool spec)
- Custody, signing, or routing Pearl funds (Spec A anti-goal; same here)
- AMD ROCm enablement (separate spec, parallel structure to this one)
- Intel Arc / Mac Intel / older CUDA enablement (separate specs)
- Modifying anything in Spec A. **Spec B is purely additive.**
- Pearl protocol changes (none required; see §3.1)

### 4.3 Explicit non-goal: economic competitiveness

This spec does not promise that Apple Silicon mining will be **profitable**. The performance gap to a tuned H100 kernel is likely large (§6.1.5 discusses why). What this spec *does* promise: a correct, working Apple Silicon path that's enabled the day the kernel ships, with a transparent doctor surface that tells Mac users honestly what their hashrate looks like. Whether it's worth the electricity is a user decision.

## 5. Phase 0 — investigation, coordination, reference oracle

The phase that costs the least and prevents the most rework. Three workstreams in parallel.

### 5.1 Workstream P0-A: Pearl-side coordination

**Goal:** Confirm protocol acceptance in writing from Pearl maintainers; align on whether OJ contributes upstream or ships independently.

**Steps:**

1. Open a GitHub Discussion on `pearl-research-labs/pearl`: "Apple Silicon / Metal NoisyGEMM enablement — coordination". Reference Spec B URL.
2. Get explicit confirmation from a Pearl maintainer that:
   - Validator path is hardware-neutral as believed (§3.1).
   - There is no Pearl-internal Metal port already in flight that would conflict.
   - LICENSE compatibility allows OJ-authored kernel code to be either contributed upstream (preferred) or distributed alongside OJ.
3. Discuss the upstream-vs-fork question. Strong default: **contribute upstream into a new `pearl/miner/pearl-gemm-metal/` crate**, paralleling `pearl-gemm/`, so Pearl owns the kernel long-term and we benefit from their CI and review. Fork only if upstream contribution is blocked.

**Exit criteria:**

- [ ] Written confirmation of protocol acceptance
- [ ] Agreement on contribution model (upstream / coordinated fork / independent)
- [ ] No duplicate-effort risk

### 5.2 Workstream P0-B: build a reference oracle

**Goal:** A pure-Python (or pure-Rust) implementation of NoisyGEMM that produces bit-exact-or-fp16-tolerance-bounded outputs versus Pearl's CUDA reference. **Used as the test oracle for Phase 1** — without it, you can't verify the Metal kernel's correctness against a portable baseline.

**Steps:**

1. Read `pearl/miner/pearl-gemm/csrc/gemm/` end-to-end. Catalog the protocol-relevant constants in `pearl_gemm_constants.hpp`:
   - `kAxEBLScaleFactor = 1 << 14`
   - `kEARxBpEBScaleFactor = 1 << 12`
   - `kIntToFp16ScaleFactor = 1 << 12`
   - `kEBRScaleFactorDenoise`, `kEALScaleFactorDenoise`
2. Read `pearl/py-pearl-mining/` to see what's already exposed in Python. If a reference impl already lives there, **use it**; do not duplicate.
3. If gaps exist, build them in PyTorch (CPU). Mirror the structure of the CUDA kernels:
   - `noise_generation.cu` → `noise_generation.py` — derive `EAL`, `EAR`, `EBL`, `EBR` from blake3-of-key + seed
   - `pearl_gemm` (matmul + noise) → `pearl_gemm.py` — compute `Y_noisy = (A + EAL·EAR) × (B + EBL·EBR)` with the documented scaling
   - `inner_hash_kernel.cu` → `inner_hash.py` — blake3 commitment over the noised matmul
   - `denoise_converter.cu` → `denoise.py` — recover `Y_clean = A·B` from `Y_noisy` and the noise components
   - `pow_utils.hpp` → `pow_check.py` — difficulty target check
4. Cross-check: run a corpus of 100+ inputs through the Pearl CUDA reference (on an H100 dev box; see §5.4) and through the Python reference. Assert outputs match within the documented tolerance — most likely **bit-exact for int paths and fp16-tolerance for the denoised result**.

**Exit criteria:**

- [ ] `tools/pearl-reference-oracle/` (in OJ repo, or separate repo) builds and tests pass
- [ ] Parity confirmed against Pearl CUDA on ≥100 input sets
- [ ] Constants table documented in this spec (replace the bullet list above with the verified values)

### 5.3 Workstream P0-C: Apple-side viability

**Goal:** Decide between MLX and llama.cpp Metal as the integration host before designing the kernel.

**Decision criteria:**

| Factor | MLX (`ml-explore/mlx`, `mlx-lm`) | llama.cpp Metal (`ggerganov/llama.cpp`) |
|---|---|---|
| Op-replacement hooks | Less mature; would likely require monkey-patching `mlx.nn.Linear` or upstream PR adding plugin hooks | More mature; `ggml` op tree is open and Metal backend has clear extension points (`ggml-metal.metal`) |
| Apple-native quantization story | Excellent (4-bit, 8-bit native ops) | Good but not as native |
| Inference-quality fidelity for OJ users today | High — MLX-LM is the de facto Mac LLM stack | High — also widely used |
| Upstream-contribution complexity | Higher (smaller team, less plugin culture) | Lower (large open community, clear contributor flow) |
| Ecosystem alignment with OJ engine map | OJ's `engine/` doesn't currently have an MLX engine; would need both | OJ already has llama.cpp via `engine/openai_compat_engines.py` |

**Recommendation:** **llama.cpp Metal first**, MLX as a fast-follow. Reasoning: ggml's op tree gives a cleaner extension path for a custom NoisyGEMM op; OJ already has llama.cpp engine wiring; and the upstream-contribution path is more navigable. MLX is a better long-term fit for Apple-native users but is currently a harder integration target.

**Steps:**

1. Spike: implement a no-op "custom op" passthrough in llama.cpp Metal. ~1-2 days work to confirm the integration mechanism is real and the build pipeline cooperates.
2. Spike: same in MLX. Compare effort.
3. Pick one. Document the decision in this spec.

**Exit criteria:**

- [ ] Decision made and documented in §6.2
- [ ] Trivial plugin hook proven on the chosen backend

### 5.4 Hardware required for Phase 0

- One H100/H200 box (cloud rental fine — Lambda, RunPod, Crusoe). Used for: running Pearl's CUDA reference to capture parity test vectors, running the Pearl Docker miner end-to-end as a known-good baseline.
- Apple Silicon dev machines: M2 Max minimum, M3/M4 Pro+ preferred. M-series Ultra ideal for any perf experiments.
- Estimated cloud cost for Phase 0: < $200.

## 6. Phases 1 and 2 — kernel and plugin

### 6.1 Phase 1 — Metal NoisyGEMM kernel

**Goal:** A Metal compute-shader implementation of NoisyGEMM that produces outputs matching the Phase 0 reference oracle, performant enough to make Mac mining a real (if low-yield) feature.

#### 6.1.1 Implementation surface

Two viable targets, in order of preference:

**A. Direct Metal Shading Language (MSL) compute kernels.** Maximum control, maximum performance ceiling, maximum effort. The CUDA reference is highly tuned (TMA, WGMMA, multi-stage pipelines); a direct MSL port can lean on Apple's matmul intrinsics where they exist (`simdgroup_matrix` ops on M3+).

**B. Metal Performance Shaders Graph (MPSGraph).** Higher-level than raw MSL; uses Apple's tuned matmul kernels under the hood; limited control over the in-kernel commitment hash. Likely path: do the matmul via MPSGraph, do noise generation + commitment hashing as separate kernels, accept the perf hit from less fusion.

**Recommendation:** Start with B for correctness and shipping speed; profile; move hot paths to A only if economically justified. Apple's matmul intrinsics are fast enough that the perf gap to a fused implementation may be acceptable.

#### 6.1.2 Algorithm structure

Following the Pearl CUDA reference, end-to-end work performed for one mining attempt:

1. **Quantize inputs.** `A: fp16 → int8 + scale_A`, `B: fp16 → int8 + scale_B`. Match Pearl's `quantize_kernel.cu` semantics (per-row or per-channel scales — verify via Phase 0 oracle).
2. **Generate noise tensors.** From `key_A`, `key_B` (per-block blake3-derived seeds), produce `EAL` (m, R), `EAR` (k, R), `EBL` (k, R), `EBR` (n, R) of int8. Scale factors per `pearl_gemm_constants.hpp`.
3. **Noisy matmul.** Compute `Y_noisy = (A + EAL · EAR_T) × (B + EBL · EBR_T)`. Output is int32 then converted to fp16.
4. **Inner-hash commitment.** blake3 over `Y_noisy` (or a row-tile of it) to produce the PoW target candidate. This is the hottest path — the noise + commitment loop runs at every share.
5. **PoW check.** Compare commitment digest against the difficulty target (`make_pow_target_tensor` semantics from Pearl's Python interface).
6. **On hit: denoise.** Compute `Y_clean = Y_noisy - (noise contributions)` to feed back into vLLM/MLX as the actual matmul output. Inference cannot be wrong.
7. **Post-hit: STARK proof generation.** When a share meets the network difficulty target, the miner generates a plonky2 STARK proof tying the noisy matmul + commitment to the block. This proving step is **separate from the Metal kernel** — it runs in pure Rust via Pearl's existing `zk-pow/` and `py-pearl-mining` code paths and should work cross-platform unchanged. Cost: seconds-to-minutes of CPU per block. Confirm cross-platform builds during Phase 0-C and §7.5.

#### 6.1.3 Crate / package layout

Strong preference: **upstream contribution to Pearl** as `pearl/miner/pearl-gemm-metal/` paralleling the existing `pearl-gemm/`:

```
pearl/miner/pearl-gemm-metal/
    Cargo.toml          (or pyproject.toml + setup.py — match Pearl conventions)
    metal/              (.metal MSL source files)
    src/
        lib.rs          (or src/pearl_gemm_metal/__init__.py)
    tests/
```

If upstream contribution is blocked (Phase 0 outcome), fork with attribution into `OpenJarvis/vendor/pearl-gemm-metal/` and document the divergence policy in this spec.

#### 6.1.4 Testing

- **Parity tests.** Each kernel (noise gen, matmul, inner hash, denoise, PoW check) tested independently against the Phase 0 reference oracle. Bit-exact for int paths; fp16-tolerance bounded for fp paths (specific tolerance: TBD via Phase 0 measurement).
- **End-to-end correctness.** Full mining attempt produces a candidate proof that the reference Rust prover (`zk-pow/`) accepts.
- **Hardware fuzz.** Run on M1 Pro, M2 Max, M3 Max, M4 Max, and M-Ultra variants. Catch any silently-wrong hardware behavior (Metal feature variance across generations is real).

#### 6.1.5 Performance expectations

Honest baseline: **expect 0.05–0.2× the share rate of an H100** on a high-end M-Ultra, and proportionally less on smaller chips. Reasons:

- H100 has dedicated FP8/FP16 tensor cores with WGMMA throughput Apple Silicon does not match
- Pearl's CUDA kernel is heavily fused (matmul + noise + commitment in one kernel via TMA pipelining); a Metal version will likely be less fused
- 70B model bandwidth requirements stress unified memory

This is fine. Mac mining is a feature for Apple Silicon owners who want to participate, not a competitive yield product. Document it transparently in `mine doctor` and the user guide.

#### 6.1.6 Exit criteria for Phase 1

- [ ] Parity tests pass on M2 Max and M4 Max
- [ ] End-to-end mining attempt produces a valid proof accepted by `zk-pow::verify_block`
- [ ] Performance characterized and published (M-series matrix)
- [ ] Code merged upstream OR forked-with-policy per Phase 0 outcome

### 6.2 Phase 2 — Inference-backend plugin

**Goal:** A llama.cpp Metal (or MLX, per Phase 0-C) plugin that swaps the standard quantized linear op for Phase 1's NoisyGEMM during inference, so a Mac running this plugin produces both correct LLM outputs and valid mining shares.

#### 6.2.1 Path: llama.cpp Metal (assuming Phase 0-C selected this)

- Add a custom `ggml` op `GGML_OP_PEARL_NOISY_GEMM` with a Metal backend implementation that calls Phase 1's kernels.
- Plugin entry point: a small library that, when loaded, replaces the default linear op in the model graph during loading.
- Build artifact: `libpearl_metal_plugin.dylib` (or static lib).

#### 6.2.2 Path: MLX (alternate)

- Define `mlx.NoisyLinear` as a subclass of `mlx.nn.Linear` that calls Phase 1's kernels via a custom Metal op binding.
- Provide a model-loading shim: `from openjarvis.mining import patch_mlx_for_pearl; patch_mlx_for_pearl()` that monkey-patches `mlx.nn.Linear` instances at load time. Less elegant; works.

#### 6.2.3 Inference-quality regression tests

The plugin is correctness-critical: a noised model that doesn't fully denoise produces degraded responses. Test:

- Load a small reference model (e.g., a 1-3B parameter Pearl-blessed model if one exists for testing, otherwise the smallest model the protocol accepts).
- Run a fixed prompt set through both noised+denoised and standard paths.
- Assert outputs are bit-exact or within fp16 tolerance.
- Run OJ's existing eval framework (`src/openjarvis/evals/`) on a small benchmark (e.g., an MMLU subset registered as a Pearl-mining-mode dataset). Assert no degradation > the tolerance budget. Falling back to `lm-eval-harness` is acceptable if OJ's eval surface for Mac is incomplete at the time.

#### 6.2.4 Exit criteria

- [ ] Plugin loads in chosen backend
- [ ] End-to-end inference produces correct outputs (regression tests pass)
- [ ] Mining shares are submitted to a Pearl testnet during inference
- [ ] At least one block found on testnet from a Mac

## 7. Phase 3 — OpenJarvis provider integration

Where the OJ-side work is small. Inherits the entire `MiningProvider` ABC, registry, sidecar, config schema, telemetry adapter, and v2 seams from Spec A unchanged.

### 7.1 New files

```
src/openjarvis/mining/
    llamacpp_pearl_metal.py    # OR mlx_pearl.py — depending on Phase 2 path
                                # @MinerRegistry.register("llamacpp-pearl-metal")
                                # implements MiningProvider ABC from Spec A §4.4
```

### 7.2 New optional extra

```toml
# pyproject.toml
mining-pearl-metal = [
    "pearl-metal-plugin>=0.1",   # the Phase 2 plugin, however published
    # MLX path adds: "mlx>=0.X", "mlx-lm>=0.X"
    # llama.cpp path adds: "llama-cpp-python>=0.X" with Metal extras
]
```

### 7.3 Capability detection

```python
# src/openjarvis/mining/llamacpp_pearl_metal.py
class LlamaCppPearlMetalProvider(MiningProvider):
    provider_id = "llamacpp-pearl-metal"

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        if hw.platform != "darwin":
            return MiningCapabilities(False, reason="Apple Silicon required (platform != darwin)")
        if hw.gpu is None or hw.gpu.vendor != "apple":
            return MiningCapabilities(False, reason="Apple Silicon GPU required")
        if engine_id not in {"llamacpp", "llama-cpp"}:
            return MiningCapabilities(False, reason=f"engine '{engine_id}' has no Pearl Metal plugin; use llamacpp")
        if not _pearl_metal_plugin_available():
            return MiningCapabilities(False, reason="install with `uv sync --extra mining-pearl-metal`")
        if not _model_has_pearl_variant(model):
            return MiningCapabilities(False, reason=f"model '{model}' has no Pearl-blessed variant")
        return MiningCapabilities(True, estimated_hashrate=_estimate_hashrate(hw))
```

Each branch is exactly the kind of "why can't I mine" message Spec A's `mine doctor` surfaces verbatim.

### 7.4 Lifecycle

Unlike Spec A's vLLM provider which orchestrates a Docker container, the Apple provider runs **two coordinated subprocesses directly on the host**:

1. The inference server (llama.cpp server with the Pearl Metal plugin loaded, or MLX-LM server depending on Phase 0-C path)
2. `pearl-gateway` as a sibling process — same one that runs inside the Docker container in Spec A, but here it runs natively on the Mac

Lifecycle:

- `start()`: spawn (1) with the Pearl Metal plugin pre-loaded (`DYLD_INSERT_LIBRARIES`-style or `--plugin` flag depending on chosen backend's invocation contract), then spawn (2) pointing at it. Write the same sidecar shape Spec A defines, with `gateway_url` pointing at the native pearl-gateway. Track both PIDs internally.
- `stop()`: SIGTERM (2) first, then (1), with bounded waits and SIGKILL fallback. Remove sidecar.
- `is_running()`, `stats()`: identical contract to vLLM provider; `stats()` reads from the native pearl-gateway's `:8339/metrics`.

**No Docker.** Apple Silicon Docker doesn't pass through Metal; running Pearl in a Mac Docker container would defeat the purpose. Document this explicitly in §7 of this spec; do not attempt a Docker path.

### 7.5 Pearl gateway on Mac

The Pearl `pearl-gateway` process is currently only documented as part of the Docker container. For Mac, we need it to run natively. Two options:

1. Build `pearl-gateway` from source via `uv sync --package pearl-gateway` — same workspace package the Docker image uses. Should work cross-platform since it's pure Python plus py-pearl-mining bindings. Verify.
2. If (1) fails on Apple Silicon, work with Pearl maintainers (Phase 0-A) to port it — a small amount of work compared to the kernel.

**Phase 3 verifies (1).** This is a Phase 0-A coordination point.

### 7.6 Exit criteria

- [ ] `LlamaCppPearlMetalProvider` registered, detection matrix correct on M1/M2/M3/M4
- [ ] `jarvis mine init` runs to completion on Apple Silicon
- [ ] `jarvis mine start` launches subprocess + Pearl gateway on Mac
- [ ] `jarvis mine status` returns valid `MiningStats` from a real Mac mining session
- [ ] `jarvis mine doctor` produces honest, actionable output for Mac users

## 8. Phase 4 — Verification & bringup

### 8.1 Hardware matrix

| Chip | Test priority | Expected outcome |
|---|---|---|
| M1 / M1 Pro / M1 Max | low — generation 1 GPU may have feature gaps | works but slow |
| M2 / M2 Pro / M2 Max | medium | works |
| M2 Ultra | medium | best M2-class hashrate |
| M3 / M3 Pro / M3 Max | high — first gen with `simdgroup_matrix` | works, meaningful share rate |
| M4 / M4 Pro / M4 Max | high — current flagship | best non-M-Ultra hashrate |

For each chip in the matrix, run:

1. `jarvis mine init` end-to-end
2. `jarvis mine start` and run for ≥4 h continuous
3. Capture and publish: shares submitted, shares accepted, block-find time distribution, GPU temp, system load impact on normal use
4. Run a parallel `lm-eval-harness` on the mining endpoint to assert inference quality is unaffected

### 8.2 Pearl testnet bringup

Before any mainnet recommendation:

- Mine on Pearl testnet for ≥7 continuous days from at least two Apple Silicon variants
- Find at least one block on testnet from each variant
- Verify all blocks accepted by `zk-pow::verify_block` on a reference validator node
- Report results to Pearl maintainers; gate any mainnet announcement on their sign-off

### 8.3 Documentation deliverables

- `docs/user-guide/mining-apple-silicon.md` — user-facing: prerequisites, install flow, doctor reading guide, performance expectations table, links to share-rate calculators
- `docs/development/mining-providers.md` — generalized "how to add a new provider" guide using this spec as the canonical worked example
- An update to `docs/user-guide/mining.md` (Spec A) adding Apple Silicon to the supported-platforms list

### 8.4 Exit criteria

- [ ] Hardware matrix covered
- [ ] Testnet bringup complete
- [ ] Documentation merged
- [ ] Pearl maintainer sign-off obtained
- [ ] OJ release notes call out Apple Silicon mining as supported

## 9. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Pearl validator rejects non-CUDA-mined blocks despite hardware-neutral validator code | low (validator code reviewed) | catastrophic (whole spec invalid) | Phase 0-A explicit confirmation; Phase 0-B oracle reduces likelihood of math drift |
| R2 | Pearl ships their own Metal port, conflicts with OJ's | medium (depends on Pearl roadmap) | high (rework or fork) | Phase 0-A coordination; default to upstream contribution |
| R3 | Metal NoisyGEMM is so slow that mining is uneconomical even for hobbyists | medium-high | medium (feature ships but unused) | §4.3 names this as a non-goal; transparency in `mine doctor`; consider M-Ultra-only-by-default in v1 of this spec |
| R4 | NoisyGEMM correctness bug → invalid blocks → wasted user electricity | low if §6.1.4 testing rigorous | high (trust hit) | Strong parity testing against oracle; testnet bringup before mainnet |
| R5 | Inference-quality regression — denoised path doesn't fully recover model fidelity | medium | high | §6.2.3 regression tests; eval-harness gate before ship |
| R6 | Pearl protocol changes between Phase 0 and Phase 4 (multi-month) | medium | medium | Pin Phase 0 ref same as Spec A; renegotiate at each Pearl rev |
| R7 | Apple changes Metal API in macOS update | low-medium | medium | Use stable MSL features; pin Xcode toolchain |
| R8 | Upstream Pearl PR rejected | low (Pearl wants this) | medium (forced fork) | Phase 0-A negotiates upstream-vs-fork up front |
| R9 | `pearl-gateway` doesn't build on Apple Silicon (§7.5) | medium (it's Python — should work, but py-pearl-mining has Rust deps) | low (small fix) | Phase 0 verifies builds; Phase 0-A coordination if not |

## 10. Open questions to resolve before / during Phase 0

1. Is there a Pearl-blessed "small" model for testing? The reference miner uses a 70B model — too big for fast iteration. A 7B or 13B variant for development would dramatically speed up Phase 1 and 2.
2. What is the documented fp16 tolerance budget for the denoised matmul output? Phase 0-B must measure it; the spec assumes "fp16 tolerance" but a precise epsilon is needed for parity tests.
3. Does `py-pearl-mining` already expose enough of NoisyGEMM in Python that Phase 0-B becomes a thin wrapper rather than a reimplementation? Read it first.
4. Is `pearl-gateway` already cross-platform, or does it need Apple-specific work?
5. Does Pearl gate any of the difficulty / consensus parameters on hardware introspection that would penalize non-CUDA miners (unlikely, but worth verifying)?
6. What's the minimum acceptable hashrate for `jarvis mine init` to *let* a Mac user enable mining? Should `mine doctor` warn loudly below some floor? `MiningCapabilities.estimated_hashrate` field exists in Spec A's schema for exactly this.
7. Upstream contribution: does Pearl require a CLA? LICENSE compatibility: ISC ↔ Apache-2.0 should be fine but confirm.
8. Apple Silicon CI: GitHub Actions has `macos-14`/`macos-15` runners with Apple Silicon; can OJ's CI run this provider's tests? (Likely yes, provided we don't try to mine in CI — just unit-test the kernel against the oracle.)
9. Verify the actual `engine_id` registry key for llama.cpp in OJ's `EngineRegistry`. Spec uses `"llamacpp"` / `"llama-cpp"` placeholders in §7.3; grep `src/openjarvis/engine/openai_compat_engines.py` to confirm the canonical key before implementing capability detection.
10. Confirm whether plonky2 STARK proving on Apple Silicon CPU is performant enough that block-find latency stays within network expectations. If proving takes minutes on M-class CPU and the network expects sub-second proof submission, this becomes a blocking issue.

## 11. Cross-references

- **[Spec A](2026-05-05-vllm-pearl-mining-integration-design.md)** — the v1 integration this extends. Read §4.4 (the `MiningProvider` ABC), §5.3 (sidecar shape), §8.1–8.2 (telemetry adapter contract), §8.5 (v2 fee/pool seams). All apply unchanged.
- **Pearl repo paths to read in order:**
  1. `pearl/zk-pow/src/api/verify.rs` — the validator (proves hardware neutrality)
  2. `pearl/miner/pearl-gemm/csrc/gemm/pearl_gemm_constants.hpp` — protocol-relevant constants
  3. `pearl/miner/pearl-gemm/csrc/gemm/` — the rest of the CUDA kernel for algorithm structure
  4. `pearl/py-pearl-mining/` — possible reference oracle starting point
  5. `pearl/miner/pearl-gateway/` — verify cross-platform buildability (§7.5)
  6. `pearl/miner/vllm-miner/` — for plugin hook patterns to mirror in Phase 2
- **Pearl paper:** [Proof-of-Useful-Work via matrix multiplication (arXiv:2504.09971)](https://arxiv.org/abs/2504.09971) — read for the math formalization before Phase 0-B.
- **Apple references:**
  - [Metal Shading Language Specification](https://developer.apple.com/metal/Metal-Shading-Language-Specification.pdf)
  - [MPS / MPSGraph documentation](https://developer.apple.com/documentation/metalperformanceshadersgraph)
  - [MLX](https://github.com/ml-explore/mlx) — alternative Phase 2 host
- **Coordination thread:** TBD — Phase 0-A creates the Pearl Discussion / issue link; cite here once opened.

## 12. Implementation plan

The implementation plan for Spec B is a separate document, written via the `superpowers:writing-plans` skill **after Phase 0 outcomes are known**. Phase 0 is small enough to execute against this spec directly. Phases 1–4 should each get their own implementation plan; do not write a single monolithic plan covering all four — the timelines and ownership differ too much.
