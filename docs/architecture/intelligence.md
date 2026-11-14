# Intelligence Primitive

The Intelligence primitive represents **the model** — its identity, weights, quantization format, fallback chain, and the catalog of well-known models with detailed metadata. It no longer contains routing logic; query analysis and model selection have moved to the [Learning primitive](learning.md).

---

## Purpose

The Intelligence primitive answers a single question: *what is the model?* It maintains a catalog of known models with metadata (parameter count, context length, VRAM requirements, supported engines) and provides helpers for registering built-in models and merging models discovered from running engines at runtime.

The primitive provides three key capabilities:

1. **Model catalog** -- a registry of well-known models with metadata (parameter count, context length, VRAM requirements, supported engines)
2. **Auto-discovery** -- merging models discovered from running engines into the catalog
3. **Model configuration** -- `IntelligenceConfig` captures the local model's identity, weight paths, quantization, and preferred engine

!!! info "Routing has moved"
    Query analysis (`build_routing_context`) and model selection (`HeuristicRouter`, `RouterPolicy` ABC) now live in the [Learning primitive](learning.md). Backward-compatible re-exports remain in `intelligence/_stubs.py` and `intelligence/router.py` so existing code continues to work.

---

## ModelSpec

Every model in the system is described by a `ModelSpec` dataclass, defined in `core/types.py`:

```python
@dataclass(slots=True)
class ModelSpec:
    model_id: str                              # Unique identifier (e.g., "qwen3:8b")
    name: str                                  # Human-readable name
    parameter_count_b: float                   # Total parameters in billions
    context_length: int                        # Maximum context window (tokens)
    active_parameter_count_b: Optional[float]  # MoE active params (None for dense)
    quantization: Quantization                 # Quantization format (none, fp8, int4, etc.)
    min_vram_gb: float                         # Minimum VRAM required
    supported_engines: Sequence[str]           # Which engines can run this model
    provider: str                              # Model provider (e.g., "alibaba", "meta")
    requires_api_key: bool                     # Whether cloud API key is needed
    metadata: Dict[str, Any]                   # Additional metadata (pricing, architecture)
```

Models are registered in the `ModelRegistry`:

```python
from openjarvis.core.registry import ModelRegistry

# Register a model
ModelRegistry.register_value("qwen3:8b", ModelSpec(
    model_id="qwen3:8b",
    name="Qwen3 8B",
    parameter_count_b=8.2,
    context_length=32768,
    supported_engines=("vllm", "ollama", "llamacpp", "sglang"),
    provider="alibaba",
))
```

---

## Model Catalog

The built-in model catalog is defined in `intelligence/model_catalog.py` as the `BUILTIN_MODELS` list. It includes models across three categories:

### Local Models -- Dense

| Model ID | Name | Parameters | Context | Supported Engines |
|----------|------|-----------|---------|-------------------|
| `qwen3:8b` | Qwen3 8B | 8.2B | 32K | vLLM, Ollama, llama.cpp, SGLang |
| `qwen3.5:9b` | Qwen3.5 9B (vision) | 9B | 128K | vLLM, Ollama, llama.cpp, SGLang, MLX |
| `qwen3:32b` | Qwen3 32B | 32B | 32K | Ollama, vLLM |
| `llama3.3:70b` | Llama 3.3 70B | 70B | 128K | Ollama, vLLM |
| `llama3.2:3b` | Llama 3.2 3B | 3B | 128K | Ollama, vLLM, llama.cpp |
| `deepseek-coder-v2:16b` | DeepSeek Coder V2 16B | 16B | 128K | Ollama, vLLM |
| `mistral:7b` | Mistral 7B | 7B | 32K | Ollama, vLLM, llama.cpp |

The Qwen3.5 9B llama.cpp download uses the Q4_K_M GGUF (5.7 GB) and automatically
downloads its F16 vision projector (0.9 GB) from the same Hugging Face repository.

### Local Models -- Mixture of Experts (MoE)

