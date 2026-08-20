# tests/evals/core/test_config_split_parsing.py
"""Regression: the `split` key under [[benchmarks]] is parsed and plumbed."""

from __future__ import annotations

from pathlib import Path

from openjarvis.evals.core.config import load_eval_config


def _write_config(tmp_path: Path, split_value: str | None) -> Path:
    split_line = f'split = "{split_value}"' if split_value else ""
    toml = f"""
[meta]
name = "split-parse-test"

[run]
output_dir = "{tmp_path / "out"}"
seed = 42

[[models]]
name = "dummy-model"
engine = "noop"

[[benchmarks]]
name = "gaia"
backend = "jarvis-agent"
{split_line}
max_samples = 10
"""
    p = tmp_path / "eval.toml"
    p.write_text(toml)
    return p


def test_split_parsed_when_present(tmp_path: Path):
    p = _write_config(tmp_path, "test")
    cfg = load_eval_config(p)
    assert cfg.benchmarks[0].split == "test"


def test_split_absent_becomes_none(tmp_path: Path):
    p = _write_config(tmp_path, None)
    cfg = load_eval_config(p)
    assert cfg.benchmarks[0].split is None


def test_split_train_value(tmp_path: Path):
    p = _write_config(tmp_path, "train")
    cfg = load_eval_config(p)
    assert cfg.benchmarks[0].split == "train"


def test_split_all_value(tmp_path: Path):
    p = _write_config(tmp_path, "all")
    cfg = load_eval_config(p)
    assert cfg.benchmarks[0].split == "all"


def test_split_plumbs_to_agent_eval_config(tmp_path: Path):
    """End-to-end: parsed split flows into RunConfig.dataset_split
    which is what runner.py passes to ds.load(split=...)."""
    p = _write_config(tmp_path, "test")
    cfg = load_eval_config(p)
    # Pull out one expanded RunConfig (model x benchmark product)
    from openjarvis.evals.core.config import expand_suite

    run_cfgs = list(expand_suite(cfg))
    assert len(run_cfgs) >= 1
    assert run_cfgs[0].dataset_split == "test"
