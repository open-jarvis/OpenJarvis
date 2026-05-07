# Adding a Mining Provider

The `openjarvis.mining` subsystem follows the same registry pattern as engines,
agents, tools, memory, and channels. New mining paths should be provider
modules, not special cases in the CLI or engine layer.

## Provider Contract

Every provider implements `openjarvis.mining.MiningProvider`:

- `detect(hw, engine_id, model)` is pure capability detection. It must not
  start subprocesses, hit the network, or mutate state.
- `start(config)` owns provider lifecycle setup and writes the mining sidecar
  when it changes inference routing.
- `stop()` tears down provider-owned processes or containers.
- `is_running()` answers from provider-owned state.
- `stats()` returns `MiningStats` using the provider's most stable telemetry
  surface.

Register providers through `MinerRegistry` and expose idempotent
`ensure_registered()`:

```python
from openjarvis.core.registry import MinerRegistry


def ensure_registered() -> None:
    if not MinerRegistry.contains("my-provider"):
        MinerRegistry.register_value("my-provider", MyProvider)
```

`tests/conftest.py` clears registries between tests, so test fixtures and CLI
entry points should call `ensure_registered()` before relying on a provider.

## Optional Dependencies

Provider dependencies belong in scoped extras:

- `mining-pearl-vllm` for the NVIDIA/vLLM Docker provider
- Future Apple work should use a separate extra such as `mining-pearl-metal`
  or `mining-pearl-cpu`

Avoid a generic `mining-pearl` extra until there is a shared dependency set
that every provider actually needs.

## Sidecar Contract

The runtime sidecar lives at `~/.openjarvis/runtime/mining.json`. Engine
handoff is data-driven:

- If the sidecar has `vllm_endpoint`, engine discovery registers
  `vllm-pearl-mining`.
- If a future provider mines alongside the user's normal engine, it should omit
  `vllm_endpoint`; engine discovery will ignore it.

Do not branch on `provider == "vllm-pearl"` in generic code. Branch on sidecar
shape or provider capability.

## Apple Silicon Handoff

The Apple Silicon effort should add its own provider module and reuse:

- `MiningProvider`
- `MinerRegistry`
- `MiningConfig`
- `MiningStats`
- `Sidecar`
- `jarvis mine doctor` capability iteration

That work should not need to rewrite the NVIDIA provider, CLI group, telemetry
collector, or engine sidecar handoff.

## NVIDIA Release Gate

The NVIDIA provider is not considered economically proven until the H100/H200
runbook passes on real hardware. See
[`mining-nvidia-validation.md`](./mining-nvidia-validation.md) for the required
commands, artifacts, and pass criteria.

## Model Enablement

New Pearl-compatible language models are tracked separately from provider
support. See [`pearl-model-enablement.md`](./pearl-model-enablement.md) for the
conversion and validation checklist.