| Model ID | Name | Total / Active Params | Context | Min VRAM |
|----------|------|----------------------|---------|----------|
| `gpt-oss:120b` | GPT-OSS 120B | 117B / 5.1B | 128K | 12 GB |
| `glm-4.7-flash` | GLM 4.7 Flash | 30B / 3B | 128K | 8 GB |
| `trinity-mini` | Trinity Mini | 26B / 3B | 128K | 8 GB |

### Cloud Models

| Model ID | Provider | Context | Pricing (input/output per 1M tokens) |
|----------|----------|---------|--------------------------------------|
| `gpt-4o` | OpenAI | 128K | $2.50 / $10.00 |
| `gpt-4o-mini` | OpenAI | 128K | $0.15 / $0.60 |
| `gpt-5-mini` | OpenAI | 400K | $0.25 / $2.00 |
| `claude-sonnet-4-20250514` | Anthropic | 200K | $3.00 / $15.00 |
| `claude-opus-4-20250514` | Anthropic | 200K | $15.00 / $75.00 |
| `claude-opus-4-6` | Anthropic | 200K | $5.00 / $25.00 |
| `gemini-2.5-pro` | Google | 1M | $1.25 / $10.00 |
| `gemini-2.5-flash` | Google | 1M | $0.30 / $2.50 |

### Registering Built-in Models

The `register_builtin_models()` function populates the `ModelRegistry` with all built-in models. It skips models that are already registered, making it safe to call multiple times:

```python
from openjarvis.intelligence import register_builtin_models

register_builtin_models()
# All BUILTIN_MODELS are now in ModelRegistry
```

---

## Auto-Discovery: Merging Runtime Models

When engines are discovered at runtime, they report models that may not be in the built-in catalog. The `merge_discovered_models()` function creates minimal `ModelSpec` entries for these:

```python
from openjarvis.intelligence import merge_discovered_models

# Models reported by Ollama that aren't in the catalog
merge_discovered_models("ollama", ["phi3:3.8b", "codellama:7b"])
```

For each model ID not already in the registry, a `ModelSpec` is created with the model ID as both the `model_id` and `name`, with zero-value defaults for unknown fields. This ensures the routing system can still select from all available models, even ones it has no metadata for.

---

## IntelligenceConfig

The `IntelligenceConfig` dataclass (in `core/config.py`) captures the full identity of the model the system is configured to use, as well as the default sampling parameters for generation:

```python
@dataclass(slots=True)
class IntelligenceConfig:
    """The model — identity, paths, quantization, fallback chain, and generation defaults."""

    default_model: str = ""       # Primary model key (e.g., "qwen3:8b")
    fallback_model: str = ""      # Fallback when default is unavailable
    model_path: str = ""          # Local weights (HF repo, GGUF file, etc.)
    checkpoint_path: str = ""     # Checkpoint/adapter path (e.g., LoRA)
    quantization: str = "none"    # none, fp8, int8, int4, gguf_q4, gguf_q8
    preferred_engine: str = ""    # Override engine for this model (e.g., "vllm")
    provider: str = ""            # local, openai, anthropic, google
    # Generation defaults (overridable per-call)
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 0.9
    top_k: int = 40
    repetition_penalty: float = 1.0
    stop_sequences: str = ""      # Comma-separated stop strings
```

### Model Identity Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `default_model` | `str` | `""` | Primary model registry key. Resolved at startup; overrides any engine default. |
| `fallback_model` | `str` | `""` | Used when the default model is not available on any running engine. |
| `model_path` | `str` | `""` | Path or HuggingFace repo ID for local weights (e.g., `"./models/qwen3-8b.gguf"` or `"Qwen/Qwen3-8B"`). |
| `checkpoint_path` | `str` | `""` | Path to a fine-tuned checkpoint or LoRA adapter directory. |
| `quantization` | `str` | `"none"` | Quantization format. Accepted values: `none`, `fp8`, `int8`, `int4`, `gguf_q4`, `gguf_q8`. |
| `preferred_engine` | `str` | `""` | When set, `SystemBuilder`, `sdk.py`, and `cli/ask.py` use this engine key instead of `config.engine.default`. |
| `provider` | `str` | `""` | Model provider hint: `local`, `openai`, `anthropic`, `google`. Used by the Cloud engine backend to route API calls. |

