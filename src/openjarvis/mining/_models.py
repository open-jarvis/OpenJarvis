"""Pearl mining model support registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from openjarvis.mining._constants import DEFAULT_PEARL_MODEL

PearlModelStatus = Literal["validated", "planned"]


@dataclass(frozen=True)
class PearlModelSpec:
    """OpenJarvis support metadata for a Pearl-compatible model."""

    model_id: str
    base_model_id: str
    status: PearlModelStatus
    provider: str = "vllm-pearl"
    min_vram_gb: float = 70.0
    default_max_model_len: int = 8192
    default_gpu_memory_utilization: float = 0.96
    notes: str = ""

    @property
    def is_validated(self) -> bool:
        return self.status == "validated"


PEARL_MODEL_SPECS: tuple[PearlModelSpec, ...] = (
    PearlModelSpec(
        model_id=DEFAULT_PEARL_MODEL,
        base_model_id="meta-llama/Llama-3.3-70B-Instruct",
        status="validated",
        min_vram_gb=70.0,
        default_max_model_len=8192,
        notes="Default Pearl-blessed vLLM mining model.",
    ),
    PearlModelSpec(
        model_id="pearl-ai/Qwen3.5-9B-pearl",
        base_model_id="Qwen/Qwen3.5-9B",
        status="planned",
        min_vram_gb=24.0,
        default_max_model_len=8192,
        notes=(
            "Planned target; Pearl artifact is not publicly available yet. "
            "Validation tracked in open-jarvis/OpenJarvis#316."
        ),
    ),
    PearlModelSpec(
        model_id="ScalingIntelligence/Qwen3.5-9B-pearl",
        base_model_id="Qwen/Qwen3.5-9B",
        status="validated",
        min_vram_gb=24.0,
        default_max_model_len=4096,
        notes=(
            "Experimental OpenJarvis/Pearl artifact validated on H100. "
            "Runtime requires --language-model-only, --skip-mm-profiling, "
            "and --gdn-prefill-backend triton."
        ),
    ),
    PearlModelSpec(
        model_id="pearl-ai/Qwen3.6-27B-pearl",
        base_model_id="Qwen/Qwen3.6-27B",
        status="planned",
        min_vram_gb=80.0,
        default_max_model_len=8192,
        notes=(
            "Planned target; Pearl artifact is not publicly available yet. "
            "Validation tracked in open-jarvis/OpenJarvis#317."
        ),
    ),
    PearlModelSpec(
        model_id="pearl-ai/Gemma-4-E4B-it-pearl",
        base_model_id="google/gemma-4-E4B-it",
        status="planned",
        min_vram_gb=24.0,
        default_max_model_len=8192,
        notes=(
            "Planned target; Pearl artifact is not publicly available yet. "
            "Validation tracked in open-jarvis/OpenJarvis#318."
        ),
    ),
    PearlModelSpec(
        model_id="pearl-ai/Gemma-4-31B-it-pearl",
        base_model_id="google/gemma-4-31B-it",
        status="planned",
        min_vram_gb=80.0,
        default_max_model_len=8192,
        notes=(
            "Artifact exists but H100 validation is blocked by missing Gemma4 "
            "processor/preprocessor metadata in the published Pearl artifact. "
            "Validation tracked in open-jarvis/OpenJarvis#319."
        ),
    ),
    PearlModelSpec(
        model_id="ScalingIntelligence/Gemma-4-31B-it-pearl",
        base_model_id="google/gemma-4-31B-it",
        status="validated",
        min_vram_gb=80.0,
        default_max_model_len=8192,
        notes=(
            "Experimental OpenJarvis/Pearl artifact validated on H100 with "
            "Gemma4 processor/preprocessor metadata included."
        ),
    ),
)

_MODEL_SPECS_BY_ID = {spec.model_id: spec for spec in PEARL_MODEL_SPECS}
_MODEL_SPECS_BY_BASE_ID = {spec.base_model_id: spec for spec in PEARL_MODEL_SPECS}


def iter_pearl_model_specs() -> tuple[PearlModelSpec, ...]:
    """Return all known Pearl model specs in display order."""

    return PEARL_MODEL_SPECS


def get_pearl_model_spec(model_id: str) -> PearlModelSpec | None:
    """Return support metadata for a Pearl model id or its raw base id."""

    return _MODEL_SPECS_BY_ID.get(model_id) or _MODEL_SPECS_BY_BASE_ID.get(model_id)


def pearl_variant_for_base_model(model_id: str) -> str | None:
    """Return the planned Pearl model id for a raw base model id, if known."""

    spec = _MODEL_SPECS_BY_BASE_ID.get(model_id)
    return spec.model_id if spec else None


__all__ = [
    "PearlModelSpec",
    "get_pearl_model_spec",
    "iter_pearl_model_specs",
    "pearl_variant_for_base_model",
]
