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
        model_id="pearl-ai/Gemma-4-31B-it-pearl",
        base_model_id="google/gemma-4-31B-it",
        status="planned",
        min_vram_gb=80.0,
        default_max_model_len=8192,
        notes=(
            "Public Pearl org artifact; requires H100/H200 validation in "
            "OpenJarvis before mining is enabled by default."
        ),
    ),
    PearlModelSpec(
        model_id="pearl-ai/Llama-3.1-8B-Instruct-pearl",
        base_model_id="meta-llama/Llama-3.1-8B-Instruct",
        status="planned",
        min_vram_gb=24.0,
        default_max_model_len=8192,
        notes=(
            "Public Pearl org artifact; requires H100/H200 validation in "
            "OpenJarvis before mining is enabled by default."
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
