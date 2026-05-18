"""Tests for the experimental Pearl model converter script."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
safetensors_torch = pytest.importorskip("safetensors.torch")
load_file = safetensors_torch.load_file
save_file = safetensors_torch.save_file


def _load_converter():
    path = Path(__file__).parents[2] / "scripts" / "pearl" / "model_converter.py"
    spec = importlib.util.spec_from_file_location("pearl_model_converter", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_converter_quantizes_linear_weights_and_writes_pearl_config(
    tmp_path: Path,
) -> None:
    converter = _load_converter()
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "config.json").write_text(
        json.dumps({"architectures": ["TinyForCausalLM"], "model_type": "tiny"})
    )
    (src / "tokenizer_config.json").write_text("{}")
    save_file(
        {
            "model.embed_tokens.weight": torch.ones(4, 4, dtype=torch.bfloat16),
            "model.embed_tokens_per_layer.weight": torch.full(
                (4, 4), 2, dtype=torch.bfloat16
            ),
            "model.layers.0.self_attn.q_proj.weight": torch.arange(
                16, dtype=torch.float32
            ).reshape(4, 4),
            "model.layers.0.self_attn.o_proj.weight": torch.arange(
                16, dtype=torch.float32
            ).reshape(4, 4),
            "model.layers.0.input_layernorm.weight": torch.ones(4),
        },
        src / "model.safetensors",
    )

    stats = converter.convert_checkpoint(
        str(src),
        out,
        hf_token_env="HF_TOKEN",
        device="cpu",
        chunk_rows=2,
        dry_run=False,
    )

    assert stats.non_mining == 1
    assert stats.mining == 1
    tensors = load_file(out / "model.safetensors")
    assert tensors["model.layers.0.self_attn.q_proj.weight"].dtype == torch.int8
    assert tensors["model.layers.0.self_attn.o_proj.weight"].dtype == torch.int8
    assert tensors["model.layers.0.self_attn.q_proj.weight_scale"].shape == (4, 1)
    assert tensors["model.layers.0.self_attn.o_proj.weight_scale"].shape == (4, 1)
    assert tensors["model.embed_tokens.weight"].dtype == torch.bfloat16
    assert tensors["model.embed_tokens_per_layer.weight"].dtype == torch.bfloat16
    assert "model.embed_tokens_per_layer.weight_scale" not in tensors

    config = json.loads((out / "config.json").read_text())
    assert config["quantization_config"]["quant_method"] == "pearl"
    assert (
        config["quantization_config"]["config_groups"]["group_1"]["weights"]["num_bits"]
        == 7
    )
    assert "re:.*visual.*" in config["quantization_config"]["ignore"]
    assert "re:.*embed_tokens_per_layer$" in config["quantization_config"]["ignore"]
    index = json.loads((out / "model.safetensors.index.json").read_text())
    assert "model.layers.0.self_attn.o_proj.weight_scale" in index["weight_map"]


def test_converter_adds_gemma4_preprocessor_compat_file(
    tmp_path: Path,
) -> None:
    converter = _load_converter()
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    (src / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Gemma4ForConditionalGeneration"],
                "model_type": "gemma4",
            }
        )
    )
    (src / "processor_config.json").write_text('{"processor_class":"Gemma4Processor"}')
    (src / "tokenizer_config.json").write_text("{}")
    save_file(
        {
            "language_model.model.layers.0.self_attn.q_proj.weight": torch.arange(
                16, dtype=torch.float32
            ).reshape(4, 4),
        },
        src / "model.safetensors",
    )

    converter.convert_checkpoint(
        str(src),
        out,
        hf_token_env="HF_TOKEN",
        device="cpu",
        chunk_rows=2,
        dry_run=False,
    )

    assert (out / "processor_config.json").exists()
    assert (out / "preprocessor_config.json").exists()