### Generation Default Fields

These fields set the default sampling parameters for every inference call. Individual calls can override them by passing keyword arguments to `engine.generate()`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `temperature` | `float` | `0.7` | Sampling temperature. Lower values produce more deterministic output; higher values increase diversity. |
| `max_tokens` | `int` | `1024` | Maximum number of tokens to generate per call. |
| `top_p` | `float` | `0.9` | Nucleus sampling probability mass. At each step, only tokens comprising the top-p probability mass are considered. |
| `top_k` | `int` | `40` | Top-k sampling: only consider the top-k most likely tokens at each step. |
| `repetition_penalty` | `float` | `1.0` | Penalize repeated token sequences. Values greater than 1.0 reduce repetition. |
| `stop_sequences` | `str` | `""` | Comma-separated stop strings. Generation halts when any stop string appears in the output. |

!!! note "Moved from Agent"
    Generation parameters (`temperature`, `max_tokens`) previously lived under `[agent]` in the config file. They now live under `[intelligence]`. Old configs with these fields under `[agent]` are automatically migrated at load time. See the [configuration migration guide](../getting-started/configuration.md#migration-guide) for details.

### TOML Configuration

```toml
[intelligence]
default_model = "qwen3:8b"
fallback_model = "llama3.2:3b"
temperature = 0.7
max_tokens = 1024
# top_p = 0.9
# top_k = 40
# repetition_penalty = 1.0
# stop_sequences = ""

# Local weight overrides (optional)
# model_path = "./models/qwen3-8b-instruct.gguf"
# checkpoint_path = "./checkpoints/my-lora"
# quantization = "gguf_q4"

# Engine selection for this model (takes priority over [engine].default)
# preferred_engine = "vllm"

# Provider for cloud models
# provider = "openai"
```

### Engine Selection Priority

When resolving which engine to use, `SystemBuilder`, `sdk.py`, and `cli/ask.py` check `config.intelligence.preferred_engine` before `config.engine.default`:

```
1. Explicit --engine CLI flag or engine_key= SDK parameter
2. config.intelligence.preferred_engine  ← new field
3. config.engine.default
4. First healthy engine discovered at runtime
```

This lets you pin a specific model to a specific engine without changing the global engine default. For example, a GGUF quantized model can be pinned to `llamacpp` while the global default remains `ollama`:

```toml
[engine]
default = "ollama"

[intelligence]
default_model = "llama3.2:3b"
model_path = "./models/llama-3.2-3b.Q4_K_M.gguf"
quantization = "gguf_q4"
preferred_engine = "llamacpp"
```

---

## Public API

`intelligence/__init__.py` exports exactly three names:

```python
from openjarvis.intelligence import (
    BUILTIN_MODELS,           # List[ModelSpec] — the full built-in catalog
    merge_discovered_models,  # (engine_key, model_ids) -> None
    register_builtin_models,  # () -> None
)
```

### Backward-Compatibility Shims

The following names are still importable from `openjarvis.intelligence` via shim modules, but their canonical locations have moved:

| Name | Old location | Canonical location |
|------|-------------|-------------------|
| `RouterPolicy` | `intelligence/_stubs.py` | `learning/_stubs.py` |
| `QueryAnalyzer` | `intelligence/_stubs.py` | `learning/_stubs.py` |
| `HeuristicRouter` | `intelligence/router.py` | `learning/router.py` |
| `build_routing_context` | `intelligence/router.py` | `learning/router.py` |
| `DefaultQueryAnalyzer` | `intelligence/router.py` | `learning/router.py` |

New code should import from the canonical `learning.*` locations. The shims in `intelligence/_stubs.py` and `intelligence/router.py` are retained for backward compatibility only.

---

## Integration with Learning

The Learning primitive consumes the model catalog to make routing decisions. The `HeuristicRouter` and `TraceDrivenPolicy` both read `ModelRegistry` to compare model sizes when selecting between candidates. See the [Learning & Traces](learning.md) documentation for full details on routing policies, the `RouterPolicy` ABC, and the trace-driven feedback loop.
