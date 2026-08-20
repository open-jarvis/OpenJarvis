#!/usr/bin/env python3
"""Create experimental Pearl-compatible compressed-tensors checkpoints.

This utility converts raw Hugging Face safetensors checkpoints into the minimal
Pearl quantization shape consumed by Pearl's vLLM plugin:

- int7 channel-wise weights for mining layers
- int8 channel-wise weights for non-mining layers
- dynamic token-wise symmetric activation metadata

It is intentionally conservative and aimed at Gemma4/Qwen3.5 enablement work.
It does not upload to Hugging Face and does not mark a model validated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import load_file, save_file

NON_MINING_RE = re.compile(
    r"(self_attn\.(q_proj|k_proj|v_proj|qkv_proj)|mlp\.down_proj)\.weight$"
)
IGNORED_TEXT_RE = re.compile(
    r"(^|\.)(embed_tokens|embed_tokens_per_layer|lm_head|norm|layernorm|layer_norm)"
    r"\.weight$"
)
IGNORED_MULTIMODAL_RE = re.compile(
    r"(^model\.(vision|audio|embed_vision)|vision_tower|vision_model|visual|audio)"
)


@dataclass(frozen=True)
class ConversionStats:
    copied: int = 0
    mining: int = 0
    non_mining: int = 0

    def add(self, kind: str) -> "ConversionStats":
        return ConversionStats(
            copied=self.copied + (kind == "copied"),
            mining=self.mining + (kind == "mining"),
            non_mining=self.non_mining + (kind == "non_mining"),
        )


def classify_weight(name: str, tensor: torch.Tensor) -> str:
    """Classify one safetensors entry as copied, mining, or non_mining."""

    if not name.endswith(".weight") or tensor.ndim != 2:
        return "copied"
    if IGNORED_TEXT_RE.search(name) or IGNORED_MULTIMODAL_RE.search(name):
        return "copied"
    if NON_MINING_RE.search(name):
        return "non_mining"
    return "mining"


def quantize_channelwise(
    weight: torch.Tensor,
    *,
    max_val: int,
    device: str,
    chunk_rows: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Symmetric per-output-channel int quantization for one 2D weight."""

    if weight.ndim != 2:
        raise ValueError(f"expected 2D weight, got shape {tuple(weight.shape)}")
    rows = weight.shape[0]
    q_chunks: list[torch.Tensor] = []
    scale_chunks: list[torch.Tensor] = []
    for start in range(0, rows, chunk_rows):
        chunk = weight[start : start + chunk_rows].to(
            device=device, dtype=torch.float32
        )
        scale = chunk.abs().amax(dim=1, keepdim=True) / float(max_val)
        scale = torch.where(scale == 0, torch.ones_like(scale), scale)
        quantized = torch.round(chunk / scale).clamp(-max_val, max_val).to(torch.int8)
        q_chunks.append(quantized.cpu())
        scale_chunks.append(scale.to(dtype=torch.bfloat16).cpu())
    return torch.cat(q_chunks, dim=0), torch.cat(scale_chunks, dim=0)


def quantization_config() -> dict[str, Any]:
    """Return the Pearl quantization config for generated checkpoints."""

    dynamic_token = {
        "actorder": None,
        "block_structure": None,
        "dynamic": True,
        "group_size": None,
        "num_bits": 7,
        "observer": None,
        "observer_kwargs": {},
        "strategy": "token",
        "symmetric": True,
        "type": "int",
    }
    weight_channel = {
        "actorder": None,
        "block_structure": None,
        "dynamic": False,
        "group_size": None,
        "num_bits": 7,
        "observer": "minmax",
        "observer_kwargs": {},
        "strategy": "channel",
        "symmetric": True,
        "type": "int",
    }

    int8_input = {**dynamic_token, "num_bits": 8}
    int8_weight = {**weight_channel, "num_bits": 8}

    return {
        "config_groups": {
            "group_0": {
                "format": "int-quantized",
                "input_activations": int8_input,
                "output_activations": None,
                "targets": [
                    "re:.*self_attn\\.[qkv]_proj$",
                    "re:.*self_attn\\.qkv_proj$",
                    "re:.*\\.down_proj$",
                ],
                "weights": int8_weight,
            },
            "group_1": {
                "format": "int-quantized",
                "input_activations": dynamic_token,
                "output_activations": None,
                "targets": ["Linear"],
                "weights": weight_channel,
            },
        },
        "format": "mixed-precision",
        "global_compression_ratio": None,
        "ignore": [
            "lm_head",
            "re:.*embed_tokens$",
            "re:.*embed_tokens_per_layer$",
            "re:.*vision.*",
            "re:.*visual.*",
            "re:.*vision_tower.*",
            "re:.*vision_model.*",
            "re:.*image.*",
            "re:.*audio.*",
            "re:.*embed_vision.*",
            "re:.*multi_modal_projector.*",
        ],
        "kv_cache_scheme": None,
        "quant_method": "pearl",
        "quantization_status": "compressed",
        "sparsity_config": {},
        "transform_config": {},
        "version": "0.13.0",
    }


def resolve_source(source: str, token: str | None) -> Path:
    """Resolve a local path or download a Hugging Face snapshot."""

    path = Path(source)
    if path.exists():
        return path
    from huggingface_hub import snapshot_download

    return Path(
        snapshot_download(
            source,
            token=token,
            allow_patterns=[
                "*.json",
                "*.jinja",
                "*.txt",
                "*.model",
                "*.safetensors",
                ".gitattributes",
            ],
        )
    )


def copy_metadata_files(source_dir: Path, output_dir: Path) -> None:
    """Copy non-safetensors model metadata into the output directory."""

    for src in source_dir.rglob("*"):
        if not src.is_file() or src.suffix == ".safetensors":
            continue
        rel = src.relative_to(source_dir)
        dst = output_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def patch_config(output_dir: Path) -> None:
    config_path = output_dir / "config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"missing {config_path}")
    config = json.loads(config_path.read_text())
    config["quantization_config"] = quantization_config()
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")


def patch_processor_metadata(output_dir: Path) -> None:
    """Provide compatibility filenames required by vLLM Gemma4 profiling."""

    config_path = output_dir / "config.json"
    if not config_path.exists():
        return
    config = json.loads(config_path.read_text())
    architectures = config.get("architectures") or []
    is_gemma4 = any(
        isinstance(item, str) and "Gemma4" in item for item in architectures
    )
    if not is_gemma4:
        return

    processor = output_dir / "processor_config.json"
    preprocessor = output_dir / "preprocessor_config.json"
    if processor.exists() and not preprocessor.exists():
        shutil.copy2(processor, preprocessor)


def convert_safetensors_file(
    src: Path,
    dst: Path,
    *,
    device: str,
    chunk_rows: int,
    dry_run: bool,
) -> tuple[int, dict[str, str], ConversionStats]:
    tensors = load_file(str(src), device="cpu")
    out: dict[str, torch.Tensor] = {}
    stats = ConversionStats()
    for name, tensor in tensors.items():
        kind = classify_weight(name, tensor)
        stats = stats.add(kind)
        if dry_run or kind == "copied":
            out[name] = tensor
            continue
        max_val = 63 if kind == "mining" else 127
        quantized, scale = quantize_channelwise(
            tensor,
            max_val=max_val,
            device=device,
            chunk_rows=chunk_rows,
        )
        out[name] = quantized
        out[f"{name.removesuffix('.weight')}.weight_scale"] = scale

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        save_file(out, str(dst))
    total_size = sum(tensor.nbytes for tensor in out.values())
    weight_map = {key: dst.name for key in out}
    return total_size, weight_map, stats


def write_index(output_dir: Path, total_size: int, weight_map: dict[str, str]) -> None:
    index = {
        "metadata": {"total_size": total_size},
        "weight_map": dict(sorted(weight_map.items())),
    }
    (output_dir / "model.safetensors.index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n"
    )


def convert_checkpoint(
    source: str,
    output_dir: Path,
    *,
    hf_token_env: str,
    device: str,
    chunk_rows: int,
    dry_run: bool,
) -> ConversionStats:
    token = os.environ.get(hf_token_env)
    source_dir = resolve_source(source, token)
    output_dir.mkdir(parents=True, exist_ok=True)

    safetensors_files = sorted(source_dir.glob("*.safetensors"))
    if not safetensors_files:
        raise FileNotFoundError(f"no .safetensors files found in {source_dir}")

    if not dry_run:
        copy_metadata_files(source_dir, output_dir)
        patch_config(output_dir)
        patch_processor_metadata(output_dir)

    total_size = 0
    weight_map: dict[str, str] = {}
    stats = ConversionStats()
    for src in safetensors_files:
        dst = output_dir / src.name
        file_size, file_map, file_stats = convert_safetensors_file(
            src,
            dst,
            device=device,
            chunk_rows=chunk_rows,
            dry_run=dry_run,
        )
        total_size += file_size
        weight_map.update(file_map)
        stats = ConversionStats(
            copied=stats.copied + file_stats.copied,
            mining=stats.mining + file_stats.mining,
            non_mining=stats.non_mining + file_stats.non_mining,
        )
        print(
            f"{src.name}: copied={file_stats.copied} "
            f"mining={file_stats.mining} non_mining={file_stats.non_mining}"
        )

    if not dry_run:
        write_index(output_dir, total_size, weight_map)
    return stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Local model directory or Hugging Face model id")
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--hf-token-env", default="HF_TOKEN")
    parser.add_argument("--device", default="cpu", help="cpu or cuda")
    parser.add_argument("--chunk-rows", type=int, default=4096)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stats = convert_checkpoint(
        args.source,
        args.output_dir,
        hf_token_env=args.hf_token_env,
        device=args.device,
        chunk_rows=args.chunk_rows,
        dry_run=args.dry_run,
    )
    print(
        "total: "
        f"copied={stats.copied} mining={stats.mining} non_mining={stats.non_mining}"
    )
    if args.dry_run:
        print("dry run only; no checkpoint was written")


if __name__ == "__main__":
    main()
